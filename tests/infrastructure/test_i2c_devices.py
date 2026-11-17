import unittest
from unittest import mock

from core.infrastructure import i2c_devices
from core.infrastructure.i2c_devices import (
    I2CManager,
    MCPManager,
    interrupt_pin,
    invoke_button_channel,
    mode_button_channel,
    rotary_encoder_channel_a,
    rotary_encoder_channel_b,
)


class TestI2CManager(unittest.TestCase):
    def setUp(self):
        busio_patch = mock.patch.object(i2c_devices, "busio")
        board_patch = mock.patch.object(i2c_devices, "board")
        self.busio = busio_patch.start()
        self.board = board_patch.start()
        self.addCleanup(busio_patch.stop)
        self.addCleanup(board_patch.stop)

    def test_opens_i2c_bus_on_board_scl_sda(self):
        manager = I2CManager()

        self.busio.I2C.assert_called_once_with(self.board.SCL, self.board.SDA)
        self.assertIs(self.busio.I2C.return_value, manager.i2c)

    def test_value_error_disables_i2c_and_logs_warning(self):
        self.busio.I2C.side_effect = ValueError("No Hardware I2C on (scl,sda)")

        with self.assertLogs("tac.core.infrastructure.mcp", "WARNING"):
            manager = I2CManager()

        self.assertIsNone(manager.i2c)

    def test_runtime_error_disables_i2c_and_logs_warning(self):
        self.busio.I2C.side_effect = RuntimeError("no i2c")

        with self.assertLogs("tac.core.infrastructure.mcp", "WARNING"):
            manager = I2CManager()

        self.assertIsNone(manager.i2c)

    def test_unexpected_errors_are_not_swallowed(self):
        self.busio.I2C.side_effect = OSError("bus on fire")

        with self.assertRaises(OSError):
            I2CManager()


class MCPManagerTestCase(unittest.TestCase):
    def setUp(self):
        mcp_patch = mock.patch.object(i2c_devices, "MCP23017")
        self.mcp_cls = mcp_patch.start()
        self.addCleanup(mcp_patch.stop)
        self.mcp = self.mcp_cls.return_value
        self.i2c_manager = mock.Mock(i2c=mock.Mock(name="i2c"))
        self.rpigpio = mock.Mock(name="rpigpio_manager")
        self.executor = mock.Mock(name="executor")
        self.manager = MCPManager(self.i2c_manager, self.rpigpio, self.executor)


class TestMCPManagerSetup(MCPManagerTestCase):
    def test_creates_mcp_on_i2c_bus(self):
        self.mcp_cls.assert_called_once_with(self.i2c_manager.i2c)
        self.assertIs(self.mcp, self.manager.mcp)

    def test_add_callback_stores_callback_by_pin(self):
        callback = mock.Mock()

        self.manager.add_callback(3, callback)

        self.assertEqual({3: callback}, self.manager.mcp_callbacks)

    def test_setup_configures_pins_as_pulled_up_inputs(self):
        self.manager.add_callback(0, mock.Mock())
        self.manager.add_callback(1, mock.Mock())

        self.manager.setup()

        self.mcp.get_pin.assert_has_calls([mock.call(0), mock.call(1)])
        pin = self.mcp.get_pin.return_value
        self.assertEqual(i2c_devices.Direction.INPUT, pin.direction)
        self.assertEqual(i2c_devices.Pull.UP, pin.pull)

    def test_setup_enables_interrupts_and_pull_ups_via_bitmask(self):
        for pin in (0, 1, 9, 10):
            self.manager.add_callback(pin, mock.Mock())

        self.manager.setup()

        mask = (1 << 0) | (1 << 1) | (1 << 9) | (1 << 10)
        self.assertEqual(mask, self.mcp.interrupt_enable)
        self.assertEqual(mask, self.mcp.gppu)
        self.assertEqual(0x0000, self.mcp.interrupt_configuration)
        self.assertEqual(0x44, self.mcp.io_control)
        self.mcp.clear_ints.assert_called_once_with()

    def test_setup_registers_interrupt_pin_callback_and_starts_gpio(self):
        self.manager.setup()

        self.rpigpio.add_callback.assert_called_once_with(
            interrupt_pin, self.manager.gpio_event_detected
        )
        self.rpigpio.setup.assert_called_once_with()

    def test_setup_without_callbacks_uses_empty_mask(self):
        self.manager.setup()

        self.assertEqual(0, self.mcp.interrupt_enable)

    def test_close_cleans_up_gpio(self):
        self.manager.close()

        self.rpigpio.cleanup.assert_called_once_with()

    def test_pin_assignments_do_not_overlap(self):
        channels = [
            mode_button_channel,
            invoke_button_channel,
            rotary_encoder_channel_a,
            rotary_encoder_channel_b,
        ]

        self.assertEqual(len(channels), len(set(channels)))


class TestMCPManagerInterrupts(MCPManagerTestCase):
    def _arrange_pins(self, int_flag, int_cap, levels):
        type(self.mcp).int_flag = mock.PropertyMock(return_value=int_flag)
        type(self.mcp).int_cap = mock.PropertyMock(return_value=int_cap)
        self.mcp.get_pin.side_effect = lambda pin: mock.Mock(value=levels[pin])

    def test_changed_pin_callback_gets_captured_value_and_all_pin_values(self):
        callback_a, callback_b = mock.Mock(), mock.Mock()
        self.manager.add_callback(0, callback_a)
        self.manager.add_callback(1, callback_b)
        self._arrange_pins(
            int_flag=[0],
            int_cap={0: 0, 1: 1},
            levels={0: 1, 1: 1},
        )

        self.manager.gpio_event_detected(4)

        callback_a.assert_called_once_with(False, {0: [False, True], 1: [True, True]})
        callback_b.assert_not_called()

    def test_all_flagged_pins_are_dispatched(self):
        callback_a, callback_b = mock.Mock(), mock.Mock()
        self.manager.add_callback(0, callback_a)
        self.manager.add_callback(1, callback_b)
        self._arrange_pins([0, 1], {0: 1, 1: 1}, {0: 1, 1: 1})

        self.manager.gpio_event_detected(4)

        callback_a.assert_called_once()
        callback_b.assert_called_once()

    def test_no_flagged_pins_dispatches_nothing(self):
        callback = mock.Mock()
        self.manager.add_callback(0, callback)
        self._arrange_pins([], {0: 1}, {0: 1})

        self.manager.gpio_event_detected(4)

        callback.assert_not_called()

    def test_flagged_pin_without_callback_raises_key_error(self):
        self.manager.add_callback(0, mock.Mock())
        self._arrange_pins([5], {0: 1}, {0: 1})

        with self.assertRaises(KeyError):
            self.manager.gpio_event_detected(4)


if __name__ == "__main__":
    unittest.main()
