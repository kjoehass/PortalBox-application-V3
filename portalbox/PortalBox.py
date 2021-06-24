#!python3

# PortalBox.py acts as a hardware abstraction layer exposing a somewhat
# simple API to the hardware
"""
2021-06-09 Version   KJHass
  - Supports either Neopixels or DotStars

2021-05-12 Version   KJHass
  - read card twice before returning card id number or -1
  - don't read RFID reader version for debugging, it doesn't help

2021-03-25 Version   KJHass
  - imports os and periodically writes to files in /tmp to feed the watchdog
  - defines colors RED and YELLOW for display if RFID hangs
  - verifies that RFID serial # is correct, else decide RFID hanging
  - verifies that another specific register in RFID is valid, else decide
    that RFID is hanging
  - if the RFID hangs, go into an infinite loop of beeping and flashing, wait
    for the watchdog timer to restart this service
  - defines the NRST pin for the RFID module, defines it as an output, and
    sets its state appropriately
  - adds more logging for debugging purposes
"""
# from standard library
import os
import logging
from time import sleep

# Our libraries
from .display.AbstractController import BLACK

# third party
import RPi.GPIO as GPIO
#from mfrc522 import MFRC522
from .MFRC522 import MFRC522

# Constants defining how peripherals are connected
#FIXME Add RPi4?
REVISION_ID_RASPBERRY_PI_0_W = "9000c1"
#FIXME Get this from config file
LEDS = "DOTSTARS"

GPIO_INTERLOCK_PIN = 11
GPIO_BUZZER_PIN = 33
GPIO_BUTTON_PIN = 35
GPIO_SOLID_STATE_RELAY_PIN = 37
GPIO_RFID_NRST_PIN = 13

#FIXME Get from config file
RED = b'\xFF\x00\x00'
YELLOW = b'\xFF\x80\x00'

# Utility functions
def get_revision():
        file = open("/proc/cpuinfo","r")
        for line in file:
            if "Revisio" in line:
                file.close()
                return line.rstrip().split(' ')[1]
        file.close()
        return -1


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

        # Reset the RFID card
        GPIO.setup(GPIO_RFID_NRST_PIN, GPIO.OUT)
        GPIO.output(GPIO_RFID_NRST_PIN, False)

        GPIO.setup(GPIO_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.add_event_detect(GPIO_BUTTON_PIN, GPIO.RISING)

        self.set_equipment_power_on(False)

        # Create display controller
        if LEDS == "DOTSTARS":
            logging.debug("Creating DotStar display controller")
            from .display.DotstarController import DotstarController
            self.display_controller = DotstarController()
        elif LEDS == "NEOPIXELS":
            logging.debug("Creating Neopixel display controller")
            from .display.R2NeoPixelController import R2NeoPixelController
            self.display_controller = R2NeoPixelController()
        else:
            logging.info("No display driver!")
            self.display_controller = None

        # Deassert NRST
        GPIO.output(GPIO_RFID_NRST_PIN, True)

        # Create a proxy for the RFID card reader
        logging.debug("Creating RFID reader")
        self.RFIDReader = MFRC522()

        # set up some state
        self.sleepMode = False
        # keep track of values in RFID module registers
        self.outlist = [0] * 64


    def set_equipment_power_on(self, state):
        '''
        Turn on/off power to the attached equipment by swithing on/off relay
            and interlock
        @param (boolean) state - True to turn on power to equipment, False to
            turn off power to equipment
        '''
        if state:
            logging.info("Turning on equipment power and interlock")
            os.system("echo True > /tmp/running")
        else:
            logging.info("Turning off equipment power and interlock")
            os.system("echo False > /tmp/running")
        ## Turn off power to SSR
        GPIO.output(GPIO_SOLID_STATE_RELAY_PIN, state)
        ## Open interlock
        #FIXME  Why? What do we do for Pi4?
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
        rfid_hang = False

        # These three registers appear to change to specific values if the
        # RFID module hangs
        reglist = [17, 20, 21]
        for reg in reglist:
            regval = self.RFIDReader.Read_MFRC522(reg)
            # If register 20 changes from 0x83 to 0x80 then the transmit
            # antennas are turned off
            if (reg == 20) and (self.outlist[reg] == 0x83) and (regval == 0x80):
                rfid_hang = True
            # Log all changes to these three registers
            if regval != self.outlist[reg]:
                logging.info("Reg {0:02x} changed from {1:02x} to {2:02x}".format(reg, self.outlist[reg], regval))
                self.outlist[reg] = regval

       # If the RFID module hangs then we need to restart the portal-box
       # service. This is an infinite loop...the watchdog timer should 
       # detect this and restart the service. Meanwhile, we beep and an
       # flash a red and yellow display
        while rfid_hang:
           self.set_buzzer(True)
           self.set_display_color(RED)
           sleep(0.05)
           self.set_buzzer(False)
           self.set_display_color(YELLOW)
           sleep(10)

        # Scan for card...twice before giving up
        for attempts in range(2):
            (status, TagType) = self.RFIDReader.MFRC522_Request(MFRC522.PICC_REQIDL)

            if MFRC522.MI_OK == status:
                # Get the UID of the card
                (status, uid) = self.RFIDReader.MFRC522_Anticoll()

                if MFRC522.MI_OK == status:
                    # We have the UID, generate unsigned integer
                    # uid is a MSB order byte array of theoretically 4 bytes
                    result = 0
                    for i in range(4):
                        result += (uid[i] << (8 * (3 - i)))
                    # If we found a valid card ID, return it
                    if result > 0:
                        return result

        return -1

    def wake_display(self):
        if self.display_controller:
            self.display_controller.wake_display()
        else:
            logging.info("PortalBox wake_display failed")


    def sleep_display(self):
        '''
        Sets LED display to indicate the box is in a low power mode

        :return: None
        '''
        if self.display_controller:
            self.display_controller.sleep_display()
        else:
            logging.info("PortalBox sleep_display failed")


    def set_display_color(self, color = BLACK):
        '''
        Set the entire strip to specified color.
        @param (bytes len 3) color - the color to set. Defaults to LED's off
        '''
        self.wake_display()
        if self.display_controller:
            self.display_controller.set_display_color(color)
        else:
            logging.info("PortalBox set_display_color failed")


    def set_display_color_wipe(self, color = BLACK, duration = 1000):
        '''
        Set the entire strip to specified color using a "wipe" effect.
        @param (bytes len 3) color - the color to set. Defaults to LED's off
        @param (int) duration -  how long in milliseconds the effect should
                                take.  Defaults to 1 second
        '''
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
