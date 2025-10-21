import os
import argparse
from dependency_injector import containers, providers
from core.domain.mode_state_machine import DomainModeStateMachine
from core.domain.alarm_editor import AlarmEditor
from core.infrastructure.brightness_sensor import BrightnessSensor
from core.infrastructure.i2c_devices import I2CManager, MCPManager
from core.infrastructure.mcp23017.buttons import ButtonsManager
from core.infrastructure.mcp23017.rotary_encoder import RotaryEncoderManager
from core.interface.display.display import Display
from core.application.api import Api
from core.infrastructure.audio import Speaker, PlayerFactory
from core.application.controls import Controls
from core.infrastructure.persistence import Persistence
from resources.resources import config_file
from core.domain.model import (
    AlarmClockContext,
    Config,
    DisplayContent,
    PlaybackContent,
)
from utils.sound_device import TACSoundDevice
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

    alarm_clock_context = providers.Singleton(AlarmClockContext, config=config)
    alarm_editor = providers.Singleton(AlarmEditor, context=alarm_clock_context)
    domain_mode_state_machine = providers.Singleton(
        DomainModeStateMachine, alarm_editor=alarm_editor
    )

    sound_device = providers.Singleton(TACSoundDevice)
    playback_content = providers.Singleton(
        PlaybackContent,
        alarm_clock_context=alarm_clock_context,
        sound_device=sound_device,
    )
    display_content = providers.Singleton(
        DisplayContent,
        alarm_clock_context=alarm_clock_context,
        playback_content=playback_content,
    )

    persistence = providers.Singleton(Persistence, config_file=config_file)

    player_factory = providers.Singleton(PlayerFactory, config=config)

    speaker = providers.Singleton(
        Speaker,
        playback_content=playback_content,
        config=config,
        player_factory=player_factory,
    )

    i2c_manager = providers.Singleton(I2CManager)
    brightness_sensor = providers.Singleton(BrightnessSensor, i2c_manager=i2c_manager)
    mcp_manager = providers.Singleton(MCPManager, i2c_manager=i2c_manager)
    button_manager = providers.Singleton(ButtonsManager, mcp_manager=mcp_manager)
    rotary_encoder_manager = providers.Singleton(
        RotaryEncoderManager, mcp_manager=mcp_manager
    )

    controls = providers.Singleton(
        Controls,
        alarm_clock_context=alarm_clock_context,
        display_content=display_content,
        playback_content=playback_content,
        brightness_sensor=brightness_sensor,
    )

    serial_interface = providers.Singleton(spi, device=0, port=0)
    device = providers.Singleton(ssd1322, serial_interface=serial_interface)

    display = providers.Singleton(
        Display,
        device=device,
        display_content=display_content,
        playback_content=playback_content,
        alarm_clock_context=alarm_clock_context,
    )

    api = providers.Singleton(
        Api,
        controls=controls,
        display=display,
        encrypted=not argument_args().software,
    )
