#!python3

# PortalBox.py acts as a hardware abstraction layer exposing a somewhat
# simple API to the hardware

# from standard library
import logging
from time import sleep

# third party
import RPi.GPIO as GPIO
from neopixel import *
from MFRC522 import MFRC522

# Constants defining how peripherals are connected
REVISION_ID_RASPBERRY_PI_0_W = "9000c1"

GPIO_INTERLOCK_PIN = 11
GPIO_BUZZER_PIN = 33
GPIO_BUTTON_PIN = 35
GPIO_SOLID_STATE_RELAY_PIN = 37

LED_COUNT      = 15     # Number of LED pixels.
LED_PIN        = 18     # GPIO pin connected to the pixels (must support PWM!).
LED_FREQ_HZ    = 800000 # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 5      # DMA channel to use for generating signal (try 5)
LED_BRIGHTNESS = 255    # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False  # True to invert the signal (when using NPN transistor level shift)

BLACK = Color(0,0,0)

# Utility functions
def get_revision():
        file = open("/proc/cpuinfo","r")
        for line in file:
            if "Revisio" in line:
                file.close()
                return line.rstrip().split(' ')[1]
        file.close()
        return -1


def wheel(pos):
    """Generate rainbow colors across 0-255 positions."""
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)

class PortalBox:
    '''
    Wrapper to manage peripherals
    '''
    def __init__(self):
        #detect raspberry pi version
        self.is_pi_zero_w = REVISION_ID_RASPBERRY_PI_0_W == get_revision()

        ## set GPIO to known good state
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)

        ## GPIO pin assignments and initializations
        GPIO.setup(GPIO_INTERLOCK_PIN, GPIO.OUT)
        GPIO.setup(GPIO_BUZZER_PIN, GPIO.OUT)
        GPIO.setup(GPIO_SOLID_STATE_RELAY_PIN, GPIO.OUT)

        GPIO.setup(GPIO_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.add_event_detect(GPIO_BUTTON_PIN, GPIO.RISING)

        self.set_equipment_power_on(False)

        ## Create NeoPixel object with appropriate configuration.
        self.strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
        self.strip.begin()

        # Create a proxy for the RFID card reader
        self.RFIDReader = MFRC522()

        # set up some state
        self.sleepMode = False


    def set_equipment_power_on(self, state):
        '''
        Turn on/off power to the attached equipment by swithing on/off relay
            and interlock
        @param (boolean) state - True to turn on power to equipment, False to
            turn off power to equipment
        '''
        ## Turn off power to SSR
        GPIO.output(GPIO_SOLID_STATE_RELAY_PIN, state)
        ## Open interlock
        if self.is_pi_zero_w:
            GPIO.output(GPIO_INTERLOCK_PIN, state)
        else:
            GPIO.output(GPIO_INTERLOCK_PIN, (not state))


    def set_buzzer(self, state):
        '''
        :param state: True -> Buzzer On; False -> Buzzer Off
        :return: None
        '''
        GPIO.output(GPIO_BUZZER_PIN, state)


    def get_button_state(self):
        '''
        Determine the current button state
        '''
        if GPIO.input(GPIO_BUTTON_PIN):
            return True
        else:
            return False


    def has_button_been_pressed(self):
        '''
        Use GPIO event detection to determine if the button has been pressed
        since the last call to this method
        '''
        return GPIO.event_detected(GPIO_BUTTON_PIN)


    def read_RFID_card(self):
        '''
        @return a positive integer representing the uid from the card on a
            successful read, -1 otherwise
        '''
        # Scan for cards
        (status, TagType) = self.RFIDReader.MFRC522_Request(MFRC522.PICC_REQIDL)
        logging.debug("MFRC522 Request returned: %s, %s", status, TagType)

        if MFRC522.MI_OK == status:
            # Get the UID of the card
            (status, uid) = self.RFIDReader.MFRC522_Anticoll()
            logging.debug("MFRC522 Request returned: %s, %s", status, uid)

            if MFRC522.MI_OK == status:
                # We have the UID, generate unsigned integer
                # uid is a MSB order byte array of theoretically 4 bytes
                result = 0
                for i in range(4):
                    result += (uid[i] << (8 * (3 - i)))
                return result
            return -1
        return -1

    def wake_display(self):
        self.sleepMode = False


    def sleep_display(self, wait_ms=10, iterations=1):
        '''
        Sets LED display to a pulsating rainbow... running as a thread is left
        to the caller
        
        :param strip: LED strip
        :param wait_ms: factor in rainbow pattern speed
        :param iterations: factor in rainbow pattern speed
        :return: None
        '''
        i = 0
        self.sleepMode = True
        while self.sleepMode:
            for j in range(256*iterations): #5.12 seconds if iterations = 1
                if self.sleepMode:
                    for i in range(self.strip.numPixels()):
                        self.strip.setPixelColor(i, wheel(((i * 256 / self.strip.numPixels()) + j) & 255))
                    self.strip.show()
                    sleep(wait_ms/1000.0)
                else:
                    break
            i += 1


    def set_display_color(self, color = BLACK):
        '''
        Set the entire strip to specified color.
        @param (unsigned integer) color - the color to set defaults to LED's off
        '''
        self.sleepMode = False
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, color)
        self.strip.show()


    def set_display_color_wipe(self, color, speed):
        '''
        Set the entire strip to specified color using a "wipe" effect.
        @param (unsigned integer) color - the color to set
        @param (int) speed -  how fast to wipe in color, one pixel every n ms
        '''
        self.sleepMode = False
        for i in range(self.strip.numPixels()):
            self.strip.setPixelColor(i, color)
            self.strip.show()
            sleep(speed/1000.0)


    def flash_display(self, color, wait_ms=150, flashes=5):
        """Flash color across all display pixels multiple times."""
        self.sleepMode = False
        num_pixels = self.strip.numPixels()
        for j in range(flashes):
            for i in range(num_pixels):
                self.strip.setPixelColor(i, color)
            self.strip.show()
            sleep(wait_ms/1000.0)
            for i in range(num_pixels):
                self.strip.setPixelColor(i, Color(0,0,0))
            self.strip.show()
            sleep(wait_ms/1000.0)


    def cleanup(self):
        self.set_buzzer(False)
        self.set_display_color()
        GPIO.cleanup()


