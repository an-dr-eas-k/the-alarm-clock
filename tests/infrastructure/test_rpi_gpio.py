import sys
import logging
import unittest
from concurrent.futures import Executor, Future
from unittest import mock

from core.infrastructure import rpi_gpio
from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
    HwButtonLongPressEvent,
    HwRotaryEvent,
    RotaryDirection,
)
from core.infrastructure.rpi_gpio import (
    GPIODeviceBase,
    GPIOInputManager,
    RPiGPIOManager,
    invoke_button_gpio,
    mode_button_gpio,
    rotary_encoder_a_gpio,
    rotary_encoder_b_gpio,
)
from tests.support import RecordingEventBus


def quiet_event_bus_logger(test_case):
    bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
    previous = bus_logger.level
    bus_logger.setLevel(logging.ERROR)
    test_case.addCleanup(bus_logger.setLevel, previous)


class InlineExecutor(Executor):
    def __init__(self):
        self.submitted = []

    def submit(self, fn, /, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))
        future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def make_fake_gpio(pin_values=None):
    gpio = mock.MagicMock(name="GPIO")
    gpio.IN, gpio.OUT, gpio.BOTH = "IN", "OUT", "BOTH"
    gpio.PUD_UP, gpio.PUD_OFF = "PUD_UP", "PUD_OFF"
    values = pin_values if pin_values is not None else {}
    gpio.input.side_effect = lambda pin: values.get(pin, 1)
    return gpio


class TestGPIODeviceBase(unittest.TestCase):
    def test_gpio_module_is_imported_lazily_and_set_to_bcm_mode(self):
        rpi = mock.MagicMock()
        modules = {"RPi": rpi, "RPi.GPIO": rpi.GPIO}

        with mock.patch.dict(sys.modules, modules):
            device = GPIODeviceBase()
            gpio = device._gpio_module

        self.assertIs(rpi.GPIO, gpio)
        rpi.GPIO.setmode.assert_called_once_with(rpi.GPIO.BCM)

    def test_gpio_module_is_cached_after_first_access(self):
        rpi = mock.MagicMock()

        with mock.patch.dict(sys.modules, {"RPi": rpi, "RPi.GPIO": rpi.GPIO}):
            device = GPIODeviceBase()
            device._gpio_module
            device._gpio_module

        rpi.GPIO.setmode.assert_called_once()

    def test_missing_rpi_library_yields_none_and_logs_warning(self):
        with mock.patch.dict(sys.modules, {"RPi": None}):
            device = GPIODeviceBase()
            with self.assertLogs("tac.core.infrastructure.rpi_gpio", "WARNING"):
                gpio = device._gpio_module

        self.assertIsNone(gpio)

    def test_runtime_error_on_setmode_is_tolerated(self):
        rpi = mock.MagicMock()
        rpi.GPIO.setmode.side_effect = RuntimeError("not a Pi")

        with mock.patch.dict(sys.modules, {"RPi": rpi, "RPi.GPIO": rpi.GPIO}):
            device = GPIODeviceBase()
            with self.assertLogs("tac.core.infrastructure.rpi_gpio", "WARNING"):
                gpio = device._gpio_module

        self.assertIsNone(gpio)


