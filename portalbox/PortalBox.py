#!python3

# PortalBox.py acts as a hardware abstraction layer exposing a somewhat
# simple API to the hardware

# from standard library
import os
import logging
from time import sleep

# Our libraries
from .display.AbstractController import BLACK

# third party
import RPi.GPIO as GPIO
from mfrc522 import MFRC522

# Constants defining how peripherals are connected
REVISION_ID_RASPBERRY_PI_0_W = "9000c1"

GPIO_INTERLOCK_PIN = 11
GPIO_BUZZER_PIN = 33
GPIO_BUTTON_PIN = 35
GPIO_SOLID_STATE_RELAY_PIN = 37


# Utility functions
def get_revision():
        file = open("/proc/cpuinfo","r")
        for line in file:
            if "Revisio" in line:
                file.close()
            return line.rstrip().split(" ")[1]
        file.close()
        return -1


class PortalBox:
    """
    Wrapper to manage peripherals
    """

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

        # Create display controller
        if self.is_pi_zero_w:
            logging.debug("Creating display controller")
            from .display.DotstarController import DotstarController

            self.display_controller = DotstarController()
        else:
            logging.info(
                "Did not connect to display driver, display methods will be unavailable"
            )
            self.display_controller = None

        # Create a proxy for the RFID card reader
        logging.debug("Creating RFID reader")
        self.RFIDReader = MFRC522()

        # set up some state
        self.sleepMode = False


    def set_equipment_power_on(self, state):
        """
        Turn on/off power to the attached equipment by swithing on/off relay
            and interlock
        @param (boolean) state - True to turn on power to equipment, False to
            turn off power to equipment
        """
        logging.info("Turning on/off equipment power and interlock")
        if state:
            os.system("echo True > /tmp/running")
        else:
            os.system("echo False > /tmp/running")
        ## Turn on/off power to SSR
        GPIO.output(GPIO_SOLID_STATE_RELAY_PIN, state)
        ## Open/close interlock
        if self.is_pi_zero_w:
            GPIO.output(GPIO_INTERLOCK_PIN, state)
        else:
            GPIO.output(GPIO_INTERLOCK_PIN, (not state))


    def set_buzzer(self, state):
        """
        :param state: True -> Buzzer On; False -> Buzzer Off
        :return: None
        """
        GPIO.output(GPIO_BUZZER_PIN, state)


    def get_button_state(self):
        """
        Determine the current button state
        """
        if GPIO.input(GPIO_BUTTON_PIN):
            return True
        else:
            return False


    def has_button_been_pressed(self):
        """
        Use GPIO event detection to determine if the button has been pressed
        since the last call to this method
        """
        return GPIO.event_detected(GPIO_BUTTON_PIN)


    def read_RFID_card(self):
        """
        @return a positive integer representing the uid from the card on a
            successful read, -1 otherwise
        """
        # Scan for cards

        (status, TagType) = self.RFIDReader.MFRC522_Request(MFRC522.PICC_REQIDL)
#        logging.debug("MFRC522 Request returned: %s, %s", status, TagType)

        if MFRC522.MI_OK == status:
            # Get the UID of the card
            (status, uid) = self.RFIDReader.MFRC522_Anticoll()
            logging.debug("MFRC522 Request returned: %s, %s", status, uid)

            if MFRC522.MI_OK == status:
                # We have the UID, generate unsigned integer
                # uid is a MSB order byte array of theoretically 4 bytes
                result = 0
                for i in range(4):
                    result += uid[i] << (8 * (3 - i))
                return result
            return -1
        return -1

    def wake_display(self):
        if self.display_controller:
            self.display_controller.wake_display()
        else:
            logging.info("PortalBox wake_display failed")


    def sleep_display(self):
        """
        Sets LED display to indicate the box is in a low power mode

        :return: None
        """
        if self.display_controller:
            self.display_controller.sleep_display()
        else:
            logging.info("PortalBox sleep_display failed")


    def set_display_color(self, color = BLACK):
        """
        Set the entire strip to specified color.
        @param (bytes len 3) color - the color to set. Defaults to LED's off
        """
        self.wake_display()
        if self.display_controller:
            self.display_controller.set_display_color(color)
        else:
            logging.info("PortalBox set_display_color failed")


    def set_display_color_wipe(self, color = BLACK, duration = 1000):
        """
        Set the entire strip to specified color using a "wipe" effect.
        @param (bytes len 3) color - the color to set. Defaults to LED's off
        @param (int) duration -  how long in milliseconds the effect should
                                take.  Defaults to 1 second
        """
        self.wake_display()
        if self.display_controller:
            self.display_controller.set_display_color_wipe(color, duration)
        else:
            logging.info("PortalBox color_wipe failed")


    def flash_display(self, color, duration=1000, flashes=5, end_color = BLACK):
        """Flash color across all display pixels multiple times."""
        self.wake_display()
        if self.display_controller:
            self.display_controller.flash_display(color, duration, flashes, end_color)
        else:
            logging.info("PortalBox flash_display failed")


    def cleanup(self):
        logging.info("PortalBox.cleanup() starts")
        os.system("echo False > /tmp/running")
        self.set_buzzer(False)
        self.set_display_color()
        GPIO.cleanup()
