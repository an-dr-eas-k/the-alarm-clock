import logging
import unittest
from unittest import mock

from evdev import ecodes

from core.infrastructure import computer_infrastructure
from core.infrastructure.computer_infrastructure import ComputerInfrastructure
from core.infrastructure.events_infrastructure import (
    ButtonDirection,
    DeviceName,
    HwButtonEvent,
    HwButtonLongPressEvent,
    HwRotaryEvent,
    RotaryDirection,
)
from tests.support import RecordingEventBus


def key_event(code, value=1, type_=ecodes.EV_KEY):
    return mock.Mock(code=code, value=value, type=type_)


class ComputerInfrastructureTestCase(unittest.TestCase):
    def setUp(self):
        bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
        self.addCleanup(bus_logger.setLevel, bus_logger.level)
        bus_logger.setLevel(logging.ERROR)
        evdev_patch = mock.patch.object(computer_infrastructure, "evdev")
        self.evdev = evdev_patch.start()
        self.addCleanup(evdev_patch.stop)
        self.executor = mock.Mock(name="executor")
        self.infra = ComputerInfrastructure(self.executor)
        self.bus = RecordingEventBus()
        self.alarm_audio_service = mock.Mock(event_bus=self.bus)
        self.config = self.alarm_audio_service.alarm_clock_context.config
        self.infra.configure(self.alarm_audio_service)


class TestStartup(ComputerInfrastructureTestCase):
    def test_constructor_submits_run_loop_to_executor(self):
        self.executor.submit.assert_called_once_with(self.infra._run_loop)

    def test_is_running_after_start(self):
        self.assertTrue(self.infra.running)

    def test_stop_clears_running_flag(self):
        self.infra.stop()

        self.assertFalse(self.infra.running)

    def test_configure_wires_service_config_and_event_bus(self):
        self.assertIs(self.alarm_audio_service, self.infra.alarm_audio_service)
        self.assertIs(self.config, self.infra.config)
        self.assertIs(self.bus, self.infra.event_bus)


class TestKeyboardDiscovery(ComputerInfrastructureTestCase):
    def _devices(self, *names):
        devices = [mock.Mock(path=f"/dev/input/event{i}") for i in range(len(names))]
        for device, name in zip(devices, names):
            device.name = name
        self.evdev.list_devices.return_value = [d.path for d in devices]
        self.evdev.InputDevice.side_effect = devices
        return devices

    def test_find_keyboards_filters_by_name_case_insensitively(self):
        kbd, _mouse, kbd2 = self._devices("AT Keyboard", "Logitech Mouse", "USB KEYBOARD")

        self.assertEqual([kbd, kbd2], self.infra._find_keyboards())

    def test_find_keyboards_returns_empty_when_listing_fails(self):
        self.evdev.list_devices.side_effect = PermissionError("/dev/input")

        with self.assertLogs("tac.core.infrastructure.keyboard_buttons", "ERROR"):
            self.assertEqual([], self.infra._find_keyboards())

    def test_run_loop_listens_on_every_keyboard(self):
        kbd, kbd2 = self._devices("Keyboard A", "Keyboard B")
        self.executor.reset_mock()

        self.infra._run_loop()

        self.executor.submit.assert_has_calls(
            [
                mock.call(self.infra._listen_to_device, kbd),
                mock.call(self.infra._listen_to_device, kbd2),
            ]
        )

    def test_run_loop_without_keyboards_logs_error_and_submits_nothing(self):
        self._devices("Mouse")
        self.executor.reset_mock()

        with self.assertLogs("tac.core.infrastructure.keyboard_buttons", "ERROR"):
            self.infra._run_loop()

        self.executor.submit.assert_not_called()


class TestListenToDevice(ComputerInfrastructureTestCase):
    def test_key_down_events_are_forwarded_to_on_press(self):
        device = mock.Mock()
        down = key_event(ecodes.KEY_1, value=1)
        device.read_loop.return_value = [down]

        with mock.patch.object(self.infra, "on_press") as on_press:
            self.infra._listen_to_device(device)

        on_press.assert_called_once_with(down, device)

    def test_key_up_and_repeat_events_are_ignored(self):
        device = mock.Mock()
        device.read_loop.return_value = [
            key_event(ecodes.KEY_1, value=0),
            key_event(ecodes.KEY_1, value=2),
        ]

        with mock.patch.object(self.infra, "on_press") as on_press:
            self.infra._listen_to_device(device)

        on_press.assert_not_called()

    def test_non_key_events_are_ignored(self):
        device = mock.Mock()
        device.read_loop.return_value = [
            key_event(ecodes.KEY_1, value=1, type_=ecodes.EV_SYN)
        ]

        with mock.patch.object(self.infra, "on_press") as on_press:
            self.infra._listen_to_device(device)

        on_press.assert_not_called()

    def test_loop_ends_when_stopped(self):
        device = mock.Mock()
        device.read_loop.return_value = [key_event(ecodes.KEY_1), key_event(ecodes.KEY_2)]
        self.infra.stop()

        with mock.patch.object(self.infra, "on_press") as on_press:
            self.infra._listen_to_device(device)

        on_press.assert_not_called()

    def test_device_errors_are_logged_not_raised(self):
        device = mock.Mock()
        device.name = "Keyboard"
        device.read_loop.side_effect = OSError("device unplugged")

        with self.assertLogs("tac.core.infrastructure.keyboard_buttons", "WARNING"):
            self.infra._listen_to_device(device)


