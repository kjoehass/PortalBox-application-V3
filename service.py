#!python3

# from the standard library
import configparser
import logging
import os
import signal
import sys
import threading
from time import sleep, time
from uuid import getnode as get_mac_address

# our code
from portalbox.PortalBox import PortalBox
from Database import Database
from Emailer import Emailer

# Definitions aka constants
DEFAULT_CONFIG_FILE_PATH = "config.ini"

RED = b'\xFF\x00\x00'
GREEN = b'\x00\xFF\x00'
YELLOW = b'\xFF\xFF\x00'
BLUE = b'\x00\x00\xFF'
ORANGE = b'\xDF\x20\x00'

class PortalBoxApplication:
    '''
    wrap code as a class to allow for clean sharing of objects
    between states
    '''
    def __init__(self, settings):
        '''
        Setup the bare minimun, defering as much as poosible to the run method
        so signal handlers can be configured in __main__
        '''
        self.exceeded_time = False
        self.running = False
        self.equipment_id = False
        self.box = PortalBox()
        self.settings = settings


    def __del__(self):
        '''
        free resources after run
        '''
        self.box.cleanup()


    def run(self):
        '''
        Actually get ready to run... we defered initialization in order to
        configure signal handlers in __main__ but they should now be in place
        
        This corresponds to the transition from Start in FSM.odg see docs
        '''
        # Step 1 Do a bit of a dance to show we are running
        self.box.set_display_color_wipe(RED, 10)
        
        # Set 2 Figure out our identity
        mac_address = format(get_mac_address(), 'x')
        logging.debug("Discovered Mac Address: %s", mac_address)

        # connect to backend database
        logging.debug("Connecting to database on host %s", self.settings['db']['host'])
        try:
            self.db = Database(self.settings['db'])
            logging.debug("Connected to Database")
        except Exception as e:
            logging.error("{}".format(e))
            sys.exit(1)

        # be prepared to send emails
        try:
            self.emailer = Emailer(self.settings['email'])
            logging.debug("Cached email settings")
        except Exception as e:
            # should be unreachable
            logging.error("{}".format(e))
            sys.exit(1)

        # give user hint we are makeing progress 
        self.box.set_display_color_wipe(ORANGE, 10)

        # determine what we are
        profile = (-1,)
        self.running = True
        while self.running and 0 > profile[0]:
            profile = self.db.get_equipment_profile(mac_address)
            if 0 > profile[0]:
                sleep(5)

        # only run if we have role, which we might not if systemd asked us to
        # shutdown before we discovered a role
        if 0 < profile[0]:
            # profile:
            #   (int) equipment id
            #   (int) equipment type id
            #   (str) equipment type
            #   (int) location id
            #   (str) location
            #   (int) time limit in minutes
            self.equipment_id = profile[0]
            self.equipment_type_id = profile[1]
            self.location = profile[4]
            self.timeout_period = profile[5]

            logging.info("Discovered identity. Type: %s(%s) Timeout period: %s", profile[2], self.equipment_type_id, self.timeout_period)
            self.db.log_started_status(self.equipment_id)

            self.box.set_display_color_wipe(GREEN, 10)
            self.timeout_period *= 60 # python threading wants seconds, DB has minutes
            self.proxy_uid = -1
            self.training_mode = False
            self.wait_for_access_card()
        else:
            logging.info("Running ending abnormally. Did not discover identity.")


    def wait_for_access_card(self):
        '''
        Wait for a card and if we read a card decide what to do
        '''
        self.box.set_display_color_wipe(BLUE, 15)
        # Run... loop endlessly waiting for RFID cards
        while self.running:
            # Scan for card
            uid = self.box.read_RFID_card()
            if -1 < uid:
                # we read a card... decide what to do
                card_type = self.db.get_card_type(uid)
                logging.debug("Card of type: %s was presented", card_type)
                if Database.SHUTDOWN_CARD == card_type:
                    logging.info("Shutdown Card: %s detected, triggering box shutdown", uid)
                    self.db.log_shutdown_status(self.equipment_id, uid)
                    self.box.set_display_color()
                    os.system("shutdown -h now")
                elif Database.TRAINING_CARD == card_type:
                    if self.db.is_training_card_for_equipment_type(uid, self.equipment_type_id):
                        logging.info("Trainer identitfied by card: %s is authorized to use equipment", uid)
                        self.training_mode = True
                        self.run_session(uid)
                        self.training_mode = False
                    else:
                        self.wait_for_unauthorized_card_removal(uid)
                elif Database.USER_CARD == card_type:
                    if self.db.is_user_authorized_for_equipment_type(uid, self.equipment_type_id):
                        logging.info("User identitfied by card: %s is authorized to use equipment", uid)
                        self.run_session(uid)
                    else:
                        self.wait_for_unauthorized_card_removal(uid)
                else:
                    self.wait_for_unauthorized_card_removal(uid)

                self.box.set_display_color_wipe(BLUE, 15)

            sleep(0.2)


    def run_session(self, user_id):
        '''
        Allow user to use the equipment
        '''
        logging.info("Logging successful activation of equipment to backend database")
        self.db.log_access_attempt(user_id, self.equipment_id, True)
        self.authorized_uid = user_id
        self.box.set_display_color(GREEN)
        self.box.set_equipment_power_on(True)
        if 0 < self.timeout_period:
            self.exceeded_time = False
            self.activation_timeout = threading.Timer(self.timeout_period, self.timeout)
            self.activation_timeout.start()
        self.wait_for_authorized_card_removal()
        if not self.exceeded_time and 0 < self.timeout_period:
            self.activation_timeout.cancel()
        self.box.set_equipment_power_on(False)
        logging.info("Logging completion of equipment access to backend database")
        self.db.log_access_completion(user_id, self.equipment_id)
        self.authorized_uid = -1


    def timeout(self):
        '''
        Called by timer thread when usage time is exceeeded
        '''
        self.exceeded_time = True


    def wait_for_unauthorized_card_removal(self, uid):
        '''
        Wait for card to be removed
        '''
        logging.info("Card: %s is NOT authorized to use equipment", uid)
        self.db.log_access_attempt(uid, self.equipment_id, False)

        # We have to have a grace_counter because consecutive card reads currently fail
        grace_count = 0
        #loop endlessly waiting for shutdown or card to be removed
        while self.running and grace_count < 2:
            # Scan for card
            uid = self.box.read_RFID_card()
            if -1 < uid:
                # we read a card
                grace_count = 0
            else:
                # we did not read a card
                grace_count += 1

            self.box.flash_display(RED, 100, 1, RED)


    def wait_for_authorized_card_removal(self):
        '''
        Wait for card to be removed
        '''
        self.card_present = True
        self.proxy_uid = -1
        # We have to have a grace_counter because consecutive card reads currently fail
        grace_count = 0
        #loop endlessly waiting for shutdown or card to be removed
        while self.running and self.card_present:
            # check for timeout
            if self.exceeded_time:
                self.wait_for_timeout_grace_period_to_expire()
                if self.card_present:
                    # User pressed the button return to running
                    self.exceeded_time = False
                    if self.card_present:
                            grace_count = 0
                            if -1 < self.proxy_uid:
                                self.box.set_display_color(ORANGE)
                            else:
                                self.box.set_display_color(GREEN)
                    self.activation_timeout = threading.Timer(self.timeout_period, self.timeout)
                    self.activation_timeout.start()

            # Scan for card
            uid = self.box.read_RFID_card()
            if -1 < uid and (uid == self.authorized_uid or uid == self.proxy_uid):
                # we read an authorized card
                grace_count = 0
            else:
                # we did not read a card or we read the wrong card
                grace_count += 1

                if grace_count > 2:
                    self.wait_for_user_card_return()
                    if self.card_present:
                        grace_count = 0
                        if -1 < self.proxy_uid:
                            self.box.set_display_color(ORANGE)
                        else:
                            self.box.set_display_color(GREEN)

            sleep(0.1)


    def wait_for_user_card_return(self):
        '''
        Wait for a time for card to return before shutting down, button press
        shuts down immediately.

        We accomplish this using the card_present flag. By setting the flag
        to False immeditely we just return and the outer loop in
        wait_for_authorized_card_removal will also end. If we get the
        authorized card back we can toggle the flag back and return which will
        cause the outer loop to continue
        '''
        self.card_present = False
        self.proxy_uid = -1
        self.box.set_display_color(YELLOW)
        grace_count = 0
        logging.info("Card Removed")
        self.box.has_button_been_pressed() # clear pending events
        while self.running and grace_count < 16:
            # Check for button press
            if self.box.has_button_been_pressed():
                break

            # Scan for card
            uid = self.box.read_RFID_card()
            if -1 < uid:
                # we read a card
                if uid == self.authorized_uid:
                    # card returned
                    self.card_present = True
                    break
                elif not self.training_mode: # trainers may not use proxy cards
                    # check if proxy card
                    if Database.PROXY_CARD == self.db.get_card_type(uid):
                        self.card_present = True
                        self.proxy_uid = uid
                        break

            grace_count += 1
            self.box.set_buzzer(True)
            self.box.flash_display(YELLOW, 100, 1, YELLOW)
            self.box.set_buzzer(False)

        if self.running and not self.card_present:
            logging.debug("Grace period following card removal expired; shutting down equipment")


    def wait_for_timeout_grace_period_to_expire(self):
        logging.info("Equipment usage timeout")
        self.card_present = False # indicate to up stack frames card is gone to end their loops
        grace_count = 0
        self.box.has_button_been_pressed() # clear pending events
        self.box.set_display_color(ORANGE)
        while self.running and grace_count < 600:
            #check for button press
            if self.box.has_button_been_pressed():
                logging.info("Button was pressed, extending time out period")
                self.card_present = True # do not indicate to up stack frames that card is gone so their loops resume
                break
            else:
                grace_count += 1
            
            if 1 > (grace_count % 2):
                self.box.flash_display(ORANGE, 100, 1, ORANGE)

            if 1 > (grace_count % 20):
                self.box.set_buzzer(True)
            else:
                self.box.set_buzzer(False)

            sleep(0.1)

        # endless squeal will get boxes thrown out
        self.box.set_buzzer(False)

        if not self.card_present:
            # shutdown now, do not wait for email or card removal
            self.box.set_equipment_power_on(False)

            # was forgotten card?
            uid = self.box.read_RFID_card()
            uid2 = self.box.read_RFID_card() #try twice since reader fails consecutive reads
            if -1 < uid or -1 < uid2:
                # Card is still present
                self.box.set_display_color_wipe(BLUE, 50)
                user = self.db.get_user(self.authorized_uid)
                self.emailer.send(user[2], "Access Card left in PortalBox", "{} {} it appears you left your access card in a badge box for the {} in the {}".format(user[0], user[1], self.equipment_type_id, self.location))

                # wait for card to be removed... we need to make sure we don't have consecutive read failure
                grace_count = 0
                while self.running and grace_count < 2:
                    # Scan for card
                    uid = self.box.read_RFID_card()
                    if -1 < uid:
                        # card present
                        grace_count = 0
                    else:
                        grace_count += 1

                    self.box.flash_display(RED, 100, 1, RED)


    def exit(self):
        ''' Stop looping in all run states '''
        logging.info("Service Exiting")
        if self.running:
            if self.equipment_id:
                self.db.log_shutdown_status(self.equipment_id, False)
            self.running = False
        else:
            # never made it to the run state
            sys.exit()


    def handle_interupt(self, signum, frame):
        ''' Stop the service from a signal'''
        logging.debug("Interupted")
        self.exit()


