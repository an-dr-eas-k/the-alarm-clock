import os
import argparse
from dependency_injector import containers, providers
from core.domain.mode import AlarmClockStateMachine
from core.interface.display.display import Display
from core.application.api import Api
from core.infrastructure.audio import Speaker
from core.application.controls import HardwareControls, SoftwareControls
from core.infrastructure.persistence import Persistence
from resources.resources import config_file
from core.domain.model import (
    AlarmClockState,
    Config,
    DisplayContent,
    PlaybackContent,
)
from luma.core.device import dummy
from luma.oled.device import ssd1322
from luma.core.interface.serial import spi


class DIContainer(containers.DeclarativeContainer):

    @staticmethod
    def create_argument_parser():
        parser = argparse.ArgumentParser(prog="ClockApp")
        parser.add_argument("-s", "--software", action="store_true")
        return parser

    argument_parser = providers.Singleton(create_argument_parser)

    argument_args = providers.Singleton(
        lambda parser: parser.parse_args(), parser=argument_parser
    )

    config = providers.Singleton(
        lambda: (
            Config.deserialize(config_file) if os.path.exists(config_file) else Config()
        )
    )

    alarm_clock_state = providers.Singleton(AlarmClockState, config=config)
    state_machine = providers.Singleton(AlarmClockStateMachine, state=alarm_clock_state)

    playback_content = providers.Singleton(PlaybackContent, state=alarm_clock_state)
    display_content = providers.Singleton(
        DisplayContent, state=alarm_clock_state, playback_content=playback_content
    )

    persistence = providers.Singleton(Persistence, config_file=config_file)
    speaker = providers.Singleton(
        Speaker, playback_content=playback_content, config=config
    )

    controls = providers.Singleton(
        HardwareControls,
        state=alarm_clock_state,
        display_content=display_content,
        playback_content=playback_content,
    )

    serial_interface = providers.Singleton(spi, device=0, port=0)
    device = providers.Singleton(ssd1322, serial_interface=serial_interface)

    display = providers.Singleton(
        Display,
        device=device,
        display_content=display_content,
        playback_content=playback_content,
        state=alarm_clock_state,
    )

    api = providers.Singleton(
        Api,
        controls=controls,
        display=display,
        encrypted=not argument_args().software,
    )
