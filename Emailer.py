#!python3

# from standard library
from email.mime.text import MIMEText
import logging
import smtplib
import ssl

class Emailer:
    '''
    Bind settings in a class for reuse 
    '''

    def __init__(self, settings):
        self.settings = settings


    def send(self, to, subject, body):
        """
        Send an email using the configured settings.

        params:
            to - The email address to which to send the email.
            subject - The subject for the email
            body - The message body for the email
        """
        message = MIMEText(body)
        message['From'] = self.settings['from_address']
        message['To'] = to
        if 'cc_address' in self.settings:
            message['Cc'] = self.settings['cc_address']
        if 'bcc_address' in self.settings:
            message['Bbc'] = self.settings['bcc_address']
        message['Subject'] = subject
        if 'reply_to' in self.settings:
            message.add_header('reply-to', self.settings['reply_to'])

        logging.debug("Creating SMTP server")
        server = smtplib.SMTP(self.settings['smtp_server'], int(self.settings['smtp_port']))
        context = ssl.create_default_context()
        if 'my_smtp_server_uses_a_weak_certificate' in self.settings:
            if self.settings['my_smtp_server_uses_a_weak_certificate'].lower() in ("yes", "true", "1"):
                context.set_ciphers('HIGH:!DH:!aNULL')
        server.starttls(context=context)
        server.login(self.settings['auth_user'], self.settings['auth_password'])
        server.send_message(message)
        server.quit()
        logging.info("Emailed: %s about: %s", to, subject)


# Rest of this file is the test suite. Use `python3 Email.py` to run
# check prevents running of test suite if loading (import) as a module
if __name__ == "__main__":
    # standard library
    import configparser

    # Init logging
    logging.basicConfig(format='%(message)s', level=logging.DEBUG)

    # Read our Configuration
    settings = configparser.ConfigParser()
    settings.read('config.ini')

    # connect to backend database
    emailer = Emailer(settings['email'])

    emailer.send(settings['email']['cc_address'], "Hello World", "Greetings Developer. You have tested the Emailer module.")
