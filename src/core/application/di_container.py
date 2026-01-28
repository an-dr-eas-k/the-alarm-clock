import os
import argparse
import vlc
from concurrent.futures import ThreadPoolExecutor
from dependency_injector import containers, providers
from core.domain.mode_coordinator import AlarmClockModeCoordinator
from core.infrastructure.rpi_gpio import GPIOInputManager, RPiGPIOManager
from core.interface.display.format import DisplayFormatter
from core.interface.hardware_input_handler import HardwareInputHandler
from core.infrastructure.brightness_sensor import BrightnessSensor
from core.infrastructure.i2c_devices import I2CManager, MCPManager
from core.infrastructure.mcp23017.buttons import ButtonsManager
from core.infrastructure.mcp23017.rotary_encoder import RotaryEncoderManager
from core.infrastructure.scheduler import SchedulerService
from core.interface.display.display import Display
from core.application.api import Api
from core.infrastructure.audio import Speaker
from core.application.alarm_audio_service import AlarmAudioService
from core.application.system_service import SystemService
from core.infrastructure.persistence import Persistence
from core.infrastructure.event_bus import EventBus
from resources.resources import config_file
from core.domain.model import (
    AlarmClockContext,
    Config,
    PlaybackContent,
)
from core.interface.display.display_content import DisplayContent
from utils.os_interactions import OSInteraction
from utils.sound_device import TACSoundDevice
from luma.oled.device import ssd1322
from luma.core.interface.serial import spi
from luma.core.framebuffer import diff_to_previous


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

    executor = providers.Singleton(
        ThreadPoolExecutor, max_workers=10, thread_name_prefix="GlobalExecutor"
    )

    event_bus = providers.Singleton(EventBus, executor=executor)

    config = providers.Singleton(
        lambda event_bus: (
            Config.deserialize(config_file, event_bus)
            if os.path.exists(config_file)
            else Config(event_bus=event_bus)
        ),
        event_bus=event_bus,
    )

    os_interaction = providers.Singleton(
        OSInteraction,
        software_mode=argument_args().software,
    )

    alarm_clock_context = providers.Singleton(
        AlarmClockContext,
        config=config,
        is_online=os_interaction().is_internet_available(),
    )

    # Domain layer: Pure business logic, no hardware dependencies
    mode_coordinator = providers.Singleton(
        AlarmClockModeCoordinator,
        event_bus=event_bus,
        alarm_clock_context=alarm_clock_context,
    )

    # Interface layer: Translates hardware events to domain commands
    hardware_input_handler = providers.Singleton(
        HardwareInputHandler,
        event_bus=event_bus,
        mode_coordinator=mode_coordinator,
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
        Persistence,
        config_file=config_file,
        event_bus=event_bus,
        executor=executor,
    )

    vlc_instance = providers.Singleton(
        vlc.Instance, ["--no-video", "--network-caching=3000", "--live-caching=3000"]
    )

    speaker = providers.Singleton(
        Speaker,
        event_bus=event_bus,
        vlc_instance=vlc_instance,
        executor=executor,
    )

    i2c_manager = providers.Singleton(I2CManager)
    brightness_sensor = providers.Singleton(BrightnessSensor, i2c_manager=i2c_manager)
    mcp_manager = providers.Singleton(
        MCPManager, i2c_manager=i2c_manager, executor=executor
    )
    button_manager = providers.Singleton(
        ButtonsManager, mcp_manager=mcp_manager, event_bus=event_bus
    )
    rotary_encoder_manager = providers.Singleton(
        RotaryEncoderManager, mcp_manager=mcp_manager, event_bus=event_bus
    )

    gpio_manager = providers.Singleton(
        RPiGPIOManager,
        executor=executor,
    )
    gpio_input_manager = providers.Singleton(
        GPIOInputManager, gpio_manager=gpio_manager, event_bus=event_bus
    )

    scheduler_service = providers.Singleton(
        SchedulerService,
        event_bus=event_bus,
    )

    system_service = providers.Singleton(
        SystemService,
        alarm_clock_context=alarm_clock_context,
        scheduler_service=scheduler_service,
        event_bus=event_bus,
        display_content=display_content,
        brightness_sensor=brightness_sensor,
        os_interaction=os_interaction,
    )

    alarm_audio_service = providers.Singleton(
        AlarmAudioService,
        alarm_clock_context=alarm_clock_context,
        display_content=display_content,
        playback_content=playback_content,
        brightness_sensor=brightness_sensor,
        event_bus=event_bus,
        scheduler_service=scheduler_service,
        os_interaction=os_interaction,
    )

    serial_interface = providers.Singleton(spi, device=0, port=0, bus_speed_hz=16000000)
    framebuffer = providers.Singleton(diff_to_previous, num_segments=4)
    device = providers.Singleton(
        ssd1322, serial_interface=serial_interface, framebuffer=framebuffer
    )

    display_formatter = providers.Singleton(
        DisplayFormatter,
        content=display_content,
        alarm_clock_context=alarm_clock_context,
    )

    display = providers.Singleton(
        Display,
        device=device,
        display_content=display_content,
        playback_content=playback_content,
        display_formatter=display_formatter,
        event_bus=event_bus,
        alarm_clock_context=alarm_clock_context,
    )

    api = providers.Singleton(
        Api,
        alarm_audio_service=alarm_audio_service,
        display=display,
        event_bus=event_bus,
        executor=executor,
        encrypted=not argument_args().software,
    )
