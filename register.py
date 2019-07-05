#!python3

# from the standard library
import configparser
import os
import sys
from uuid import getnode as get_mac_address

# our code
from Database import Database

config_file_path = "config.ini"

# Look at Command Line for Overrides
if 1 < len(sys.argv):
    if os.path.isfile(sys.argv[1]):
        # override default config file
        config_file_path = sys.argv[1]
    # else print help message?

# Read our Configuration
settings = configparser.ConfigParser()
settings.read(config_file_path)

mac_address = format(get_mac_address(), 'x')

db = Database(settings['db'])
is_registered = db.is_registered(mac_address)
if not is_registered:
    db.register(mac_address)