import logging
import signal
from luma.core.device import dummy

import tornado.ioloop

from core.application.di_container import DIContainer
from dependency_injector import providers

from core.domain.model import (
    Mode,
)
from core.application.controls import Controls, SoftwareControls
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
        state = self.container.alarm_clock_state()
        state.state_machine = self.container.state_machine()

        logger.info("config available")

        playback_content = self.container.playback_content()
        state.subscribe(playback_content)
        display_content = self.container.display_content()
        state.subscribe(display_content)

        if not self.is_on_hardware():
            self.container.controls.override(
                providers.Singleton(
                    SoftwareControls,
                    state=self.container.alarm_clock_state,
                    display_content=self.container.display_content,
                    playback_content=self.container.playback_content,
                )
            )
            self.container.device.override(
                providers.Singleton(dummy, height=64, width=256, mode="RGB")
            )

        controls: Controls = self.container.controls()
        display = self.container.display()
        display_content.subscribe(display)

        persistence = self.container.persistence()
        state.subscribe(persistence)
        state.config.subscribe(persistence)

        speaker = self.container.speaker()
        playback_content.subscribe(speaker)
        state.config.subscribe(controls)
        playback_content.subscribe(controls)
        state.state_machine.subscribe(controls)
        controls.configure()

        api = self.container.api()
        api.start()

        state.mode = Mode.Idle
        controls.consider_failed_alarm()
        tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    init_logging()
    logger.info("start")
    ClockApp().go()
