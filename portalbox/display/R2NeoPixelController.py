from __future__ import division

# Import from standard library
import logging
from time import sleep

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

        logging.debug("Creating serial port connection to Arduino")
        self._controller = serial.Serial(port=self.port, timeout=2)
        logging.debug("Finished creating serial port connection")


    def _transmit(self, command):
        self._controller.write(bytes(command, "ascii"))


    def _receive(self):
        '''
        Read from serial port until a '0' or '1' are received from the Arduino
        and return True on success and False on failure
        '''
        guard = 0

        while 200 > guard:
            guard += 1
            response = self._controller.read(1)
            if 0 < len(response):
                if 48 == response[0]:
                    # 48 := ASCII '0'
                    return True
                elif 49 == response[0]:
                    # 49 := ASCII '1'
                    return False
                #else: read a whitespace character
            else:
                logging.error("NeoPixel controller rcvd 0 length response")
                raise Exception('Communications failed')
            sleep(0.05)

        logging.error("NeoPixel controller receive timeout")
        raise Exception('Communications failed')


    def sleep_display(self):
        '''
        Start a display sleeping animation
        '''
        AbstractController.sleep_display(self)
        self.set_display_color(self.sleep_color)  # Bug in pulse cmd?
        command = "pulse {} {} {}\n".format(self.sleep_color[0], self.sleep_color[1], self.sleep_color[2])
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
        command = "color {} {} {}\n".format(color[0], color[1], color[2])
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

        command = "wipe {} {} {} {}\n".format(color[0], color[1], color[2], duration)
        self._transmit(command)
        return self._receive()


    def flash_display(self, flash_color, duration, flashes=5, end_color = BLACK):
        """Flash color across all display pixels multiple times."""
        if duration > int(self._controller.timeout * 1000):
            self._controller.timeout = duration / 1000

        command = "blink {} {} {} {}\n".format(flash_color[0], flash_color[1], flash_color[2], duration)
        self._transmit(command)
        success = self._receive()
        if success:
            command = "color {} {} {}\n".format(end_color[0], end_color[1], end_color[2])
            self._transmit(command)
            return self._receive()
