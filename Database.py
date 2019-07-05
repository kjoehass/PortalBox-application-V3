#!python3

# from standard library
import logging

# third party libraries
import mysql.connector

class Database:
    '''
    A high level interface to the backend database
    '''
    # Access card types
    INVALID_CARD = -1
    SHUTDOWN_CARD = 1
    PROXY_CARD = 2
    TRAINING_CARD = 3
    USER_CARD = 4

    def __init__(self, settings):
        '''
        Create a connection to the database specified

        @param (dict)settings - a dictionary describing the database to connect to
        '''
        self._settings = settings
        self._connection = mysql.connector.connect(**settings)


    def close(self):
        '''
        Closes the encapsulated database connection
        '''
        self._connection.close()


    def reconnect(self):
        '''
        Reestablish a connection to the database. Useful if the connection
        timed out
        '''
        # allow exceptions to bubble out
        self._connection = mysql.connector.connect(**self._settings)


    def is_registered(self, mac_address):
        '''
        Determine if the portal box identified by the MAC address has been
        registered with the database
        '''
        registered = False

        try:
            if not self._connection.is_connected():
                self.reconnect()

            # Send query
            query = ("SELECT count(id) FROM equipment WHERE mac_address = %s")
            cursor = self._connection.cursor()
            cursor.execute(query, (mac_address,))

            # Interpret result
            (registered,) = cursor.fetchone()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))

        return registered


    def register(self, mac_address):
        '''
        Register the portal box identified by the MAC address with the database
        as an out of service device
        '''
        success = False

        try:
            if not self._connection.is_connected():
                self.reconnect()

            # Send query
            query = ("INSERT INTO equipment (name, type_id, mac_address, location_id) VALUES ('New Portal Box', 1, %s, 1)")
            cursor = self._connection.cursor()
            cursor.execute(query, (mac_address,))

            if 1 == cursor.rowcount:
                success = True

            self._connection.commit()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))

        return success


    def get_equipment_profile(self, mac_address):
        '''
        Discover the equipment profile assigned to the Portal Box in the database

        @return a tuple consisting of: (int)equipment id,
        (int)equipment type id, (str)equipment type, (int)location id,
        (str)location, (int)time limit in minutes
        '''
        profile = (-1, -1, None, -1, None, -1)

        try:
            if not self._connection.is_connected():
                self.reconnect()

            # Query MySQL for RID by sending MAC Address
            query = ("SELECT e.id, e.type_id, t.name, e.location_id, l.name, e.timeout "
                "FROM equipment AS e "
                "INNER JOIN equipment_types AS t ON e.type_id = t.id "
                "INNER JOIN locations AS l ON e.location_id =  l.id "
                "WHERE e.mac_address = %s")
            cursor = self._connection.cursor(buffered = True) # we want rowcount to be available
            cursor.execute(query, (mac_address,))

            if 0 < cursor.rowcount:
                # Interpret result
                profile = cursor.fetchone()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))

        return profile


    def log_access_attempt(self, card_id, equipment_id, successful):
        '''
        Logs start time for user using a resource.
        
        @param card_id: The ID read from the card presented by the user
        @param equipment_id: The ID assigned to the portal box
        @param successful: If login was successful (user is authorized)
        '''
        try:
            if not self._connection.is_connected():
                self.reconnect()

            query = ("CALL log_access_attempt(%s, %s, %s)")
            cursor = self._connection.cursor()

            cursor.execute(query, (successful, card_id, equipment_id))
            # No check for success?
            self._connection.commit()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))


    def log_access_completion(self, card_id, equipment_id):
        '''
        Logs end time for user using a resource.
        
        @param card_id: The ID read from the card presented by the user
        @param equipment_id: The ID assigned to the portal box
        @param successful: If login was successful (user is authorized)
        '''
        try:
            if not self._connection.is_connected():
                self.reconnect()
        
            query = ("CALL log_access_completion(%s, %s)")
            cursor = self._connection.cursor()

            cursor.execute(query, (card_id, equipment_id))
            self._connection.commit()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))


    def is_user_authorized_for_equipment_type(self, user_id, equipment_type_id):
        '''
        Check if card holder identified by user_id is authorized for the
        equipment type identified by equipment_type_id
        '''
        is_authorized = False

        try:
            if not self._connection.is_connected():
                self.reconnect()

            query = ("SELECT requires_training, charge_policy_id > 2 FROM equipment_types WHERE id = %s")
            cursor = self._connection.cursor()
            cursor.execute(query, (equipment_type_id,))
            
            (requires_training,requires_payment) = cursor.fetchone()
            if requires_training and requires_payment:
                query = ("SELECT count(p.id) FROM payments AS p "
                    "INNER JOIN users_x_cards AS u ON u.user_id = p.user_id "
                    "WHERE u.card_id = %s")
                cursor.execute(query, (user_id,))
                (count,) = cursor.fetchone()
                if 0 < count:
                    query = ("SELECT count(u.id) FROM users_x_cards AS u "
                    "INNER JOIN authorizations AS a ON a.user_id= u.user_id "
                    "WHERE u.card_id = %s AND a.equipment_type_id = %s")
                    cursor.execute(query, (user_id, equipment_type_id))
                    (count,) = cursor.fetchone()
                    if 0 < count:
                        is_authorized = True
            elif requires_training and not requires_payment:
                query = ("SELECT count(u.id) FROM users_x_cards AS u "
                "INNER JOIN authorizations AS a ON a.user_id= u.user_id "
                "WHERE u.card_id = %s AND a.equipment_type_id = %s")
                cursor.execute(query, (user_id, equipment_type_id))
                (count,) = cursor.fetchone()
                if 0 < count:
                    is_authorized = True
            elif not requires_training and requires_payment:
                query = ("SELECT count(p.id) FROM payments AS p "
                    "INNER JOIN users_x_cards AS u ON u.user_id = p.user_id "
                    "WHERE u.card_id = %s")
                cursor.execute(query, (user_id,))
                (count,) = cursor.fetchone()
                if 0 < count:
                    is_authorized = True
            else:
                # we don't require payment or training, user is implicitly authorized
                is_authorized = True           

            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))

        return is_authorized


    def get_card_type(self, id):
        '''
        Get the type of the card identified by id

        @return an integer: -1 for card not found, 1 for shutdown card, 2 for
            proxy card, 3 for training card, and 4 for user card 
        '''
        type_id = -1

        try:
            if not self._connection.is_connected():
                self.reconnect()

            query = ("SELECT type_id FROM cards WHERE id = %s")

            cursor = self._connection.cursor(buffered = True) # we want rowcount to be available
            cursor.execute(query, (id,))

            if 0 < cursor.rowcount:
                (type_id,) = cursor.fetchone()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))

        return type_id


    def is_training_card_for_equipment_type(self, id, type_id):
        '''
        Determine if the training card identified by id is valid as a
        training card for equipment of type specified by type_id
        '''
        valid = False

        try:
            if not self._connection.is_connected():
                self.reconnect()

            # Send query
            query = ("SELECT count(id) FROM equipment_type_x_cards "
                "WHERE card_id = %s AND equipment_type_id = %s")
            cursor = self._connection.cursor()
            cursor.execute(query, (id,type_id))

            # Interpret result
            (valid,) = cursor.fetchone()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))

        return valid

 
    def get_user(self, id):
        '''
        Get details for the user identified by (card) id

        @return, a tuple of name and email
        '''
        user = (None, None)
        try:
            if not self._connection.is_connected():
                self.reconnect()

            query = ("SELECT u.name, u.email FROM users_x_cards AS c "
                "JOIN users AS u ON u.id = c.user_id WHERE c.card_id = %s")

            cursor = self._connection.cursor()
            cursor.execute(query, (id,))

            user = cursor.fetchone()
            cursor.close()
        except mysql.connector.Error as err:
            logging.error("{}".format(err))

        return user


