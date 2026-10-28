import logging
import unittest
from unittest import mock

from core.domain.events import (
    ForcedDisplayUpdateEvent,
    StreamChangeRequest,
    ToggleAudioRequest,
    VolumeChangeRequest,
)
from core.domain.mode_coordinator import ModeName
from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
    HwButtonLongPressEvent,
    HwRotaryEvent,
    RotaryDirection,
)
from core.interface.hardware_input_handler import HardwareInputHandler
from tests.support import RecordingEventBus

ALL_NON_DEFAULT_MODES = [m for m in ModeName if m != ModeName.DEFAULT]
HW_EVENT_TYPES = (HwButtonEvent, HwButtonLongPressEvent, HwRotaryEvent)


class HandlerTestCase(unittest.TestCase):
    def setUp(self):
        bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
        self.addCleanup(bus_logger.setLevel, bus_logger.level)
        bus_logger.setLevel(logging.ERROR)
        self.bus = RecordingEventBus()
        self.coordinator = mock.Mock(name="mode_coordinator")
        self.coordinator.current_mode_name = ModeName.DEFAULT
        self.handler = HardwareInputHandler(self.bus, self.coordinator)

    def emit_button(self, device, direction=ButtonDirection.DOWN):
        self.bus.emit(HwButtonEvent(device, direction))

    def emit_rotary(self, direction, first_tick=True):
        self.bus.emit(HwRotaryEvent(DeviceName.ROTARY_ENCODER, direction, first_tick))

    def emitted_types(self):
        return [type(e) for e in self.bus.emitted if not isinstance(e, HW_EVENT_TYPES)]


class TestButtons(HandlerTestCase):
    def test_mode_button_down_calls_coordinator_and_forces_display_update(self):
        self.emit_button(DeviceName.MODE_BUTTON)

        self.coordinator.handle_mode_button.assert_called_once_with()
        self.assertEqual([ForcedDisplayUpdateEvent], self.emitted_types())

    def test_mode_button_works_in_every_mode(self):
        for mode in ModeName:
            self.coordinator.reset_mock()
            self.coordinator.current_mode_name = mode

            self.emit_button(DeviceName.MODE_BUTTON)

            self.coordinator.handle_mode_button.assert_called_once_with()

    def test_button_release_is_ignored(self):
        self.emit_button(DeviceName.MODE_BUTTON, ButtonDirection.UP)
        self.emit_button(DeviceName.INVOKE_BUTTON, ButtonDirection.UP)

        self.coordinator.handle_mode_button.assert_not_called()
        self.coordinator.handle_invoke_button.assert_not_called()
        self.assertEqual([], self.emitted_types())

    def test_invoke_button_in_default_mode_requests_audio_toggle(self):
        self.emit_button(DeviceName.INVOKE_BUTTON)

        self.assertEqual([ToggleAudioRequest], self.emitted_types())
        self.coordinator.handle_invoke_button.assert_not_called()

    def test_invoke_button_in_other_modes_is_forwarded_to_coordinator(self):
        for mode in ALL_NON_DEFAULT_MODES:
            self.coordinator.reset_mock()
            self.bus.emitted.clear()
            self.coordinator.current_mode_name = mode

            self.emit_button(DeviceName.INVOKE_BUTTON)

            self.coordinator.handle_invoke_button.assert_called_once_with()
            self.assertEqual([ForcedDisplayUpdateEvent], self.emitted_types(), mode)

    def test_rotary_device_button_event_only_forces_display_update(self):
        self.emit_button(DeviceName.ROTARY_ENCODER)

        self.coordinator.handle_mode_button.assert_not_called()
        self.coordinator.handle_invoke_button.assert_not_called()
        self.assertEqual([ForcedDisplayUpdateEvent], self.emitted_types())


