BLACK = b'\x00\x00\x00'

_BAD_COLOR_VALUE_ERROR_MSG = ("Colors are expected to be a bytes object of "
                                "length three (3) specifing the r,g and b "
                                "components of the color in that order")
_BAD_DURATION_VALUE_ERROR_MSG = ("Duration is expected to be an unsigned "
                                "integer")
_BAD_FLASHES_VALUE_ERROR_MSG = "Flashes is expected to be an unsigned integer"

class AbstractController:
    '''
    Define the interface for portal box display controllers

    PortalBox.py expects controllers to implement the interface exposed by
    AbstractController. Therefore concrete Controller classes, ones that
    interface with real hardware should subclass AbstractController
    '''

    def __init__(self, settings = {}):
        '''
        Use the optional settings to configure the display

        Caller will pass a dict (ConfigParser.SectionProxy) initialized from
        the 'display' section of the config file. A ValueError should be raised
        if a required key is missing though sane defaults should be used if
        possible so that settings is optional.
        '''
        self.is_sleeping = False


    def sleep_display(self):
        '''
        Start a display sleeping animation
        '''
        self.is_sleeping = True


    def wake_display(self):
        '''
        End a box sleeping animation
        '''
        self.is_sleeping = False


    def set_display_color(self, color = BLACK):
        '''
        Set the entire strip to specified color.
        @param (unsigned integer) color - the color to set defaults to LED's off
        '''
        if type(color) is not bytes or 3 != len(color):
            raise ValueError(_BAD_COLOR_VALUE_ERROR_MSG)


    def set_display_color_wipe(self, color, duration):
        '''
        Set the entire strip to specified color using a "wipe" effect.
        @param (unsigned integer) color - the color to set
        @param (int) duration - how long the effect is to take
        '''
        if type(color) is not bytes or 3 != len(color):
            raise ValueError(_BAD_COLOR_VALUE_ERROR_MSG)

        if type(duration) is not int or 0 > duration:
            raise ValueError(_BAD_DURATION_VALUE_ERROR_MSG)


    def flash_display(self, flash_color, duration, flashes=5, end_color = BLACK):
        """Flash color across all display pixels multiple times."""
        if type(flash_color) is not bytes or 3 != len(flash_color):
            raise ValueError(_BAD_COLOR_VALUE_ERROR_MSG)

        if type(duration) is not int or 0 > duration:
            raise ValueError(_BAD_DURATION_VALUE_ERROR_MSG)

        if type(flashes) is not int or 0 > flashes:
            raise ValueError(_BAD_FLASHES_VALUE_ERROR_MSG)

        if type(end_color) is not bytes or 3 != len(end_color):
            raise ValueError(_BAD_COLOR_VALUE_ERROR_MSG)