class TestOnPress(ComputerInfrastructureTestCase):
    def test_key_1_emits_counterclockwise_rotary_first_tick(self):
        self.infra.on_press(key_event(ecodes.KEY_1))

        self.assertEqual(
            [
                HwRotaryEvent(
                    DeviceName.ROTARY_ENCODER, RotaryDirection.COUNTERCLOCKWISE, True
                )
            ],
            self.bus.emitted,
        )

    def test_key_2_emits_clockwise_rotary_first_tick(self):
        self.infra.on_press(key_event(ecodes.KEY_2))

        self.assertEqual(
            [HwRotaryEvent(DeviceName.ROTARY_ENCODER, RotaryDirection.CLOCKWISE, True)],
            self.bus.emitted,
        )

    def test_key_3_emits_mode_button_down(self):
        self.infra.on_press(key_event(ecodes.KEY_3))

        self.assertEqual(
            [HwButtonEvent(DeviceName.MODE_BUTTON, ButtonDirection.DOWN)],
            self.bus.emitted,
        )

    def test_key_4_emits_invoke_button_down(self):
        self.infra.on_press(key_event(ecodes.KEY_4))

        self.assertEqual(
            [HwButtonEvent(DeviceName.INVOKE_BUTTON, ButtonDirection.DOWN)],
            self.bus.emitted,
        )

    def test_key_8_emits_invoke_long_press(self):
        self.infra.on_press(key_event(ecodes.KEY_8))

        self.assertEqual(
            [HwButtonLongPressEvent(DeviceName.INVOKE_BUTTON)], self.bus.emitted
        )

    def test_key_5_cycles_simulated_brightness_and_wraps(self):
        seen = []
        for _ in range(6):
            self.infra.on_press(key_event(ecodes.KEY_5))
            seen.append(self.infra.get_room_brightness())

        self.assertEqual([0.0, 0.1, 0.3, 0.8, 1.0, 0.0], seen)
        self.assertEqual([], self.bus.emitted)

    def test_key_6_rings_default_alarm(self):
        self.infra.on_press(key_event(ecodes.KEY_6))

        self.alarm_audio_service._ring_alarm.assert_called_once_with(
            self.config.get_default_alarm_definition.return_value
        )

    def test_key_7_rings_default_alarm_with_invalid_stream_url(self):
        alarm = self.config.get_default_alarm_definition.return_value

        self.infra.on_press(key_event(ecodes.KEY_7))

        self.assertEqual("invalid_stream_url", alarm.audio_effect.audio_stream.stream_url)
        self.alarm_audio_service._ring_alarm.assert_called_once_with(alarm)

    def test_unmapped_key_does_nothing(self):
        self.infra.on_press(key_event(ecodes.KEY_A))

        self.assertEqual([], self.bus.emitted)
        self.alarm_audio_service._ring_alarm.assert_not_called()

    def test_device_argument_is_optional(self):
        self.infra.on_press(key_event(ecodes.KEY_3), device=mock.Mock(name="kbd"))

        self.assertEqual(1, len(self.bus.emitted))

    def test_errors_in_handlers_are_logged_not_raised(self):
        self.alarm_audio_service._ring_alarm.side_effect = RuntimeError("no audio")

        with self.assertLogs("tac.core.infrastructure.keyboard_buttons", "WARNING"):
            self.infra.on_press(key_event(ecodes.KEY_6))


class TestBrightness(ComputerInfrastructureTestCase):
    def test_default_simulated_brightness_is_full(self):
        self.assertEqual(1.0, self.infra.get_room_brightness())

    def test_changing_brightness_keeps_class_default_untouched(self):
        self.infra.on_press(key_event(ecodes.KEY_5))

        self.assertEqual(1.0, ComputerInfrastructure.simulated_brightness)


if __name__ == "__main__":
    unittest.main()
