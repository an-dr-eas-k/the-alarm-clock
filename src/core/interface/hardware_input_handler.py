"""
Interface Layer: Translates hardware input events into domain commands.

This adapter sits between the hardware infrastructure and the domain layer,
following DDD principles by keeping infrastructure concerns out of the domain.
"""

import logging

from core.domain.mode_coordinator import AlarmClockModeCoordinator, ModeName
from core.domain.events import ToggleAudioRequest, VolumeChangeRequest
from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
    HwRotaryEvent,
    RotaryDirection,
)

logger = logging.getLogger("tac.hardware_input_handler")


class HardwareInputHandler:

    def __init__(
        self,
        event_bus,
        mode_coordinator: AlarmClockModeCoordinator,
    ):
        self.event_bus = event_bus
        self.mode_coordinator = mode_coordinator

        self.event_bus.on(HwButtonEvent)(self._handle_button_event)
        self.event_bus.on(HwRotaryEvent)(self._handle_rotary_event)

    def _handle_button_event(self, event: HwButtonEvent):
        current_mode = self.mode_coordinator.current_mode_name
        if event.direction != ButtonDirection.DOWN:
            return

        if event.device_name == DeviceName.MODE_BUTTON:
            self.mode_coordinator.handle_mode_button()

        elif event.device_name == DeviceName.INVOKE_BUTTON:
            if current_mode == ModeName.DEFAULT:
                self.event_bus.emit(ToggleAudioRequest())
            else:
                self.mode_coordinator.handle_invoke_button()

        logger.debug(
            f"Button event translated: {event.device_name} in mode {current_mode}"
        )

    def _handle_rotary_event(self, event: HwRotaryEvent):
        current_mode = self.mode_coordinator.current_mode_name
        direction = 1 if event.direction == RotaryDirection.CLOCKWISE else -1

        if current_mode == ModeName.DEFAULT:
            self.event_bus.emit(VolumeChangeRequest(relative=direction))

        elif current_mode == ModeName.ALARM_VIEW:
            self.mode_coordinator.navigate_alarms(direction)

        elif current_mode == ModeName.ALARM_EDIT:
            self.mode_coordinator.navigate_properties(direction)

        elif current_mode == ModeName.PROPERTY_EDIT:
            self.mode_coordinator.navigate_property_values(direction)

        logger.debug(
            f"Rotary event translated: {event.direction} in mode {current_mode}"
        )