class TestLongPress(HandlerTestCase):
    def test_invoke_long_press_in_default_mode_requests_stream_change(self):
        self.bus.emit(HwButtonLongPressEvent(DeviceName.INVOKE_BUTTON))

        self.assertEqual([StreamChangeRequest], self.emitted_types())

    def test_invoke_long_press_outside_default_mode_is_ignored(self):
        for mode in ALL_NON_DEFAULT_MODES:
            self.coordinator.current_mode_name = mode

            self.bus.emit(HwButtonLongPressEvent(DeviceName.INVOKE_BUTTON))

        self.assertEqual([], self.emitted_types())

    def test_mode_button_long_press_is_ignored(self):
        self.bus.emit(HwButtonLongPressEvent(DeviceName.MODE_BUTTON))

        self.assertEqual([], self.emitted_types())


class TestRotary(HandlerTestCase):
    def test_clockwise_in_default_mode_increases_volume_without_display_update(self):
        self.emit_rotary(RotaryDirection.CLOCKWISE)

        requests = self.bus.emitted_of(VolumeChangeRequest)
        self.assertEqual([1], [r.relative for r in requests])
        self.assertEqual([VolumeChangeRequest], self.emitted_types())

    def test_counterclockwise_in_default_mode_decreases_volume(self):
        self.emit_rotary(RotaryDirection.COUNTERCLOCKWISE)

        self.assertEqual(
            [-1], [r.relative for r in self.bus.emitted_of(VolumeChangeRequest)]
        )

    def test_later_ticks_are_ignored(self):
        for mode in ModeName:
            self.coordinator.current_mode_name = mode
            self.emit_rotary(RotaryDirection.CLOCKWISE, first_tick=False)

        self.assertEqual([], self.emitted_types())
        self.coordinator.navigate_alarms.assert_not_called()

    def _assert_navigation(self, mode, method_name):
        self.coordinator.reset_mock()
        self.bus.emitted.clear()
        self.coordinator.current_mode_name = mode

        self.emit_rotary(RotaryDirection.CLOCKWISE)
        self.emit_rotary(RotaryDirection.COUNTERCLOCKWISE)

        method = getattr(self.coordinator, method_name)
        self.assertEqual([mock.call(1), mock.call(-1)], method.call_args_list)
        self.assertEqual([ForcedDisplayUpdateEvent] * 2, self.emitted_types(), mode)

    def test_alarm_view_navigates_alarms(self):
        self._assert_navigation(ModeName.ALARM_VIEW, "navigate_alarms")

    def test_alarm_edit_navigates_properties(self):
        self._assert_navigation(ModeName.ALARM_EDIT, "navigate_properties")

    def test_property_edit_navigates_property_values(self):
        self._assert_navigation(ModeName.PROPERTY_EDIT, "navigate_property_values")

    def test_day_picker_navigates_day_picker(self):
        self._assert_navigation(ModeName.DAY_PICKER, "navigate_day_picker")

    def test_only_the_matching_navigation_method_is_called(self):
        self.coordinator.current_mode_name = ModeName.ALARM_EDIT

        self.emit_rotary(RotaryDirection.CLOCKWISE)

        self.coordinator.navigate_alarms.assert_not_called()
        self.coordinator.navigate_property_values.assert_not_called()
        self.coordinator.navigate_day_picker.assert_not_called()

    def test_default_mode_never_calls_navigation(self):
        self.emit_rotary(RotaryDirection.CLOCKWISE)

        for name in (
            "navigate_alarms",
            "navigate_properties",
            "navigate_property_values",
            "navigate_day_picker",
        ):
            getattr(self.coordinator, name).assert_not_called()


class TestWiring(HandlerTestCase):
    def test_handler_subscribes_to_all_hardware_event_types(self):
        for event_type in HW_EVENT_TYPES:
            self.assertEqual(1, len(self.bus._handlers[event_type]))

    def test_stores_dependencies(self):
        self.assertIs(self.bus, self.handler.event_bus)
        self.assertIs(self.coordinator, self.handler.mode_coordinator)

    def test_coordinator_errors_are_isolated_by_event_bus(self):
        self.coordinator.handle_mode_button.side_effect = RuntimeError("boom")

        with self.assertLogs("tac.core.infrastructure.event_bus", "ERROR"):
            self.emit_button(DeviceName.MODE_BUTTON)

        self.assertEqual([], self.emitted_types())


if __name__ == "__main__":
    unittest.main()