# Rest of this file is the test suite. Use `python3 Database.py` to run
# check prevents running of test suite if loading (import) as a module
if __name__ == "__main__":
    # standard library
    import configparser
    from time import sleep
    from uuid import getnode as get_mac_address

    # Init logging
    logging.basicConfig(format='%(message)s', level=logging.DEBUG)

    # Read our Configuration
    settings = configparser.ConfigParser()
    settings.read('config.ini')

    # connect to backend database
    db = Database(settings['db'])

    # test is_registered
    logging.info("Database.is_registered test")
    mac_address = format(get_mac_address(), 'x') # this machine

    registered = db.is_registered(mac_address)
    if registered:
        logging.info("\tThis machine, MAC: %s is registered with the database", mac_address)
        logging.info("\tTo test register rerun this test on a PC not registered with the database")
    else:
        logging.info("\tThis machine, MAC: %s is not registered with the database", mac_address)
        # we can test register because we have a MAC address that is not registered
        # test Database register
        logging.info("Database.register test")
        success = db.register(mac_address)

        if success:
            logging.info("\tThis machine, MAC: %s was registered with the database", mac_address)
        else:
            logging.info("\tThis machine, MAC: %s could not be registered with the database", mac_address)

    # test get_equipment_profile
    logging.info("Database.get_resource_profile test")
    (equipment_id, type_id, type, location_id, location, time_limit) = db.get_equipment_profile(mac_address)
    logging.info("\t Portal Box %s has role type:%s(%s) location:%s(%s) time limit:%s", equipment_id, type, type_id, location, location_id, time_limit)

    # test get_card
    logging.info("Database.get_card_type")
    #-1 for card not found, 1 for shutdown card, 2 for proxy card, 3 for training card, and 4 for user card
    # no card with id 0 should exist in the database
    logging.info("\tTesting for card that should not exist")
    type = db.get_card_type(0)
    if -1 == type:
        logging.info("\t[Success] card was not found in the database")
    else:
        logging.info("\t[Fail] nonexistant card found in db.get_card_type returned: %s", type)

    # card 550014053 is a shutdown card in the test database
    logging.info("\tTesting for shutdown card")
    type = db.get_card_type(550014053)
    if 1 == type:
        logging.info("\t[Success] shutdown card was found in the database")
    else:
        logging.info("\t[Fail] shutdown card was not found in db.get_card_type returned: %s", type)
    
    # card 2232841801 is a proxy card in the test database
    logging.info("\tTesting for proxy card")
    type = db.get_card_type(2232841801)
    if 2 == type:
        logging.info("\t[Success] proxy card was found in the database")
    else:
        logging.info("\t[Fail] proxy card was not found in db.get_card_type returned: %s", type)

    # card 1709165641 is a training card in the test database
    logging.info("\tTesting for training card")
    type = db.get_card_type(1709165641)
    if 3 == type:
        logging.info("\t[Success] training card was found in the database")
    else:
        logging.info("\t[Fail] training card was not found in db. get_card_type returned: %s", type)
    
    # card 1626651146 is a user card in the test database
    logging.info("\tTesting for user card")
    type = db.get_card_type(1626651146)
    if 4 == type:
        logging.info("\t[Success] user card was found in the database")
    else:
        logging.info("\t[Fail] user card was not found in db. get_card_type returned: %s", type)

    logging.info("Database.is_training_card_for_equipment_type")
    valid = db.is_training_card_for_equipment_type(1709165641, 2)
    if valid:
        logging.info("\t[Fail] 1709165641 is a training card for equipment type: 2 but it should not be")
    else:
        logging.info("\t[Success] 1709165641 is not a training card for equipment type: 2")

    valid = db.is_training_card_for_equipment_type(1709165641, 9)
    if valid:
        logging.info("\t[Success] 1709165641 is a training card for equipment type: 9")
    else:
        logging.info("\t[Fail] 1709165641 is not a training card for equipment type: 9 but it should be")

    logging.info("Database.is_user_authorized_for_equipment_type")
    valid = db.is_user_authorized_for_equipment_type(1626651146, 2)
    # not trained
    if valid:
        logging.info("\t[Fail] The user identified by card: 1626651146 is authorized for equipment type: 2 but should not be")
    else:
        logging.info("\t[Success] The user identified by card: 1626651146 is not authorized for equipment type: 2")

    # is trained no payment required
    valid = db.is_user_authorized_for_equipment_type(1626651146, 7)
    if valid:
        logging.info("\t[Success] The user identified by card: 1626651146 is authorized for equipment type: 7")
    else:
        logging.info("\t[Fail] The user identified by card: 1626651146 is not authorized for equipment type: 7 but should be")
    
    # is trained but payment lapsed
    valid = db.is_user_authorized_for_equipment_type(362577737, 4)
    if valid:
        logging.info("\t[Fail] The user identified by card: 362577737 is authorized for equipment type: 4 but should not be")
    else:
        logging.info("\t[Success] The user identified by card: 362577737 is not authorized for equipment type: 4")

    # trained and paid
    valid = db.is_user_authorized_for_equipment_type(4181928747, 4)
    if valid:
        logging.info("\t[Success] The user identified by card: 4181928747 is authorized for equipment type: 4")
    else:
        logging.info("\t[Fail] The user identified by card: 4181928747 is not authorized for equipment type: 4 but should be")
    
    # paid, training not required?

    # test get_user
    logging.info("Database.get_user test")
    user = db.get_user(1626651146)
    logging.info("\tUser: %s <%s>", user[0], user[1])

    # test access attempt
    logging.info("Testing access attempt")
    db.log_access_attempt(1626651146, 3, True)
    sleep(10)
    db.log_access_completion(1626651146, 3)

    # test reconnection
    logging.info("Database.reconnect test")
    db.close()
    try:
        db.reconnect()
        logging.info("\tReconnection successful")
    except mysql.connector.Error as err:
        logging.error("\tReconnection failed {}".format(err))

    db.close()