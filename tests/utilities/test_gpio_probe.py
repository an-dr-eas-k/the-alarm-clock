import contextlib
import importlib
import io
import sys
import types
import unittest
from unittest import mock

FAKE_MODULES = ("RPi", "RPi.GPIO", "utils.gpio_probe")


def import_gpio_probe_with_fake_rpi():
    """Import gpio_probe against a fake RPi.GPIO; returns (module, fake_gpio)."""
    gpio = mock.MagicMock(name="GPIO")
    gpio.BCM, gpio.IN, gpio.OUT = "BCM", "IN", "OUT"
    gpio.HIGH, gpio.LOW = 1, 0
    gpio.PUD_UP, gpio.PUD_DOWN = "PUD_UP", "PUD_DOWN"
    rpi = types.ModuleType("RPi")
    rpi.GPIO = gpio

    saved = {name: sys.modules.get(name) for name in FAKE_MODULES}
    sys.modules["RPi"] = rpi
    sys.modules["RPi.GPIO"] = gpio
    sys.modules.pop("utils.gpio_probe", None)
    try:
        module = importlib.import_module("utils.gpio_probe")
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module, gpio


class StopLoop(Exception):
    pass


class GpioProbeTestCase(unittest.TestCase):
    def setUp(self):
        self.probe, self.gpio = import_gpio_probe_with_fake_rpi()
        self.addCleanup(sys.modules.pop, "utils.gpio_probe", None)
        sleep = mock.patch.object(self.probe.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def run_main(self, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["gpio_probe.py", *argv]):
            with contextlib.redirect_stdout(out):
                self.probe.main()
        return out.getvalue()

    def sleep_then_interrupt(self, calls_before_interrupt):
        count = {"n": 0}

        def fake_sleep(_):
            count["n"] += 1
            if count["n"] > calls_before_interrupt:
                raise KeyboardInterrupt

        self.sleep.side_effect = fake_sleep


class ImportIsolationTest(unittest.TestCase):
    def test_fake_rpi_does_not_leak_into_sys_modules(self):
        had_rpi = "RPi" in sys.modules
        import_gpio_probe_with_fake_rpi()
        sys.modules.pop("utils.gpio_probe", None)
        self.assertEqual("RPi" in sys.modules, had_rpi)


class ReadStateTest(GpioProbeTestCase):
    def state_for(self, pulled_up, pulled_down):
        self.gpio.input.side_effect = [pulled_up, pulled_down]
        return self.probe.read_state(7)

    def test_floating_when_reading_follows_pull_resistor(self):
        self.assertEqual(self.state_for(1, 0), "FLOATING")

    def test_vcc_when_high_with_both_pulls(self):
        self.assertEqual(self.state_for(1, 1), "VCC")

    def test_gnd_when_low_with_both_pulls(self):
        self.assertEqual(self.state_for(0, 0), "GND")

    def test_indeterminate_when_reading_is_inverted(self):
        self.assertEqual(
            self.state_for(0, 1), "INDETERMINATE (pull-up=0, pull-down=1)"
        )

    def test_pull_up_is_configured_before_pull_down(self):
        self.gpio.input.side_effect = [1, 0]
        self.probe.read_state(7)

        self.assertEqual(
            self.gpio.setup.call_args_list,
            [
                mock.call(7, "IN", pull_up_down="PUD_UP"),
                mock.call(7, "IN", pull_up_down="PUD_DOWN"),
            ],
        )
        self.assertEqual(self.sleep.call_count, 2)


class DriveTest(GpioProbeTestCase):
    def test_drive_high_sets_pin_output_high_then_idles(self):
        self.sleep_then_interrupt(2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(KeyboardInterrupt):
            self.probe.drive(5, "high", 0.25)

        self.gpio.setup.assert_called_once_with(5, "OUT")
        self.gpio.output.assert_called_once_with(5, 1)
        self.assertIn("HIGH", out.getvalue())
        self.sleep.assert_called_with(0.25)

    def test_drive_low_sets_pin_output_low(self):
        self.sleep_then_interrupt(0)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(
            KeyboardInterrupt
        ):
            self.probe.drive(5, "low", 0.1)
        self.gpio.output.assert_called_once_with(5, 0)

    def test_toggle_alternates_starting_with_high(self):
        self.sleep_then_interrupt(2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(KeyboardInterrupt):
            self.probe.drive(5, "toggle", 0.1)

        self.assertEqual(
            self.gpio.output.call_args_list,
            [mock.call(5, 1), mock.call(5, 0), mock.call(5, 1)],
        )
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[1:], ["HIGH", "LOW", "HIGH"])


class TurnOnDisplayTest(GpioProbeTestCase):
    def test_initializes_ssd1322_and_fills_white(self):
        with mock.patch.object(self.probe, "spi") as spi, mock.patch.object(
            self.probe, "ssd1322"
        ) as ssd1322, mock.patch.object(self.probe, "canvas") as canvas:
            device = self.probe.turn_on_display()

        spi.assert_called_once_with(device=0, port=0, bus_speed_hz=16000000)
        ssd1322.assert_called_once_with(serial_interface=spi.return_value)
        device.contrast.assert_called_once_with(255)
        draw = canvas.return_value.__enter__.return_value
        draw.rectangle.assert_called_once_with(
            device.bounding_box, outline="white", fill="white"
        )
        self.assertIs(device, ssd1322.return_value)


class MainTest(GpioProbeTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(self.probe, "turn_on_display")
        self.turn_on_display = patcher.start()
        self.addCleanup(patcher.stop)

    def test_probe_mode_prints_state_changes_only(self):
        states = iter(["FLOATING", "FLOATING", "VCC"])

        def fake_read(pin):
            try:
                return next(states)
            except StopIteration:
                raise KeyboardInterrupt

        with mock.patch.object(self.probe, "read_state", side_effect=fake_read):
            out = self.run_main("17")

        lines = out.splitlines()
        self.assertEqual(lines[-2:], ["FLOATING", "VCC"])
        self.assertEqual(lines.count("FLOATING"), 1)
        self.gpio.setmode.assert_called_once_with("BCM")
        self.gpio.cleanup.assert_called_once_with(17)

    def test_display_is_turned_on_by_default(self):
        with mock.patch.object(self.probe, "read_state", side_effect=KeyboardInterrupt):
            out = self.run_main("17")
        self.turn_on_display.assert_called_once_with()
        self.assertIn("Display initialized", out)

    def test_no_display_flag_skips_display(self):
        with mock.patch.object(self.probe, "read_state", side_effect=KeyboardInterrupt):
            self.run_main("17", "--no-display")
        self.turn_on_display.assert_not_called()

    def test_display_failure_is_reported_but_probing_continues(self):
        self.turn_on_display.side_effect = RuntimeError("no spi")
        with mock.patch.object(
            self.probe, "read_state", side_effect=KeyboardInterrupt
        ) as read_state:
            out = self.run_main("17")
        self.assertIn("Display init failed: no spi", out)
        read_state.assert_called_once_with(17)

    def test_drive_mode_skips_display_and_delegates_to_drive(self):
        with mock.patch.object(self.probe, "drive") as drive:
            self.run_main("22", "--drive", "toggle", "--interval", "2")
        self.turn_on_display.assert_not_called()
        drive.assert_called_once_with(22, "toggle", 2.0)
        self.gpio.cleanup.assert_called_once_with(22)

    def test_cleanup_runs_even_on_unexpected_error(self):
        with mock.patch.object(self.probe, "read_state", side_effect=StopLoop):
            with self.assertRaises(StopLoop):
                self.run_main("3", "--no-display")
        self.gpio.cleanup.assert_called_once_with(3)

    def test_default_interval_is_half_a_second(self):
        self.sleep_then_interrupt(0)
        with mock.patch.object(self.probe, "read_state", return_value="GND"):
            self.run_main("3", "--no-display")
        self.sleep.assert_called_with(0.5)

    def test_missing_pin_argument_exits_with_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                self.run_main()
        self.assertEqual(ctx.exception.code, 2)

    def test_invalid_drive_mode_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_main("3", "--drive", "sideways")


if __name__ == "__main__":
    unittest.main()
