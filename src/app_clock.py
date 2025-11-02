import logging
import signal
from luma.core.device import dummy

import tornado.ioloop

from core.application.di_container import DIContainer
from dependency_injector import providers

from core.domain.model import (
    Mode,
)
from core.application.controls import Controls
from resources.resources import init_logging
from utils import os as app_os

logger = logging.getLogger("tac.app_clock")


class ClockApp:

    def __init__(self) -> None:
        self.container = DIContainer()

    def is_on_hardware(self):
        return not self.container.argument_args().software

    def shutdown_function(self):
        logger.info("graceful shutdown")
        app_os.restart_spotify_daemon()
        tornado.ioloop.IOLoop.current().stop()

    def go(self):

        signal.signal(signal.SIGTERM, self.shutdown_function)

        self.container.config()
        context = self.container.alarm_clock_context()
        context.state_machine = self.container.state_machine()

        logger.info("config available")

        if not self.is_on_hardware():
            from core.infrastructure.computer_infrastructure import (
                ComputerInfrastructure,
            )

            ci = ComputerInfrastructure()
            self.container.brightness_sensor.override(providers.Object(ci))
            self.container.device.override(
                providers.Singleton(dummy, height=64, width=256, mode="RGB")
            )

        controls: Controls = self.container.controls()

        controls.configure()

        api = self.container.api()
        api.start()

        self.container.playback_content().playback_mode = Mode.Idle
        controls.consider_failed_alarm()
        tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    init_logging()
    logger.info("start")
    ClockApp().go()