# Here is the main entry point.
if __name__ == "__main__":
    config_file_path = DEFAULT_CONFIG_FILE_PATH

    # Look at Command Line for Overrides
    if 1 < len(sys.argv):
        if os.path.isfile(sys.argv[1]):
            # override default config file
            config_file_path = sys.argv[1]
        # else print help message?

    # Read our Configuration
    settings = configparser.ConfigParser()
    settings.read(config_file_path)

    # Setup logging
    if settings.has_option('logging', 'level'):
        if 'critical' == settings['logging']['level']:
            logging.basicConfig(level=logging.CRITICAL)
        elif 'error' == settings['logging']['level']:
            logging.basicConfig(level=logging.ERROR)
        elif 'warning' == settings['logging']['level']:
            logging.basicConfig(level=logging.WARNING)
        elif 'info' == settings['logging']['level']:
            logging.basicConfig(level=logging.INFO)
        elif 'debug' == settings['logging']['level']:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.ERROR)

    # Create Badge Box Service
    service = PortalBoxApplication(settings)

    # Add signal handler so systemd can shutdown service
    signal.signal(signal.SIGINT, service.handle_interupt)
    signal.signal(signal.SIGTERM, service.handle_interupt)
    
    # Run service
    service.run()

    # Cleanup and exit
    logging.shutdown()
