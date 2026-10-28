import logging
import unittest
from unittest import mock

from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
)
from core.infrastructure.i2c_devices import invoke_button_channel, mode_button_channel
from core.infrastructure.mcp23017.buttons import ButtonsManager
from tests.support import RecordingEventBus


class TestButtonsManager(unittest.TestCase):
    def setUp(self):
        bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
        self.addCleanup(bus_logger.setLevel, bus_logger.level)
        bus_logger.setLevel(logging.ERROR)
        self.mcp_manager = mock.Mock(name="mcp_manager")
        self.bus = RecordingEventBus()
        self.buttons = ButtonsManager(self.mcp_manager, self.bus)

    def test_registers_callbacks_for_both_buttons_and_sets_up_mcp(self):
        self.mcp_manager.add_callback.assert_has_calls(
            [
                mock.call(mode_button_channel, self.buttons._mode_button_callback),
                mock.call(invoke_button_channel, self.buttons._invoke_button_callback),
            ]
        )
        self.mcp_manager.setup.assert_called_once_with()

    def test_mode_button_low_level_is_down(self):
        self.buttons._mode_button_callback(False)

        self.assertEqual(
            [HwButtonEvent(DeviceName.MODE_BUTTON, ButtonDirection.DOWN)],
            self.bus.emitted,
        )

    def test_mode_button_high_level_is_up(self):
        self.buttons._mode_button_callback(True)

        self.assertEqual(
            [HwButtonEvent(DeviceName.MODE_BUTTON, ButtonDirection.UP)],
            self.bus.emitted,
        )

    def test_invoke_button_low_level_is_down(self):
        self.buttons._invoke_button_callback(False)

        self.assertEqual(
            [HwButtonEvent(DeviceName.INVOKE_BUTTON, ButtonDirection.DOWN)],
            self.bus.emitted,
        )

    def test_invoke_button_high_level_is_up(self):
        self.buttons._invoke_button_callback(True)

        self.assertEqual(
            [HwButtonEvent(DeviceName.INVOKE_BUTTON, ButtonDirection.UP)],
            self.bus.emitted,
        )

    def test_callbacks_accept_pin_values_argument_from_mcp_manager(self):
        self.buttons._mode_button_callback(False, {0: [False, False]})
        self.buttons._invoke_button_callback(True, {1: [True, True]})

        self.assertEqual(2, len(self.bus.emitted))

    def test_registered_callback_drives_events_end_to_end(self):
        callback = self.mcp_manager.add_callback.call_args_list[0].args[1]

        callback(False, {})

        self.assertEqual(DeviceName.MODE_BUTTON, self.bus.emitted[0].device_name)


if __name__ == "__main__":
    unittest.main()
