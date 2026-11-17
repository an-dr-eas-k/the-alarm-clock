import signal
import sys
import unittest
from unittest import mock

from dependency_injector import providers


def import_app_clock():
    """Importing DIContainer parses sys.argv and pings 8.8.8.8 in its class body."""
    with mock.patch.object(sys, "argv", ["app_clock.py"]), mock.patch(
        "subprocess.run"
    ) as run:
        run.return_value.returncode = 0
        import app_clock
    return app_clock


app_clock = import_app_clock()

from core.domain.events import (  # noqa: E402
    ConfigChangedEvent,
    PlaybackChangedEvent,
    StartupFinishedEvent,
)
from core.domain.model import Mode  # noqa: E402


class ClockAppTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app_clock.ClockApp()
        self.container = mock.MagicMock(name="container")
        self.app.container = self.container
        self.order = []

        for name, patcher in (
            ("signal", mock.patch.object(app_clock.signal, "signal")),
            ("io_loop", mock.patch.object(app_clock.tornado.ioloop.IOLoop, "current")),
        ):
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.io_loop.return_value.start.side_effect = lambda: self.order.append("loop")

    def set_hardware(self, on_hardware):
        self.container.argument_args.return_value.software = not on_hardware

    def run_go(self):
        with self.assertRaises(SystemExit) as ctx, self.assertLogs("tac.app_clock", "INFO"):
            self.app.go()
        return ctx.exception.code


class ConstructionTest(unittest.TestCase):
    def test_creates_di_container(self):
        app = app_clock.ClockApp()
        self.assertTrue(hasattr(app.container, "alarm_audio_service"))
        self.assertTrue(hasattr(app.container, "argument_args"))

    def test_importing_module_does_not_start_the_app(self):
        self.assertTrue(callable(app_clock.ClockApp.go))


class IsOnHardwareTest(ClockAppTestCase):
    def test_hardware_when_software_flag_not_set(self):
        self.set_hardware(True)
        self.assertTrue(self.app.is_on_hardware())

    def test_not_hardware_when_software_flag_set(self):
        self.set_hardware(False)
        self.assertFalse(self.app.is_on_hardware())


class ShutdownFunctionTest(ClockAppTestCase):
    def test_restarts_spotify_daemon_and_stops_loop(self):
        with self.assertLogs("tac.app_clock", "INFO"):
            self.app.shutdown_function()

        self.container.os_interaction.return_value.restart_spotify_daemon.assert_called_once_with()
        self.io_loop.return_value.stop.assert_called_once_with()

    def test_accepts_signal_handler_arguments(self):
        with self.assertLogs("tac.app_clock", "INFO"):
            self.app.shutdown_function(signal.SIGTERM, None)
        self.io_loop.return_value.stop.assert_called_once_with()


