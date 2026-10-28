import importlib
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

from dependency_injector import providers

from core.domain.model import AlarmClockContext, Config, PlaybackContent
from core.infrastructure.event_bus import EventBus

logging.getLogger("tac").addHandler(logging.NullHandler())

di_container = None


def setUpModule():
    """The module pings the network and parses sys.argv at import time.

    It must be (re)imported under our mocks: another test module may already
    have imported it earlier (e.g. via app_clock) with different sys.argv /
    ping results baked into its eagerly-evaluated provider definitions, and a
    plain `import` would then just return that stale cached module.
    """
    global di_container
    completed_ping = mock.MagicMock(returncode=1)
    with mock.patch.object(sys, "argv", ["clock", "--software"]):
        with mock.patch("subprocess.run", return_value=completed_ping):
            import core.application.di_container as module

            di_container = importlib.reload(module)


class DIContainerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            di_container, "config_file", os.path.join(self.tmp.name, "config.json")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        argv_patcher = mock.patch.object(sys, "argv", ["clock", "--software"])
        argv_patcher.start()
        self.addCleanup(argv_patcher.stop)

        self.container = di_container.DIContainer()
        self.sound_device = mock.MagicMock()
        self.sound_device.get_system_volume.return_value = 0.5
        self.gpio_manager = mock.MagicMock()
        self.i2c_manager = mock.MagicMock(i2c=None)
        self.scheduler = mock.MagicMock()
        self.display = mock.MagicMock()
        self.container.sound_device.override(providers.Object(self.sound_device))
        self.container.gpio_manager.override(providers.Object(self.gpio_manager))
        self.container.i2c_manager.override(providers.Object(self.i2c_manager))
        self.container.vlc_instance.override(providers.Object(mock.MagicMock()))
        self.container.scheduler_service.override(providers.Object(self.scheduler))
        self.container.display.override(providers.Object(self.display))
        self.addCleanup(self.shutdown_executor)

    def shutdown_executor(self):
        self.container.executor().shutdown(wait=False)


class SharedSingletonTests(DIContainerTestCase):
    def test_event_bus_is_a_shared_singleton(self):
        bus = self.container.event_bus()
        self.assertIsInstance(bus, EventBus)
        self.assertIs(self.container.event_bus(), bus)

    def test_executor_is_shared_with_event_bus(self):
        self.assertIs(self.container.event_bus()._executor, self.container.executor())

    def test_config_uses_defaults_when_no_config_file_exists(self):
        config = self.container.config()
        self.assertIsInstance(config, Config)
        self.assertIs(config.event_bus, self.container.event_bus())
        self.assertEqual(config.alarm_definitions, [])

    def test_config_is_loaded_from_existing_config_file(self):
        stored = Config(self.container.event_bus())
        stored.alarm_duration_in_mins = 17
        with open(di_container.config_file, "w") as f:
            f.write(stored.serialize())
        config = self.container.config()
        self.assertEqual(config.alarm_duration_in_mins, 17)

    def test_alarm_clock_context_wraps_the_shared_config(self):
        context = self.container.alarm_clock_context()
        self.assertIsInstance(context, AlarmClockContext)
        self.assertIs(context.config, self.container.config())
        self.assertFalse(context.environment.is_online)

    def test_command_line_arguments_enable_software_mode(self):
        self.assertTrue(self.container.argument_args().software)
        self.assertTrue(self.container.os_interaction().software_mode)

    def test_argument_parser_understands_software_flag(self):
        parser = di_container.DIContainer.create_argument_parser()
        self.assertTrue(parser.parse_args(["-s"]).software)
        self.assertTrue(parser.parse_args(["--software"]).software)
        self.assertFalse(parser.parse_args([]).software)


class ServiceWiringTests(DIContainerTestCase):
    def test_playback_content_uses_overridden_sound_device(self):
        playback = self.container.playback_content()
        self.assertIsInstance(playback, PlaybackContent)
        self.assertIs(playback.sound_device, self.sound_device)
        self.sound_device.set_system_volume.assert_called_with(
            self.container.config().default_volume
        )

    def test_alarm_audio_service_receives_shared_collaborators(self):
        service = self.container.alarm_audio_service()
        self.assertIs(service.event_bus, self.container.event_bus())
        self.assertIs(service.playback_content, self.container.playback_content())
        self.assertIs(service.display_content, self.container.display_content())
        self.assertIs(service.scheduler_service, self.scheduler)
        self.assertIs(service.alarm_clock_context, self.container.alarm_clock_context())
        self.assertIs(service.os_interaction, self.container.os_interaction())
        self.assertIs(self.container.alarm_audio_service(), service)

    def test_system_service_registers_its_scheduler_jobs(self):
        service = self.container.system_service()
        self.assertIs(service.scheduler_service, self.scheduler)
        self.assertIs(service.alarm_clock_context, self.container.alarm_clock_context())
        self.assertTrue(self.scheduler.add_job.called)

    def test_brightness_sensor_survives_missing_i2c_bus(self):
        sensor = self.container.brightness_sensor()
        self.assertEqual(sensor.get_raw_lux(), 10000)

    def test_domain_and_interface_providers_resolve(self):
        coordinator = self.container.mode_coordinator()
        handler = self.container.hardware_input_handler()
        self.assertIs(handler.mode_coordinator, coordinator)
        self.assertIs(coordinator.event_bus, self.container.event_bus())
        self.assertIsNotNone(self.container.persistence())
        self.assertIsNotNone(self.container.speaker())

    def test_gpio_input_manager_registers_callbacks_on_gpio_manager(self):
        manager = self.container.gpio_input_manager()
        self.assertIs(manager.gpio_manager, self.gpio_manager)
        self.assertTrue(self.gpio_manager.add_callback.called)
        self.gpio_manager.setup.assert_called_once_with()

    def test_api_is_wired_with_unencrypted_software_mode(self):
        api = self.container.api()
        self.assertFalse(api.encrypted)
        self.assertIs(api.alarm_audio_service, self.container.alarm_audio_service())
        self.assertIs(api.system_service, self.container.system_service())
        self.assertIs(api.display, self.display)
        self.assertIs(api.event_bus, self.container.event_bus())

    def test_real_scheduler_service_provider_creates_started_scheduler(self):
        container = di_container.DIContainer()
        self.addCleanup(container.executor().shutdown, wait=False)
        scheduler = container.scheduler_service()
        self.addCleanup(scheduler.shutdown)
        self.assertTrue(scheduler.scheduler.running)
        self.assertIs(scheduler.event_bus, container.event_bus())


if __name__ == "__main__":
    unittest.main()
