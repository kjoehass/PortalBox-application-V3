from __future__ import division

# Import from our module
from .AbstractController import AbstractController, BLACK

# import from third party
import serial


class R2NeoPixelController(AbstractController):
    '''
    Control NeoPixels on R2.06 boards

    The R2.06 boards have 15 NeoPixels with the data trace connected to pin 5
    of the socket for a Raspberry Pi 0 W. The Pi however does a terrible job of
    communicating with the NeoPixels especially when running newer versions of
    Raspbian. The solution is adding a board with an arduino pro8MHzatmega328
    on it which outputs on pin 5 and is connected for serial on the UART pins
    (/dev/serial0).
    '''

    def __init__(self, settings = {}):
        '''
        Connect to Arduino
        '''
        AbstractController.__init__(self)

        if 'sleep_color' in settings:
            self.sleep_color = settings['sleep_color']
        else:
            self.sleep_color = b'\x00\x00\xFF'

        if 'port' in settings:
            self.port = settings['port']
        else:
            self.port = '/dev/serial0'

        self._controller = serial.Serial(port=self.port, timeout=2)


    def _transmit(self, command):
        logging.debug("Sending: '%s' to display controller", command)
        self._controller.write(command)


    def _receive(self):
        '''
        Read a response from the Arduino and return True on success and False
        on failure
        '''
        response = self._controller.read(2)
        if 0 < len(response):
            if '0' == response[0]:
                return True
            elif '1' == response[0]:
                return False
            else:
                raise Exception('Communications failed')
        else:
            raise Exception('Communications failed')


    def sleep_display(self):
        '''
        Start a display sleeping animation
        '''
        AbstractController.sleep_display(self)
        command = "pulse {} {} {}\n".format(ord(self.sleep_color[0]), ord(self.sleep_color[1]), ord(self.sleep_color[2]))
        self._transmit(command)
        return self._receive()


    def wake_display(self):
        '''
        End a box sleeping animation
        '''
        AbstractController.wake_display(self)


    def set_display_color(self, color = BLACK):
        '''
        Set the entire strip to specified color.
        @param (color) color - the color to set defaults to LED's off
        '''
        command = "color {} {} {}\n".format(ord(color[0]), ord(color[1]), ord(color[2]))
        self._transmit(command)
        return self._receive()


    def set_display_color_wipe(self, color = BLACK, duration = 1000):
        '''
        Set the entire strip to specified color using a "wipe" effect.
        @param (unsigned integer) color - the color to set
        @param (int) duration - how long, in milliseconds, the effect is to take
        '''
        if duration > int(self._controller.timeout * 1000):
            self._controller.timeout = duration / 1000

        command = "wipe {} {} {} {}\n".format(ord(color[0]), ord(color[1]), ord(color[2]), duration)
        self._transmit(command)
        return self._receive()


    def flash_display(self, flash_color, duration, flashes=5, end_color = BLACK):
        """Flash color across all display pixels multiple times."""
        if duration > int(self._controller.timeout * 1000):
            self._controller.timeout = duration / 1000

        command = "blink {} {} {} {}\n".format(ord(flash_color[0]), ord(flash_color[1]), ord(flash_color[2]), duration)
        self._transmit(command)
        success = self._receive()
        if success:
            command = "color {} {} {}\n".format(ord(end_color[0]), ord(end_color[1]), ord(end_color[2]))
            self._transmit(command)
            return self._receive()