class TestRPiGPIOManager(unittest.TestCase):
    def setUp(self):
        self.executor = InlineExecutor()
        self.manager = RPiGPIOManager(self.executor)
        self.pin_values = {}
        self.gpio = make_fake_gpio(self.pin_values)
        self.manager._gpio_module_cache = self.gpio

    def test_add_callback_registers_per_pin(self):
        callback = mock.Mock()

        self.manager.add_callback(5, callback)

        self.assertEqual({5: callback}, self.manager.gpio_callbacks)

    def test_callbacks_are_not_shared_between_instances(self):
        self.manager.add_callback(5, mock.Mock())

        self.assertEqual({}, RPiGPIOManager(self.executor).gpio_callbacks)

    def test_setup_configures_pull_up_input_and_edge_detection_per_pin(self):
        self.manager.add_callback(5, mock.Mock())
        self.manager.add_callback(6, mock.Mock())

        self.manager.setup()

        self.gpio.setup.assert_has_calls(
            [
                mock.call(5, "IN", pull_up_down="PUD_UP"),
                mock.call(6, "IN", pull_up_down="PUD_UP"),
            ]
        )
        self.gpio.add_event_detect.assert_has_calls(
            [
                mock.call(
                    pin, "BOTH", callback=self.manager.callback_wrapper, bouncetime=2
                )
                for pin in (5, 6)
            ]
        )

    def test_setup_without_callbacks_configures_nothing(self):
        self.manager.setup()

        self.gpio.setup.assert_not_called()

    def test_read_all_pins_returns_int_values_for_registered_pins(self):
        self.pin_values.update({5: True, 6: 0})
        self.manager.add_callback(5, mock.Mock())
        self.manager.add_callback(6, mock.Mock())

        self.assertEqual({5: 1, 6: 0}, self.manager.read_all_pins())

    def test_callback_wrapper_submits_pin_callback_with_bool_value_and_all_pins(self):
        callback = mock.Mock()
        other = mock.Mock()
        self.pin_values.update({5: 0, 6: 1})
        self.manager.add_callback(5, callback)
        self.manager.add_callback(6, other)

        self.manager.callback_wrapper(5)

        callback.assert_called_once_with(False, {5: 0, 6: 1})
        other.assert_not_called()
        self.assertEqual(1, len(self.executor.submitted))

    def test_callback_wrapper_for_unregistered_channel_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.manager.callback_wrapper(99)

    def test_cleanup_delegates_to_gpio_library(self):
        self.manager.cleanup()

        self.gpio.cleanup.assert_called_once_with()


class GPIOInputManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.executor = InlineExecutor()
        self.gpio_manager = RPiGPIOManager(self.executor)
        self.pin_values = {
            mode_button_gpio: 1,
            invoke_button_gpio: 1,
            rotary_encoder_a_gpio: 1,
            rotary_encoder_b_gpio: 1,
        }
        self.gpio_manager._gpio_module_cache = make_fake_gpio(self.pin_values)
        quiet_event_bus_logger(self)
        self.bus = RecordingEventBus()
        timer_patch = mock.patch.object(rpi_gpio.threading, "Timer")
        self.timer_cls = timer_patch.start()
        self.addCleanup(timer_patch.stop)
        self.input_manager = GPIOInputManager(self.gpio_manager, self.bus)


class TestGPIOInputManagerSetup(GPIOInputManagerTestCase):
    def test_registers_callbacks_for_all_inputs_and_configures_gpio(self):
        self.assertEqual(
            {
                mode_button_gpio,
                invoke_button_gpio,
                rotary_encoder_a_gpio,
                rotary_encoder_b_gpio,
            },
            set(self.gpio_manager.gpio_callbacks),
        )
        self.assertEqual(
            4, self.gpio_manager._gpio_module_cache.add_event_detect.call_count
        )

    def test_initial_rotary_state_is_inverted_pin_levels(self):
        self.pin_values[rotary_encoder_a_gpio] = 0
        self.pin_values[rotary_encoder_b_gpio] = 1

        manager = GPIOInputManager(self.gpio_manager, self.bus)

        self.assertEqual([(1, 0), (None, None)], manager.last_states)


