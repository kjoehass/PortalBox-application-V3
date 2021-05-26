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
        os.system("echo portalbox_init > /tmp/boxactivity")
        os.system("echo False > /tmp/running")


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
        os.system("echo False > /tmp/running")

        # Step 1 Do a bit of a dance to show we are running
        logging.info("Setting display color to wipe red")
        self.box.set_display_color_wipe(RED, 10)
        logging.info("Started PortalBoxApplication.run()")
        
        # Set 2 Figure out our identity
        mac_address = format(get_mac_address(), 'x')
        logging.info("Discovered Mac Address: %s", mac_address)

        # connect to backend database
        logging.info("Connecting to database on host %s", self.settings['db']['host'])
        try:
            logging.debug("Creating database instance")
            self.db = Database(self.settings['db'])
            logging.info("Connected to Database")
        except Exception as e:
            logging.error("{}".format(e))
            sys.exit(1)

        # be prepared to send emails
        try:
            logging.info("Creating emailer instance")
            self.emailer = Emailer(self.settings['email'])
            logging.info("Cached email settings")
        except Exception as e:
            # should be unreachable
            logging.error("{}".format(e))
            sys.exit(1)

        # give user hint we are makeing progress 
        logging.debug("Setting display color to wipe orange")
        self.box.set_display_color_wipe(ORANGE, 10)

        # determine what we are
        profile = (-1,)
        self.running = True
        while self.running and 0 > profile[0]:
            os.system("echo equipment_profile > /tmp/boxactivity")
            logging.info("Trying to get equipment profile from DB")
            profile = self.db.get_equipment_profile(mac_address)
            if 0 > profile[0]:
                sleep(10)

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
            self.equipment_type = profile[2]
            self.location = profile[4]
            self.timeout_period = profile[5]

            logging.info("Discovered identity. Type: %s(%s) Timeout: %s",
                    self.equipment_type,
                    self.equipment_type_id,
                    self.timeout_period)
            self.db.log_started_status(self.equipment_id)

            logging.debug("Setting display color to wipe green")
            self.box.set_display_color_wipe(GREEN, 10)
            self.timeout_period *= 60 # python threading wants seconds, DB has minutes
            self.proxy_uid = -1
            self.training_mode = False
            logging.info("Starting to wait for access card")
            self.wait_for_access_card()
        else:
            logging.info("Running ending; did not discover identity.")
            sys.exit(1)


    def wait_for_access_card(self):
        '''
        Wait for a card and if we read a card decide what to do
        '''
        logging.debug("Setting display to sleep display")
        self.box.sleep_display()
        # Run... loop endlessly waiting for RFID cards
        logging.debug("Waiting for an access card")
        while self.running:
            os.system("echo wait_for_a_card > /tmp/boxactivity")
            # Scan for card
            uid = self.box.read_RFID_card()
            if -1 < uid:
                logging.debug("Detected a card, getting type from DB")
                # we read a card... decide what to do
                card_type = self.db.get_card_type(uid)
                logging.debug("Card of type: %s was presented", card_type)
                if Database.SHUTDOWN_CARD == card_type:
                    logging.info("Shutdown card %s detected, shutting down", uid)
                    self.db.log_shutdown_status(self.equipment_id, uid)
                    logging.debug("Blanking display")
                    self.box.set_display_color()
                    logging.debug("Telling OS to shut down")
                    os.system("sync; shutdown -h now")
                elif Database.TRAINING_CARD == card_type:
                    logging.info("Training card %s detected, authorized?", uid)
                    if self.db.is_training_card_for_equipment_type(uid, self.equipment_type_id):
                        logging.info("Trainer %s authorized for %s",
                                      uid, self.equipment_type)
                        self.training_mode = True
                        self.run_session(uid)
                        self.training_mode = False
                    else:
                        self.wait_for_unauthorized_card_removal(uid)
                    logging.debug("Done with training card, start sleep display")
                    self.box.sleep_display()
                elif Database.USER_CARD == card_type:
                    logging.info("User card %s detected, authorized?", uid)
                    if self.db.is_user_authorized_for_equipment_type(uid, self.equipment_type_id):
                        logging.info("User %s authorized for %s",
                                uid,
                                self.equipment_type)
                        self.run_session(uid)
                    else:
                        self.wait_for_unauthorized_card_removal(uid)
                    logging.debug("Done with user card, start sleep display")
                    self.box.sleep_display()
                else:
                    logging.info("Unknown card %s detected", uid)
                    self.wait_for_unauthorized_card_removal(uid)
                    logging.debug("Done with unauthorized card, start sleep display")
                    self.box.sleep_display()

            sleep(0.2)


    def run_session(self, user_id):
        '''
        Allow user to use the equipment
        '''
        logging.info("Logging activation of %s to DB", self.equipment_type)
        self.db.log_access_attempt(user_id, self.equipment_id, True)
        self.authorized_uid = user_id

        self.box.set_buzzer(True)
        sleep(0.05)

        logging.debug("Setting display to green")
        self.box.set_display_color(GREEN)
        self.box.set_equipment_power_on(True)

        self.box.set_buzzer(False)

        if 0 < self.timeout_period:
            self.exceeded_time = False
            logging.debug("Starting equipment timer")
            self.activation_timeout = threading.Timer(self.timeout_period, self.timeout)
            logging.debug("Starting timeout")
            self.activation_timeout.start()
        self.wait_for_authorized_card_removal()
        if not self.exceeded_time and 0 < self.timeout_period:
            logging.debug("Canceling timeout")
            self.activation_timeout.cancel()
        self.box.set_equipment_power_on(False)
        logging.info("Logging end of %s access to DB", self.equipment_type)
        self.db.log_access_completion(user_id, self.equipment_id)
        self.authorized_uid = -1
        logging.debug("run_session() ends")


    def timeout(self):
        '''
        Called by timer thread when usage time is exceeeded
        '''
        logging.info("Timer timed out")
        self.exceeded_time = True


    def wait_for_unauthorized_card_removal(self, uid):
        '''
        Wait for card to be removed
        '''
        logging.info("Card %s NOT authorized for %s", uid, self.equipment_type)
        self.db.log_access_attempt(uid, self.equipment_id, False)

        # We need a grace_counter because consecutive card reads fail
        grace_count = 0

        #loop endlessly waiting for shutdown or card to be removed
        logging.debug("Looping until not running or card removed")
        while self.running and grace_count < 2:
            os.system("echo wait_unauth_remove > /tmp/boxactivity")
            # Scan for card
            uid = self.box.read_RFID_card()
            if -1 < uid:
                # we did read a card
                grace_count = 0
            else:
                # we did not read a card
                grace_count += 1

            logging.debug("Setting display to flash red")
            self.box.flash_display(RED, 100, 1, RED)
        logging.debug("wait_for_unauthorized_card_removal() ends")


    def wait_for_authorized_card_removal(self):
        '''
        Wait for card to be removed
        '''
        self.card_present = True
        self.proxy_uid = -1
        # We have to have a grace_counter because consecutive card reads currently fail
        grace_count = 0
        #loop endlessly waiting for shutdown or card to be removed
        logging.info("Waiting for card removal or timeout")
        while self.running and self.card_present:
            os.system("echo wait_auth_remove_timeout > /tmp/boxactivity")
            # check for timeout
            if self.exceeded_time:
                logging.debug("Time exceeded, wait for timeout grace")
                self.wait_for_timeout_grace_period_to_expire()
                logging.debug("Timeout grace period expired")
                if self.card_present:
                    # User pressed the button return to running
                    logging.debug("Button pressed, restart timeout")
                    self.exceeded_time = False
                    if self.card_present:
                            grace_count = 0
                            if -1 < self.proxy_uid:
                                logging.debug("Setting display to orange")
                                self.box.set_display_color(ORANGE)
                            else:
                                logging.debug("Setting display to green")
                                self.box.set_display_color(GREEN)
                    logging.debug("Creating and starting timeout timer")
                    self.activation_timeout = threading.Timer(self.timeout_period, self.timeout)
                    self.activation_timeout.start()
                else:
                    logging.debug("Card removed")
                    break

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
                            logging.debug("Setting display to orange")
                            self.box.set_display_color(ORANGE)
                        else:
                            logging.debug("Setting display to green")
                            self.box.set_display_color(GREEN)

            sleep(0.1)

        logging.debug("wait_for_authorized_card_removal() ends")


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
        logging.info("User card removed")
        self.card_present = False
        self.proxy_uid = -1
        logging.debug("Setting display to yellow")
        self.box.set_display_color(YELLOW)
        grace_count = 0
        self.box.has_button_been_pressed() # clear pending events
        logging.debug("Waiting for card to return")
        while self.running and grace_count < 16:
            os.system("echo wait_auth_card_return > /tmp/boxactivity")
            # Check for button press
            if self.box.has_button_been_pressed():
                logging.debug("Button pressed")
                break

            # Scan for card
            uid = self.box.read_RFID_card()
            if -1 < uid:
                # we read a card
                if uid == self.authorized_uid:
                    # card returned
                    self.card_present = True
                    logging.debug("Authorized card returned")
                    break
                elif not self.training_mode: # trainers may not use proxy cards
                    # check if proxy card
                    logging.debug("Checking if this is a proxy card")
                    if Database.PROXY_CARD == self.db.get_card_type(uid):
                        self.card_present = True
                        self.proxy_uid = uid
                        logging.debug("Trainer using proxy card")
                        break
                    logging.debug("This is not a proxy card")

            grace_count += 1
            self.box.set_buzzer(True)
            logging.debug("Set display to flash yellow")
            self.box.flash_display(YELLOW, 100, 1, YELLOW)
            self.box.set_buzzer(False)

        if self.running and not self.card_present:
            logging.info("Grace period following card removal expired; shutting down equipment")
        logging.debug("wait_for_user_card_return() ends")


    def wait_for_timeout_grace_period_to_expire(self):
        """
        Four posibilities:
        1) user presses button with card in to renew session
        2) user removes card and presses button to end session
        3) user removes card but does not press button to end session
        4) user forgot their card
        """
        logging.info("Equipment usage timeout")
        grace_count = 0
        self.box.has_button_been_pressed() # clear pending events
        logging.debug("Setting display to orange")
        self.box.set_display_color(ORANGE)
        logging.debug("Starting grace period")
        while self.running and grace_count < 600:
            os.system("echo grace_timeout > /tmp/boxactivity")
            #check for button press
            if self.box.has_button_been_pressed():
                logging.info("Button was pressed, extending time out period")
                uid = self.box.read_RFID_card()
                uid2 = self.box.read_RFID_card() #try twice since reader fails consecutive reads
                if -1 < uid or -1 < uid2:
                    # Card is still present session renewed
                    logging.debug("Card still present, renew session")
                    return
                else:
                    # Card removed end session
                    logging.debug("Card removed, end session")
                    self.card_present = False
                    return
            else:
                grace_count += 1
            
            if 1 > (grace_count % 2):
                logging.debug("Starting to flash display orange")
                self.box.flash_display(ORANGE, 100, 1, ORANGE)

            if 1 > (grace_count % 20):
                self.box.set_buzzer(True)
            else:
                self.box.set_buzzer(False)

            sleep(0.1)

        logging.debug("Grace period expired")
        # grace period expired 
        # stop the buzzer
        self.box.set_buzzer(False)

        # shutdown now, do not wait for email or card removal
        self.box.set_equipment_power_on(False)

        # was forgotten card?
        logging.debug("Checking for forgotten card")
        uid = self.box.read_RFID_card()
        uid2 = self.box.read_RFID_card() #try twice since reader fails consecutive reads
        if -1 < uid or -1 < uid2:
            # Card is still present
            logging.info("User card left in portal box. Sending user email.")
            logging.debug("Setting display to wipe blue")
            self.box.set_display_color_wipe(BLUE, 50)
            logging.debug("Getting user email ID from DB")
            user = self.db.get_user(self.authorized_uid)
            try:
                logging.debug("Mailing user")
                self.emailer.send(user[1], "Access Card left in PortalBox", "{} it appears you left your access card in a badge box for the {} in the {}".format(user[0], self.equipment_type, self.location))
            except Exception as e:
                logging.error("{}".format(e))

            logging.debug("Setting display to red")
            self.box.set_display_color(RED)
            while self.running and self.card_present:
                os.system("echo user_left_card > /tmp/boxactivity")
            # wait for card to be removed... we need to make sure we don't have consecutive read failure
                uid = self.box.read_RFID_card()
                uid2 = self.box.read_RFID_card() #try twice since reader fails consecutive reads
                if 0 > uid and 0 > uid2:
                    self.card_present = False
            logging.debug("Stopped running or card removed")
        else:
            # Card removed end session
            logging.debug("Card removed, session ends")
            self.card_present = False

        logging.debug("wait_for_timeout_grace_period_to_expire() ends")


    def exit(self):
        ''' Stop looping in all run states '''
        logging.info("Service Exiting")
        os.system("echo service_exit > /tmp/boxactivity")
        os.system("echo False > /tmp/running")
        if self.running:
            if self.equipment_id:
                logging.debug("Logging exit-while-running to DB")
                self.db.log_shutdown_status(self.equipment_id, False)
            self.running = False
        else:
            # never made it to the run state
            logging.debug("Not running, just exit")
            sys.exit()


    def handle_interupt(self, signum, frame):
        ''' Stop the service from a signal'''
        logging.debug("Interrupted")
        os.system("echo service_interrupt > /tmp/boxactivity")
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
    logging.debug("Creating PortalBoxApplication")
    service = PortalBoxApplication(settings)

    # Add signal handler so systemd can shutdown service
    signal.signal(signal.SIGINT, service.handle_interupt)
    signal.signal(signal.SIGTERM, service.handle_interupt)
    
    # Run service
    logging.debug("Running PortalBoxApplication")
    service.run()
    logging.debug("PortalBoxApplication ends")
    self.box.cleanup()

    # Cleanup and exit
    os.system("echo False > /tmp/running")
    logging.debug("Shutting down logger")
    logging.shutdown()
