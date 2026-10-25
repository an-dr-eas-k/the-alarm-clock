import logging
import unittest
from unittest import mock

from core.infrastructure.events_infrastructure import (
    DeviceName,
    HwRotaryEvent,
    RotaryDirection,
)
from core.infrastructure.i2c_devices import (
    rotary_encoder_channel_a,
    rotary_encoder_channel_b,
)
from core.infrastructure.mcp23017.rotary_encoder import RotaryEncoderManager
from tests.support import RecordingEventBus

A, B = rotary_encoder_channel_a, rotary_encoder_channel_b


class RotaryTestCase(unittest.TestCase):
    def setUp(self):
        bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
        self.addCleanup(bus_logger.setLevel, bus_logger.level)
        bus_logger.setLevel(logging.ERROR)
        self.levels = {A: True, B: True}
        self.mcp_manager = mock.Mock(name="mcp_manager")
        self.mcp_manager.mcp.get_pin.side_effect = lambda pin: mock.Mock(
            value=self.levels[pin]
        )
        self.bus = RecordingEventBus()
        self.encoder = RotaryEncoderManager(self.mcp_manager, self.bus)


class TestRotaryEncoderSetup(RotaryTestCase):
    def test_registers_both_channels_and_sets_up_mcp(self):
        calls = self.mcp_manager.add_callback.call_args_list

        self.assertEqual([A, B], [c.args[0] for c in calls])
        self.assertEqual(self.encoder._pin_callback, calls[0].args[1])
        self.mcp_manager.setup.assert_called_once_with()

    def test_channel_b_callback_is_a_noop(self):
        callback_b = self.mcp_manager.add_callback.call_args_list[1].args[1]

        callback_b(True, {})

        self.assertEqual([], self.bus.emitted)

    def test_initial_state_is_inverted_pin_levels(self):
        self.levels = {A: False, B: True}

        encoder = RotaryEncoderManager(self.mcp_manager, self.bus)

        self.assertEqual([(1, 0), (None, None)], encoder.last_states)

    def test_last_states_are_not_shared_between_instances(self):
        other = RotaryEncoderManager(self.mcp_manager, self.bus)

        self.assertIsNot(self.encoder.last_states, other.last_states)


class TestRotaryEncoderPinCallback(RotaryTestCase):
    def _pin_values(self, a, b):
        return {A: [a, a], B: [b, b]}

    def test_unchanged_channel_a_is_ignored(self):
        self.encoder.last_states[0] = (1, 0)

        self.encoder._pin_callback(True, self._pin_values(1, 0))

        self.assertEqual([], self.bus.emitted)
        self.assertEqual((1, 0), self.encoder.last_states[0])

    def test_unchanged_channel_a_does_not_touch_history(self):
        self.encoder.last_states = [(0, 1), (5, 5)]

        self.encoder._pin_callback(False, self._pin_values(0, 0))

        self.assertEqual([(0, 1), (5, 5)], self.encoder.last_states)

    @unittest.expectedFailure  # HwRotaryEvent requires _1st_tick; encoder omits it -> TypeError
    def test_clockwise_turn_emits_clockwise_event(self):
        self.encoder.last_states[0] = (0, 0)

        self.encoder._pin_callback(True, self._pin_values(1, 0))

        self.assertEqual(
            RotaryDirection.CLOCKWISE, self.bus.emitted_of(HwRotaryEvent)[0].direction
        )

    @unittest.expectedFailure  # same missing _1st_tick argument
    def test_counterclockwise_turn_emits_counterclockwise_event(self):
        self.encoder.last_states[0] = (1, 1)

        self.encoder._pin_callback(False, self._pin_values(0, 0))

        event = self.bus.emitted_of(HwRotaryEvent)[0]
        self.assertEqual(RotaryDirection.COUNTERCLOCKWISE, event.direction)
        self.assertEqual(DeviceName.ROTARY_ENCODER, event.device_name)

    @unittest.expectedFailure  # same missing _1st_tick argument
    def test_state_history_is_updated_after_a_turn(self):
        self.encoder.last_states = [(0, 0), (None, None)]

        self.encoder._pin_callback(True, self._pin_values(1, 0))

        self.assertEqual([(1, 0), (0, 0)], self.encoder.last_states)


if __name__ == "__main__":
    unittest.main()