class GoOnHardwareTest(ClockAppTestCase):
    def setUp(self):
        super().setUp()
        self.set_hardware(True)
        self.container.alarm_audio_service.return_value.scheduler_service.shutdown.side_effect = (
            lambda: self.order.append("scheduler_shutdown")
        )

    def test_exits_with_status_zero(self):
        self.assertEqual(self.run_go(), 0)

    def test_registers_sigterm_handler(self):
        self.run_go()
        self.signal.assert_called_once_with(signal.SIGTERM, self.app.shutdown_function)

    def test_initializes_hardware_input_and_not_computer_infrastructure(self):
        with mock.patch(
            "core.infrastructure.computer_infrastructure.ComputerInfrastructure"
        ) as computer_infrastructure:
            self.run_go()

        self.container.gpio_input_manager.assert_called_once_with()
        computer_infrastructure.assert_not_called()
        self.container.brightness_sensor.override.assert_not_called()
        self.container.device.override.assert_not_called()

    def test_starts_api_and_wires_domain_and_interface_layers(self):
        self.run_go()

        self.container.persistence.assert_called_once_with()
        self.container.system_service.assert_called_once_with()
        self.container.api.return_value.start.assert_called_once_with()
        self.container.speaker.assert_called_once_with()
        self.container.hardware_input_handler.assert_called_once_with()
        context = self.container.alarm_clock_context.return_value
        self.assertIs(context.mode_coordinator, self.container.mode_coordinator.return_value)

    def test_emits_startup_events_in_order(self):
        self.run_go()

        events = [c.args[0] for c in self.container.event_bus.return_value.emit.call_args_list]
        self.assertEqual(
            [type(e) for e in events],
            [ConfigChangedEvent, PlaybackChangedEvent, StartupFinishedEvent],
        )
        self.assertIs(events[0].config, self.container.config.return_value)
        self.assertEqual(events[1].playback_mode, Mode.Idle)

    def test_starts_io_loop_after_startup_events(self):
        emit = self.container.event_bus.return_value.emit
        emit.side_effect = lambda e: self.order.append(type(e).__name__)
        self.run_go()
        self.assertEqual(
            self.order[:4],
            ["ConfigChangedEvent", "PlaybackChangedEvent", "StartupFinishedEvent", "loop"],
        )

    def test_cleans_up_hardware_after_loop_ends(self):
        self.container.mcp_manager.return_value.close.side_effect = (
            lambda: self.order.append("mcp_close")
        )
        self.container.gpio_manager.return_value.cleanup.side_effect = (
            lambda: self.order.append("gpio_cleanup")
        )
        self.run_go()

        self.assertEqual(self.order[-3:], ["scheduler_shutdown", "mcp_close", "gpio_cleanup"])
        self.assertEqual(self.order.index("loop") + 1, self.order.index("scheduler_shutdown"))


class GoInSoftwareModeTest(ClockAppTestCase):
    def setUp(self):
        super().setUp()
        self.set_hardware(False)
        patcher = mock.patch(
            "core.infrastructure.computer_infrastructure.ComputerInfrastructure"
        )
        self.computer_infrastructure = patcher.start()
        self.addCleanup(patcher.stop)
        self.ci = self.computer_infrastructure.return_value

    def test_exits_with_status_zero(self):
        self.assertEqual(self.run_go(), 0)

    def test_simulated_infrastructure_receives_shared_executor(self):
        self.run_go()
        self.computer_infrastructure.assert_called_once_with(
            executor=self.container.executor.return_value
        )

    def test_brightness_sensor_is_overridden_with_simulated_infrastructure(self):
        self.run_go()
        (override,) = self.container.brightness_sensor.override.call_args.args
        self.assertIsInstance(override, providers.Object)
        self.assertIs(override(), self.ci)

    def test_display_device_is_overridden_with_dummy_rgb_device(self):
        self.run_go()
        (override,) = self.container.device.override.call_args.args
        self.assertIsInstance(override, providers.Singleton)
        device = override()
        self.assertEqual((device.width, device.height, device.mode), (256, 64, "RGB"))

    def test_infrastructure_is_configured_with_alarm_audio_service(self):
        self.run_go()
        self.ci.configure.assert_called_once_with(
            self.container.alarm_audio_service.return_value
        )

    def test_hardware_is_not_touched_and_infrastructure_is_stopped(self):
        self.run_go()
        self.container.gpio_input_manager.assert_not_called()
        self.container.mcp_manager.assert_not_called()
        self.container.gpio_manager.assert_not_called()
        self.ci.stop.assert_called_once_with()

    def test_scheduler_is_shut_down_after_loop(self):
        scheduler = self.container.alarm_audio_service.return_value.scheduler_service
        scheduler.shutdown.side_effect = lambda: self.order.append("scheduler_shutdown")
        self.run_go()
        self.assertEqual(self.order, ["loop", "scheduler_shutdown"])

    def test_startup_events_are_emitted(self):
        self.run_go()
        emitted = self.container.event_bus.return_value.emit.call_args_list
        self.assertEqual(len(emitted), 3)


if __name__ == "__main__":
    unittest.main()
