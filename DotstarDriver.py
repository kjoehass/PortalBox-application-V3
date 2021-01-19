import multiprocessing
import time
import spidev

# Brightness parameters
# For Dotstars, brightness is a 5-bit value from 0 to 31
DEFAULT_BRIGHTNESS = 16
MAX_PULSE_BRIGHTNESS = 30
MIN_PULSE_BRIGHTNESS = 3
PULSE_BRIGHTNESS_STEP = 2
BLACK = (0, 0, 0)

LOOP_MS = 100

class DotstarStrip:
    """
    A simple class definition for a strip of Dotstars.

    A pixel's color is stored as a red/green/blue tuple but the order that
    colors are transmitted to a Dotstar is red-blue-green.
    """

    def __init__(self, length, spi_bus, spi_device):
        self.length = length
        #self.brightness = DEFAULT_BRIGHTNESS
        self.brightness = [DEFAULT_BRIGHTNESS] * length
        self.led_colors = [(0x00, 0x00, 0x00)] * length

        self.is_pulsing = False
        self.brightness_step = 0
        self.pulse_rising = False

        self.is_blinking = False
        self.blink_color = (0x00, 0x00, 0x00)

        self.is_wiping = False
        self.wipe_color = (0x00, 0x00, 0x00)

        self.total_duration = 0
        self.step_ms = 0
        self.effect_time = 0

        # Connect this driver to a specific SPI interface, which should
        # have been enabled in /boot/config.txt
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = 100000
        self.spi.mode = 0
        self.spi.bits_per_word = 8
        self.spi.no_cs = True

    def set_brightness(self, brightness):
        """Set the common brightness value for all pixels"""
        #self.brightness = brightness
        self.brightness = [brightness] * self.length

    def set_pixel_brightness(self, brightness, number):
        """Set the brightness value of one pixel"""
        self.brightness[number] = brightness

    def fill_pixels(self, color):
        """Change the color of all pixels."""
        self.led_colors = [(color)] * self.length

    def set_pixel_color(self, color, number):
        """Change the color of a single pixel."""
        self.led_colors[number] = color

    def show(self):
        """Transmit the desired brightness and colors to the Dotstars.

        The dotstars require a "begin frame" consisting of four all-zero
        bytes before actual data is sent, and an "end frame" of four all-one
        bytes after the data is sent
        """
        self.spi.writebytes([0x00] * 4)  # begin frame
        #for red, green, blue in self.led_colors:  # swap blue, green order
        for pixel in range(self.length):
            self.spi.writebytes([0xE0 + self.brightness[pixel],
                                        self.led_colors[pixel][0],
                                        self.led_colors[pixel][2],
                                        self.led_colors[pixel][1]])
        self.spi.writebytes([0xFF] * 4)  # end frame

