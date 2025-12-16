import logging
from logging import config
import signal
import sys
from luma.core.device import dummy

import tornado.ioloop

from core.application.di_container import DIContainer
from dependency_injector import providers

from core.domain.events import (
    ConfigChangedEvent,
    PlaybackChangedEvent,
    StartupFinishedEvent,
)
from core.domain.model import (
    Mode,
)
from core.application.controls import AlarmAudioControls
from resources.resources import init_logging

logger = logging.getLogger("tac.app_clock")


class ClockApp:

    def __init__(self) -> None:
        self.container = DIContainer()

    def is_on_hardware(self):
        return not self.container.argument_args().software

    def shutdown_function(self, *args):
        logger.info("graceful shutdown")
        self.container.os_interaction().restart_spotify_daemon()
        tornado.ioloop.IOLoop.current().stop()

    def go(self):

        signal.signal(signal.SIGTERM, self.shutdown_function)

        config = self.container.config()
        context = self.container.alarm_clock_context()
        self.container.persistence()

        logger.info("config available")
        ci: any = None

        if self.is_on_hardware():
            self.container.button_manager()
            self.container.rotary_encoder_manager()
        else:
            from core.infrastructure.computer_infrastructure import (
                ComputerInfrastructure,
            )

            ci = ComputerInfrastructure()
            self.container.brightness_sensor.override(providers.Object(ci))
            self.container.device.override(
                providers.Singleton(dummy, height=64, width=256, mode="RGB")
            )

        controls: AlarmAudioControls = self.container.controls()
        self.container.system_service()
        if ci is not None:
            ci.configure(controls)

        api = self.container.api()
        api.start()

        self.container.speaker()

        # Initialize domain coordinator and interface layer
        context.mode_coordinator = self.container.mode_coordinator()
        self.container.hardware_input_handler()

        self.container.event_bus().emit(ConfigChangedEvent(config=config))
        self.container.event_bus().emit(PlaybackChangedEvent(Mode.Idle))
        self.container.event_bus().emit(StartupFinishedEvent())

        display = self.container.display()
        tornado.ioloop.PeriodicCallback(display.process_events, 50).start()

        tornado.ioloop.IOLoop.current().start()

        controls.scheduler_service.shutdown()
        if self.is_on_hardware():
            self.container.mcp_manager().close()
        elif ci is not None:
            ci.stop()

        logger.info("shutdown complete")
        sys.exit(0)


if __name__ == "__main__":
    init_logging()
    logger.info("start")
    ClockApp().go()
