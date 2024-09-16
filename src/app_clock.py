import argparse
import logging
import logging.config
import os
import signal
from luma.oled.device import ssd1322
from luma.core.device import device as luma_device
from luma.core.interface.serial import spi
from luma.core.device import dummy

import tornado.ioloop
import tornado.web
from api import Api
from audio import Speaker
from controls import Controls, SoftwareControls

from display import Display
from domain import AlarmClockState, Config, DisplayContent, Mode, PlaybackContent
from gpo import GeneralPurposeOutput
from persistence import Persistence
from resources.resources import init_logging
from utils import os as app_os

logger = logging.getLogger("tac.app_clock")


class ClockApp:
    configFile = f"{os.path.dirname(os.path.realpath(__file__))}/config.json"

    def __init__(self) -> None:
        parser = argparse.ArgumentParser("ClockApp")
        parser.add_argument("-s", "--software", action="store_true")
        self.args = parser.parse_args()

    def is_on_hardware(self):
        return not self.args.software

    def shutdown_function(self):
        logger.info("graceful shutdown")
        app_os.restart_spotify_daemon()
        tornado.ioloop.IOLoop.current().stop()

    def go(self):

        signal.signal(signal.SIGTERM, self.shutdown_function)

        self.state = AlarmClockState(Config())
        if os.path.exists(self.configFile):
            self.state.configuration = Config.deserialize(self.configFile)

        logger.info("config available")

        playback_content = PlaybackContent(self.state)
        self.state.attach(playback_content)
        display_content = DisplayContent(self.state, playback_content)
        self.state.attach(display_content)

        device: luma_device

        if self.is_on_hardware():
            self.controls = Controls(self.state, display_content, playback_content)
            # self.state.attach(GeneralPurposeOutput())
            device = ssd1322(serial_interface=spi(device=0, port=0))
            port = 80
        else:
            self.controls = SoftwareControls(
                self.state, display_content, playback_content
            )
            device = dummy(height=64, width=256, mode="RGB")
            port = 8080

        self.display = Display(
            device, display_content, playback_content, self.state.configuration
        )
        display_content.attach(self.display)
        self.persistence = Persistence(self.configFile)
        self.state.attach(self.persistence)
        self.state.configuration.attach(self.persistence)

        self.speaker = Speaker(playback_content, self.state.configuration)
        playback_content.attach(self.speaker)
        self.state.configuration.attach(self.controls)
        playback_content.attach(self.controls)
        self.controls.configure()

        self.api = Api(self.controls, self.display)
        self.api.start(port)

        self.state.mode = Mode.Idle
        self.controls.consider_failed_alarm()
        tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    init_logging()
    logger.info("start")
    ClockApp().go()
