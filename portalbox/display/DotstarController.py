# Import from standard library
import logging
from time import sleep
import multiprocessing

# Import from our module
from .AbstractController import AbstractController, BLACK
from .DotstarDriver import strip_driver

# Define the SPI bus and device that will be used
SPI_BUS = 1
SPI_DEV = 0

# Define how many LEDs are in the strip
LED_COUNT = 15


class DotstarController(AbstractController):
    """
    Control Dotstars

    The order of the colors in the serial transmission is red, blue, green
    """

    def __init__(self, settings={}):
        """Create a Dotstar driver process and start it.

        """
        AbstractController.__init__(self)

        if "sleep_color" in settings:
            self.sleep_color = settings["sleep_color"]
        else:
            self.sleep_color = b"\x00\x00\xFF"

        self.command_queue = multiprocessing.JoinableQueue()
        driver = multiprocessing.Process(
            target=strip_driver,
            name="dotstar_strip",
            args=(self.command_queue, LED_COUNT, SPI_BUS, SPI_DEV),
        )
        driver.daemon = True
        driver.start()

    def _transmit(self, command):
        """Put a command string in the queue."""
        logging.debug("Sending: '%s' to dotstar controller", command.strip())
        self.command_queue.put(command)

    def _receive(self):
        """
        Wait until the command queue is empty, then return True.

        This function blocks until the commands have been processed. There is
        no inherent or enforced limit to the length of time needed to process
        a command, so we can not use a timeout here. There is no recovery
        mechanism for a command that fails, so the driver should just throw an
        exception.
        """
        #TODO are we OK with this behavior?
        self.command_queue.join()
        return True

    #        try:
    #            response = self.command_queue.get(True, 10)
    #            if response == 0:
    #                return True
    #            else:
    #                logging.debug("Command processing failed")
    #                return False
    #
    #        except:

    def sleep_display(self):
        """Start a display sleeping animation (pulsing sleep color)."""
        AbstractController.sleep_display(self)
        command = "pulse {} {} {}\n".format(self.sleep_color[0],
                                            self.sleep_color[1],
                                            self.sleep_color[2])
        self._transmit(command)
        return self._receive()

    def wake_display(self):
        """End a box sleeping animation."""
        #TODO Should the display change now??
        AbstractController.wake_display(self)

    def set_display_color(self, color=BLACK):
        """Set the entire strip to specified color (defaults to black)."""
        AbstractController.set_display_color(self, color)

        command = "color {} {} {}\n".format(color[0],
                                            color[1],
                                            color[2])
        self._transmit(command)
        return self._receive()

    def set_display_color_wipe(self, color=BLACK, duration=1000):
        """Set the entire strip to specified color using a "wipe" effect.

        color - a tuple of red, green, blue byte values
        duration - how long, in milliseconds, the effect is to take
        """
        AbstractController.set_display_color_wipe(self, color, duration)
#        if duration > int(self._controller.timeout * 1000):
#            self._controller.timeout = duration / 1000

        command = "wipe {} {} {} {}\n".format(color[0],
                                              color[1],
                                              color[2],
                                              duration)
        self._transmit(command)
        return self._receive()

    def flash_display(self, flash_color, duration, flashes=5, end_color=BLACK):
        """Flash color across all display pixels multiple times."""
        #        if duration > int(self._controller.timeout * 1000):
        #            self._controller.timeout = duration / 1000

        command = "blink {} {} {} {} {}\n".format(flash_color[0],
                                                  flash_color[1],
                                                  flash_color[2],
                                                  duration,
                                                  flashes)
        self._transmit(command)
        success = self._receive()

        if success:
             # END_COLOR is disabled....OK with that?
#            command = "color {} {} {}\n".format(end_color[0],
#                                                end_color[1],
#                                                end_color[2])
            self._transmit(command)
            return self._receive()
