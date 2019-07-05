#!python3

# from standard library
from email.mime.text import MIMEText
import logging
import smtplib

class Emailer:
    '''
    Bind settings in a class for reuse 
    '''
    def __init__(self, settings):
        self.settings = settings


    def send(self, to, subject, body):
        msg = MIMEText(body)
        msg['From'] = self.settings['from_address']
        msg['To'] = to
        msg['Subject'] = subject
        if 'reply_to' in self.settings:
            msg.add_header('reply-to', self.settings['reply_to'])

        message = msg.as_string()

        server = smtplib.SMTP(self.settings['smtp_server'], int(self.settings['smtp_port']))
        server.starttls()
        server.login(self.settings['auth_user'], self.settings['auth_password'])
        server.sendmail(self.settings['from_address'], self.settings['to_address'], message)
        server.quit()
        logging.info("Emailed: %s about: %s", self.settings['to_address'], subject)


# Rest of this file is the test suite. Use `python3 Database.py` to run
# check prevents running of test suite if loading (import) as a module
if __name__ == "__main__":
    # standard library
    import configparser

    # Init logging
    logging.basicConfig(format='%(message)s', level=logging.DEBUG)

    # Read our Configuration
    settings = configparser.ConfigParser()
    settings.read('../config.ini')

    # connect to backend database
    emailer = Emailer(settings['email'])

    emailer.send(settings['email']['to_address'], "Hello World", "Greetings Developer. You have tested the Emailer module.")
