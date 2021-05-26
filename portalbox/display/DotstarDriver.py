"""
2021-05-26 Version   KJHass
  - Change end frame for Dotstar compatibility issue
    https://cpldcpu.wordpress.com/2016/12/13/sk9822-a-clone-of-the-apa102/
"""
import logging
import os
import signal

import multiprocessing
import time
import spidev

# Brightness parameters
# For Dotstars, brightness is a 5-bit value from 0 to 31
DEFAULT_BRIGHTNESS = 16
MAX_PULSE_BRIGHTNESS = 30
MIN_PULSE_BRIGHTNESS = 3
PULSE_BRIGHTNESS_STEP = 2
# Color definitions
BLACK = (0, 0, 0)
DARKRED = (16, 0, 0)

# The driver runs in an infinite loop, checking for new commands or updating
# the pixels. This is the duration of each loop, in milliseconds.
LOOP_MS = 100


class DotstarStrip:
    """
    A simple class definition for a strip of Dotstars.

    A pixel's color is stored as a red/green/blue tuple but the order that
    colors are transmitted to a Dotstar is red-blue-green.
    """

    def __init__(self, length, spi_bus, spi_device):
        logging.info("DRVR Creating DotstarStrip")
        # number of pixels in the strip
        self.length = length
        # each pixel has its own brightness and color tuple
        self.brightness = [DEFAULT_BRIGHTNESS] * length
        self.led_colors = [BLACK] * length

        self.is_pulsing = False
        self.brightness_step = 0
        self.pulse_rising = False

        self.is_blinking = False
        self.blink_color = BLACK

        self.is_wiping = False
        self.wipe_color = BLACK

        self.total_duration = 0
        self.step_ms = 0
        self.effect_time = 0

        # Create signal handlers
        signal.signal(signal.SIGTERM, self.catch_signal)
        signal.signal(signal.SIGINT, self.catch_signal)
        self.signalled = False

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
        # for red, green, blue in self.led_colors:  # swap blue, green order
        for pixel in range(self.length):
            self.spi.writebytes(
                [
                    0xE0 + self.brightness[pixel],
                    self.led_colors[pixel][0],
                    self.led_colors[pixel][2],
                    self.led_colors[pixel][1],
                ]
            )
        self.spi.writebytes([0x00] * 4)  # SK9822 frame
        self.spi.writebytes([0x00] * (self.length // 16 + 1))  # end frame

    def catch_signal(self, signum, frame):
        logging.info("DRVR caught signal")
        self.signalled = True

def process_command(command, led_strip):
    """
    Process command strings from the controller.

    The length of these strings is verified in the abstract base class, which
    also verifies the integer parameter ranges.
    """
    errno = 0

    # split the string into a list of tokens
    tokens = command.split()
    params = [int(token) for token in tokens[1:]]

    logging.info("DRVR received command")

    # get command part of string and determine if it is recognized
    if tokens[0] == "blink":
        # Receiving a blink command aborts wiping or pulsing
        led_strip.is_wiping = False
        led_strip.is_pulsing = False
        # the blink command requires a color tuple, a duration (ms),
        # and a repeat count as inputs
        red, green, blue, led_strip.duration, led_strip.repeats = params
        led_strip.fill_pixels((red, green, blue))
        led_strip.is_blinking = True

        # Initialize effect parameters
        led_strip.effect_time = 0
        # a blink starts will all pixels dark
        led_strip.set_brightness(MIN_PULSE_BRIGHTNESS)
        # Calculate the time for each half-blink, round to nearest loop
        # duration. This is integer math!
        led_strip.wait_ms = led_strip.duration // (2 * led_strip.repeats)
        led_strip.wait_ms = (led_strip.wait_ms + (LOOP_MS // 2)) // LOOP_MS * LOOP_MS
        if led_strip.wait_ms < LOOP_MS:
            led_strip.wait_ms = LOOP_MS

        # Calculate the actual duration of the effect, using the calculated
        # duration for each blink
        led_strip.duration = led_strip.wait_ms * 2 * led_strip.repeats

    elif tokens[0] == "wipe":
        # Receiving a wipe command aborts blinking or pulsing
        led_strip.is_blinking = False
        led_strip.is_pulsing = False
        # The wipe command changes the pixel colors one pixel at a time.
        # The command requires four integer values: red, green, blue, and
        # duration. Duration is milliseconds.
        red, green, blue, led_strip.duration = params
        led_strip.wipe_color = (red, green, blue)

        led_strip.is_wiping = True
        led_strip.set_brightness(DEFAULT_BRIGHTNESS)
        led_strip.effect_time = 0

        # Calculate the time for each half-blink, round to nearest 100ms,
        # minimum is 100ms. This is integer math!
        led_strip.wait_ms = led_strip.duration // led_strip.length
        led_strip.wait_ms = (led_strip.wait_ms + (LOOP_MS // 2)) // LOOP_MS * LOOP_MS
        if led_strip.wait_ms < LOOP_MS:
            led_strip.wait_ms = LOOP_MS
        # Calculate the actual duration of the effect, using the calculated
        # duration for each blink
        led_strip.duration = led_strip.wait_ms * led_strip.length

        # Change the first pixel color to the wipe color
        led_strip.set_pixel_color(led_strip.wipe_color, 0)

    elif tokens[0] == "color":
        # Receiving a color command aborts wiping in process
        led_strip.is_wiping = False

        # The color command sets all of the pixels to the same color.
        # The command requires three integer values: red, green, and blue.
        red, green, blue = params

        # Setting the color to black aborts all other effects
        if (red, green, blue) == BLACK:
            led_strip.is_blinking = False
            led_strip.is_pulsing = False

        # Go to default brightness if no other effect in progress
        if not led_strip.is_blinking and not led_strip.is_pulsing:
            led_strip.set_brightness(DEFAULT_BRIGHTNESS)

        led_strip.fill_pixels((red, green, blue))

    elif tokens[0] == "pulse":
        # Receiving a pulse command aborts blinking or wiping
        led_strip.is_blinking = False
        led_strip.is_wiping = False
        # The pulse command changes the brightness of all pixels so they are
        # pulsing. The pulse rate is hard coded using constant parameters.
        # The command requires three integer values: red, green, and blue.
        red, green, blue = params
        led_strip.fill_pixels((red, green, blue))

        # If already pulsing then only the color can change, else initialize
        # all pulse parameters.
        if not led_strip.is_pulsing:
            led_strip.set_brightness(DEFAULT_BRIGHTNESS)
            led_strip.is_pulsing = True
            led_strip.pulse_rising = False
    else:
        errno = 1

    return errno


def strip_driver(command_queue, led_count, spi_bus, spi_dev):
    """
    This is the main process of the driver.

    It waits until a command is received or the queue "get" times out.
    If the "get" times out then we handle a single step of any current effect.
    This is an infinite loop.
    """
    # Create and initialize an LED strip
    led_strip = DotstarStrip(led_count, spi_bus, spi_dev)
    led_strip.show()

    # loop forever (until OS kills us)
    while not led_strip.signalled:
        # Wait up to LOOP_MS for a command.
        try:
            command = command_queue.get(True, (LOOP_MS / 1000))
            process_command(command, led_strip)
            command_queue.task_done()
        except:
            if led_strip.is_blinking:
                # Are we done blinking?
                if led_strip.effect_time < led_strip.duration:
                    # Is the current effect time an even or odd multiple of
                    # the wait_ms time? If even, go to low brightness level.
                    if (led_strip.effect_time // led_strip.wait_ms) % 2 == 0:
                        led_strip.set_brightness(MIN_PULSE_BRIGHTNESS)
                    # If odd, go to high brightness level.
                    else:
                        led_strip.set_brightness(MAX_PULSE_BRIGHTNESS)

                    led_strip.effect_time = led_strip.effect_time + LOOP_MS
                # Done blinking.
                else:
                    led_strip.is_blinking = False

            if led_strip.is_wiping:
                # Are we done wiping?
                if led_strip.effect_time < led_strip.duration:
                    # After each wait_ms we change the color of the next LED
                    index = led_strip.effect_time // led_strip.wait_ms
                    led_strip.set_pixel_color(led_strip.wipe_color, index)
                    led_strip.effect_time = led_strip.effect_time + LOOP_MS
                # Done wiping. Maker sure all LEDs have the final color.
                else:
                    led_strip.is_wiping = False
                    led_strip.fill_pixels(led_strip.wipe_color)

            if led_strip.is_pulsing:
                # All pixels will have the same brightness. Get that value
                # from pixel 0
                brightness = led_strip.brightness[0]
                # If getting brighter, add to the brightness
                if led_strip.pulse_rising:
                    brightness += PULSE_BRIGHTNESS_STEP
                    if brightness >= MAX_PULSE_BRIGHTNESS:
                        led_strip.pulse_rising = False
                        brightness = MAX_PULSE_BRIGHTNESS
                # If getting darker, subtract from the brightness
                else:
                    brightness -= PULSE_BRIGHTNESS_STEP
                    if brightness <= MIN_PULSE_BRIGHTNESS:
                        led_strip.pulse_rising = True
                        brightness = MIN_PULSE_BRIGHTNESS
                # Set all pixels to the new brightness level.
                led_strip.set_brightness(brightness)

            # Send the new brightness and color values out to the Dotstars
            led_strip.show()

    # Caught TERM or KILL from OS
    # Set the LEDs to a dim red
    logging.info("DRVR stopping")
    led_strip.brightness = [MIN_PULSE_BRIGHTNESS] * led_strip.length
    led_strip.led_colors = [DARKRED] * led_strip.length
    led_strip.is_pulsing = False
    led_strip.is_blinking = False
    led_strip.is_wiping = False
    led_strip.show()