# Rest of this file is the test suite. Use `python3 Database.py` to run
# check prevents running of test suite if loading (import) as a module
if __name__ == "__main__":
    # import extras only needed for testing
    from time import sleep
    import signal

    def quit(signal,frame):
        global box
        box.cleanup()
        exit()

    # Init logging
    logging.basicConfig(format='%(message)s', level=logging.DEBUG)

    box = PortalBox()

    # Register a handler to turn off LEDs if CRTL C'd
    signal.signal(signal.SIGINT, quit)

    box.set_buzzer(True)
    sleep(0.25)
    box.set_buzzer(False)

    logging.info("Power: off; LEDs: red")
    box.set_display_color(Color(0,255,0))   # red
    sleep(5)

    logging.info("Test polling button (Please press the button)")
    is_button_pressed = False
    count = 0
    while not is_button_pressed and count < 60:
        is_button_pressed = box.get_button_state()
        if is_button_pressed:
            logging.info("Button was pressed")
        sleep(1)
        count += 1
    
    sleep(2) # give human chance to release button

    logging.info("Test button event detection (Please press the button)")
    box.has_button_been_pressed() # clear pending events
    sleep(5)
    if box.has_button_been_pressed():
        logging.info("Button was pressed")

    logging.info("Please present RFID card")
    uid = -1
    count = 0
    while uid < 0 and count < 60:
        uid = box.read_RFID_card()
        if -1 < uid:
            logging.info("RFID Card: %s", uid)
        sleep(1)
        count += 1

    logging.info("Power: on; LEDs: green")
    box.set_equipment_power_on(True)
    box.set_display_color(Color(255,0,0))   # green
    sleep(5)

    logging.info("Power: off; LEDs: sleep")
    box.set_equipment_power_on(False)
    box.sleep_display()