def process_command(command, led_strip):
    """
    Process command strings from the controller.

    The length of these strings is verified in the abstract base class, which
    also verifies the integer parameter ranges.
    """
    errno = 0

    # Receiving a new command aborts any command in process
    led_strip.is_blinking = False
    led_strip.is_wiping = False
    led_strip.is_pulsing = False
    led_strip.set_brightness(DEFAULT_BRIGHTNESS)
    led_strip.effect_time = 0

    # split the string into a list of tokens
    tokens = command.split()
    params = [int(token) for token in tokens[1:]]

    # get command part of string and determine if it is recognized
    if tokens[0] == "blink":
        # the blink command requires a color as three components, a duration,
        # and a repeat as inputs
        red, green, blue, led_strip.duration, led_strip.repeats = params
        led_strip.fill_pixels( (red, green, blue) )
        led_strip.is_blinking = True

        # Calculate the time for each half-blink, round to nearest 100ms,
        # minimum is 100ms
        led_strip.wait_ms = led_strip.duration // (2 * led_strip.repeats)
        led_strip.wait_ms = ((led_strip.wait_ms + (LOOP_MS // 2)) // LOOP_MS) * LOOP_MS
        if led_strip.wait_ms < LOOP_MS:
            led_strip.wait_ms = LOOP_MS
        led_strip.duration = led_strip.wait_ms * 2 * led_strip.repeats

        # a blink starts will all pixels dark
        led_strip.set_brightness(MIN_PULSE_BRIGHTNESS)

    elif tokens[0] == "wipe":
        # The wipe command changes the pixel colors one pixel at a time.
        # The command requires four integer values: red, green, blue, and
        # duration. Duration is milliseconds.
        red, green, blue, led_strip.duration = params
        led_strip.wipe_color = (red, green, blue)
        led_strip.is_wiping = True

        # Calculate the time for each half-blink, round to nearest 100ms,
        # minimum is 100ms
        led_strip.wait_ms = led_strip.duration // led_strip.length
        led_strip.wait_ms = ((led_strip.wait_ms + (LOOP_MS // 2)) // LOOP_MS) * LOOP_MS
        if led_strip.wait_ms < LOOP_MS:
            led_strip.wait_ms = LOOP_MS
        led_strip.duration = led_strip.wait_ms * led_strip.length

        led_strip.set_pixel_color(led_strip.wipe_color, 0)
    elif tokens[0] == "color":
        # The color command sets all of the pixels to the same color.
        # The command requires three integer values: red, green, and blue.
        red, green, blue = params
        led_strip.fill_pixels( (red, green, blue) )

    elif tokens[0] == "pulse":
        # The pulse command changes the brightness of all pixels so they are
        # pulsing. The pulse rate is hard coded using constant parameters.
        # The command requires three integer values: red, green, and blue.
        red, green, blue = params

        led_strip.is_pulsing = True
        led_strip.pulse_rising = False
        led_strip.fill_pixels( (red, green, blue) )

    else:
        errno = 1

    return errno


def strip_driver(command_queue, led_count, spi_bus, spi_dev):
    """
    This is the main process of the driver.

    It waits until a command is received or the queue "get" times out.
    If the "get" times out then we handle a single step of any current effect.
    """
    # Create and initialize an LED strip
    led_strip = DotstarStrip(led_count, spi_bus, spi_dev)
    led_strip.show()

    # loop forever
    while True:
        # Wait up to 0.1s for a command.
        try:
            command = command_queue.get(True, 0.1)
            process_command(command, led_strip)
            command_queue.task_done()
        except:
            if led_strip.is_blinking:
                if led_strip.effect_time < led_strip.duration:
                    if (led_strip.effect_time // led_strip.wait_ms) % 2 == 0:
                        led_strip.set_brightness(MIN_PULSE_BRIGHTNESS)
                    else:
                        led_strip.set_brightness(MAX_PULSE_BRIGHTNESS)

                    led_strip.effect_time = led_strip.effect_time + LOOP_MS
                else:
                    led_strip.is_blinking = False

            if led_strip.is_wiping:
                if led_strip.effect_time < led_strip.duration:
                    index = led_strip.effect_time // led_strip.wait_ms
                    led_strip.set_pixel_color(led_strip.wipe_color, index)
                    led_strip.effect_time = led_strip.effect_time + LOOP_MS
                else:
                    led_strip.is_wiping = False
                    led_strip.fill_pixels(led_strip.wipe_color)

            if led_strip.is_pulsing:
                # All pixels will have the same brightness
                # Is this OK?
                brightness = led_strip.brightness[0]
                if led_strip.pulse_rising:
                    brightness += PULSE_BRIGHTNESS_STEP
                    if brightness >= MAX_PULSE_BRIGHTNESS:
                        led_strip.pulse_rising = False
                        brightness = MAX_PULSE_BRIGHTNESS
                else:
                    brightness -= PULSE_BRIGHTNESS_STEP
                    if brightness <= MIN_PULSE_BRIGHTNESS:
                        led_strip.pulse_rising = True
                        brightness = MIN_PULSE_BRIGHTNESS
                led_strip.set_brightness(brightness)

            led_strip.show()