class TestGPIOButtons(GPIOInputManagerTestCase):
    def test_mode_button_pressed_emits_down_event_and_starts_long_press_timer(self):
        self.input_manager._mode_button_callback(False)

        self.assertEqual(
            [HwButtonEvent(DeviceName.MODE_BUTTON, ButtonDirection.DOWN)],
            self.bus.emitted,
        )
        self.timer_cls.assert_called_once_with(
            rpi_gpio.LONG_PRESS_DURATION,
            self.input_manager._emit_long_press,
            args=[DeviceName.MODE_BUTTON],
        )
        self.timer_cls.return_value.start.assert_called_once_with()

    def test_mode_button_released_emits_up_event_and_cancels_timer(self):
        self.input_manager._mode_button_callback(False)

        self.input_manager._mode_button_callback(True)

        self.assertEqual(
            HwButtonEvent(DeviceName.MODE_BUTTON, ButtonDirection.UP),
            self.bus.emitted[-1],
        )
        self.timer_cls.return_value.cancel.assert_called_once_with()
        self.assertEqual({}, self.input_manager._long_press_timers)

    def test_invoke_button_pressed_emits_down_event_and_starts_timer(self):
        self.input_manager._invoke_button_callback(False)

        self.assertEqual(
            [HwButtonEvent(DeviceName.INVOKE_BUTTON, ButtonDirection.DOWN)],
            self.bus.emitted,
        )
        self.assertIn(DeviceName.INVOKE_BUTTON, self.input_manager._long_press_timers)

    def test_invoke_button_released_emits_up_event(self):
        self.input_manager._invoke_button_callback(True)

        self.assertEqual(
            [HwButtonEvent(DeviceName.INVOKE_BUTTON, ButtonDirection.UP)],
            self.bus.emitted,
        )

    def test_release_without_press_does_not_fail(self):
        self.input_manager._mode_button_callback(True)

        self.timer_cls.assert_not_called()

    def test_second_press_cancels_previous_timer(self):
        first, second = mock.Mock(), mock.Mock()
        self.timer_cls.side_effect = [first, second]

        self.input_manager._invoke_button_callback(False)
        self.input_manager._invoke_button_callback(False)

        first.cancel.assert_called_once_with()
        second.start.assert_called_once_with()
        self.assertIs(second, self.input_manager._long_press_timers[DeviceName.INVOKE_BUTTON])

    def test_timers_of_both_buttons_are_independent(self):
        self.input_manager._mode_button_callback(False)
        self.input_manager._invoke_button_callback(False)

        self.input_manager._mode_button_callback(True)

        self.assertEqual(
            {DeviceName.INVOKE_BUTTON}, set(self.input_manager._long_press_timers)
        )

    def test_emit_long_press_emits_event_and_forgets_timer(self):
        self.input_manager._invoke_button_callback(False)

        self.input_manager._emit_long_press(DeviceName.INVOKE_BUTTON)

        self.assertEqual(
            HwButtonLongPressEvent(DeviceName.INVOKE_BUTTON), self.bus.emitted[-1]
        )
        self.assertEqual({}, self.input_manager._long_press_timers)

    def test_button_callbacks_are_wired_through_gpio_manager(self):
        self.pin_values[mode_button_gpio] = 0

        self.gpio_manager.callback_wrapper(mode_button_gpio)

        self.assertEqual(
            HwButtonEvent(DeviceName.MODE_BUTTON, ButtonDirection.DOWN),
            self.bus.emitted[-1],
        )


class TestGPIORotary(GPIOInputManagerTestCase):
    def _rotate(self, a, b):
        self.input_manager._rotary_encoder_callback(
            bool(a),
            {rotary_encoder_a_gpio: a, rotary_encoder_b_gpio: b},
        )

    def test_a_high_b_low_is_clockwise_first_tick(self):
        self._rotate(1, 0)

        self.assertEqual(
            [HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE, True)],
            self.bus.emitted,
        )

    def test_a_low_b_high_is_clockwise_later_tick(self):
        self._rotate(0, 1)

        self.assertEqual(
            [HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE, False)],
            self.bus.emitted,
        )

    def test_equal_levels_with_a_low_is_counterclockwise_first_tick(self):
        self._rotate(0, 0)

        self.assertEqual(
            [
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE, True
                )
            ],
            self.bus.emitted,
        )

    def test_equal_levels_with_a_high_is_counterclockwise_later_tick(self):
        self._rotate(1, 1)

        self.assertEqual(
            [
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE, False
                )
            ],
            self.bus.emitted,
        )

    def test_last_states_track_history(self):
        initial = self.input_manager.last_states[0]

        self._rotate(1, 0)

        self.assertEqual((1, 0), self.input_manager.last_states[0])
        self.assertEqual(initial, self.input_manager.last_states[1])


if __name__ == "__main__":
    unittest.main()
