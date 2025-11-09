import os
import argparse
from dependency_injector import containers, providers
from core.domain.mode_coordinator import (
    AlarmClockModeCoordinator,
    AlarmEditMode,
    AlarmViewMode,
    DefaultMode,
    PropertyEditMode,
)
from core.infrastructure.brightness_sensor import BrightnessSensor
from core.infrastructure.computer_infrastructure import ComputerInfrastructure
from core.infrastructure.i2c_devices import I2CManager, MCPManager
from core.infrastructure.mcp23017.buttons import ButtonsManager
from core.infrastructure.mcp23017.rotary_encoder import RotaryEncoderManager
from core.interface.display.display import Display
from core.application.api import Api
from core.infrastructure.audio import Speaker
from core.application.controls import Controls
from core.infrastructure.persistence import Persistence
from core.infrastructure.event_bus import EventBus
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

    event_bus = providers.Singleton(EventBus)

    config = providers.Singleton(
        lambda event_bus: (
            Config.deserialize(config_file, event_bus)
            if os.path.exists(config_file)
            else Config(event_bus=event_bus)
        ),
        event_bus=event_bus,
    )

    alarm_clock_context = providers.Singleton(AlarmClockContext, config=config)
    default_state = providers.Singleton(
        DefaultMode, previous_mode=None, alarm_clock_context=alarm_clock_context
    )
    alarm_view_state = providers.Singleton(AlarmViewMode, previous_mode=default_state)
    alarm_edit_state = providers.Singleton(
        AlarmEditMode, previous_mode=alarm_view_state
    )
    property_edit_state = providers.Singleton(
        PropertyEditMode, previous_mode=alarm_edit_state
    )
    state_machine = providers.Singleton(
        AlarmClockModeCoordinator,
        default_state=default_state,
        event_bus=event_bus,
        alarm_view_state=alarm_view_state,
        alarm_edit_state=alarm_edit_state,
        property_edit_state=property_edit_state,
    )

    computer_infrastructure = providers.Singleton(
        ComputerInfrastructure, event_bus=event_bus
    )

    sound_device = providers.Singleton(TACSoundDevice)
    playback_content = providers.Singleton(
        PlaybackContent,
        alarm_clock_context=alarm_clock_context,
        sound_device=sound_device,
        event_bus=event_bus,
    )
    display_content = providers.Singleton(
        DisplayContent,
        alarm_clock_context=alarm_clock_context,
        playback_content=playback_content,
        event_bus=event_bus,
    )

    persistence = providers.Singleton(
        Persistence, config_file=config_file, event_bus=event_bus
    )

    speaker = providers.Singleton(
        Speaker,
        event_bus=event_bus,
    )

    i2c_manager = providers.Singleton(I2CManager)
    brightness_sensor = providers.Singleton(BrightnessSensor, i2c_manager=i2c_manager)
    mcp_manager = providers.Singleton(MCPManager, i2c_manager=i2c_manager)
    button_manager = providers.Singleton(
        ButtonsManager, mcp_manager=mcp_manager, event_bus=event_bus
    )
    rotary_encoder_manager = providers.Singleton(
        RotaryEncoderManager, mcp_manager=mcp_manager, event_bus=event_bus
    )

    controls = providers.Singleton(
        Controls,
        alarm_clock_context=alarm_clock_context,
        display_content=display_content,
        playback_content=playback_content,
        brightness_sensor=brightness_sensor,
        event_bus=event_bus,
    )

    serial_interface = providers.Singleton(spi, device=0, port=0)
    device = providers.Singleton(ssd1322, serial_interface=serial_interface)

    display = providers.Singleton(
        Display,
        device=device,
        display_content=display_content,
        playback_content=playback_content,
        event_bus=event_bus,
        alarm_clock_context=alarm_clock_context,
    )

    api = providers.Singleton(
        Api,
        controls=controls,
        display=display,
        event_bus=event_bus,
        encrypted=not argument_args().software,
    )
