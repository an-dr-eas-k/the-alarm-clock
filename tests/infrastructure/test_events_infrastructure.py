import dataclasses
import unittest

from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
    HwButtonLongPressEvent,
    HwEvent,
    HwRotaryEvent,
    RotaryDirection,
)


class TestEnums(unittest.TestCase):
    def test_device_name_str_is_value(self):
        self.assertEqual("mode_button", str(DeviceName.MODE_BUTTON))
        self.assertEqual("invoke_button", str(DeviceName.INVOKE_BUTTON))
        self.assertEqual("rotary_encoder", str(DeviceName.ROTARY_ENCODER))

    def test_button_direction_str_is_lowercase_name(self):
        self.assertEqual("down", str(ButtonDirection.DOWN))
        self.assertEqual("up", str(ButtonDirection.UP))

    def test_rotary_direction_str_is_lowercase_name(self):
        self.assertEqual("clockwise", str(RotaryDirection.CLOCKWISE))
        self.assertEqual("counterclockwise", str(RotaryDirection.COUNTERCLOCKWISE))


class TestHwEvents(unittest.TestCase):
    def test_button_event_defaults_to_down(self):
        event = HwButtonEvent(DeviceName.MODE_BUTTON)

        self.assertEqual(ButtonDirection.DOWN, event.direction)
        self.assertFalse(event.suppress_logging)

    def test_button_event_str(self):
        event = HwButtonEvent(DeviceName.INVOKE_BUTTON, ButtonDirection.UP)

        self.assertEqual("HwButtonEvent.invoke_button.up", str(event))

    def test_long_press_event_str(self):
        event = HwButtonLongPressEvent(DeviceName.INVOKE_BUTTON)

        self.assertEqual("HwButtonLongPressEvent.invoke_button", str(event))

    def test_rotary_event_str_includes_direction_and_tick(self):
        event = HwRotaryEvent(
            DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE, True
        )

        self.assertEqual("HwRotaryEvent.rotary_encoder.clockwise.True", str(event))

    def test_rotary_event_requires_first_tick_flag(self):
        with self.assertRaises(TypeError):
            HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE)

    def test_events_are_frozen(self):
        event = HwButtonEvent(DeviceName.MODE_BUTTON)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.direction = ButtonDirection.UP

    def test_events_with_same_values_are_equal(self):
        self.assertEqual(
            HwButtonEvent(DeviceName.MODE_BUTTON),
            HwButtonEvent(DeviceName.MODE_BUTTON, ButtonDirection.DOWN),
        )

    def test_all_events_are_hw_events(self):
        self.assertTrue(issubclass(HwButtonEvent, HwEvent))
        self.assertTrue(issubclass(HwButtonLongPressEvent, HwEvent))
        self.assertTrue(issubclass(HwRotaryEvent, HwEvent))


if __name__ == "__main__":
    unittest.main()
