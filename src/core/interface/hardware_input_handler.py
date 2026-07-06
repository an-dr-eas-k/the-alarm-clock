"""
Interface Layer: Translates hardware input events into domain commands.

This adapter sits between the hardware infrastructure and the domain layer,
following DDD principles by keeping infrastructure concerns out of the domain.
"""

import logging

from core.domain.mode_coordinator import AlarmClockModeCoordinator, ModeName
from core.domain.events import (
    ForcedDisplayUpdateEvent,
    ToggleAudioRequest,
    VolumeChangeRequest,
)
from core.infrastructure.event_bus import EventBus
from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
    HwRotaryEvent,
    RotaryDirection,
)

logger = logging.getLogger("tac.core.interface.hardware_input_handler")


class HardwareInputHandler:

    def __init__(
        self,
        event_bus: EventBus,
        mode_coordinator: AlarmClockModeCoordinator,
    ):
        self.event_bus: EventBus = event_bus
        self.mode_coordinator: AlarmClockModeCoordinator = mode_coordinator

        self.event_bus.on(HwButtonEvent)(self._handle_button_event)
        self.event_bus.on(HwRotaryEvent)(self._handle_rotary_event)

    def _handle_button_event(self, event: HwButtonEvent):
        current_mode = self.mode_coordinator.current_mode_name
        logger.debug(
            f"translating button event: {event.device_name}, {event.direction} in mode {current_mode}"
        )
        if event.direction != ButtonDirection.DOWN:
            return

        if event.device_name == DeviceName.MODE_BUTTON:
            self.mode_coordinator.handle_mode_button()

        elif event.device_name == DeviceName.INVOKE_BUTTON:
            if current_mode == ModeName.DEFAULT:
                self.event_bus.emit(ToggleAudioRequest())
                return
            else:
                self.mode_coordinator.handle_invoke_button()

        self.event_bus.emit(ForcedDisplayUpdateEvent())

    def _handle_rotary_event(self, event: HwRotaryEvent):
        current_mode = self.mode_coordinator.current_mode_name
        direction = 1 if event.direction == RotaryDirection.CLOCKWISE else -1
        if not event._1st_tick:
            return

        logger.debug(
            f"translating rotary event: {event.direction} in mode {current_mode}"
        )

        if current_mode == ModeName.DEFAULT:
            self.event_bus.emit(VolumeChangeRequest(relative=direction))
            return

        elif current_mode == ModeName.ALARM_VIEW:
            self.mode_coordinator.navigate_alarms(direction)

        elif current_mode == ModeName.ALARM_EDIT:
            self.mode_coordinator.navigate_properties(direction)

        elif current_mode == ModeName.PROPERTY_EDIT:
            self.mode_coordinator.navigate_property_values(direction)

        elif current_mode == ModeName.DAY_PICKER:
            self.mode_coordinator.navigate_day_picker(direction)

        self.event_bus.emit(ForcedDisplayUpdateEvent())
