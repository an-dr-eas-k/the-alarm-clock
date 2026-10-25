import json
import logging
import logging.handlers
import os
import queue
import unittest
from unittest import mock

from resources import resources
from resources.resources import AutoStartQueueListener, init_logging


class ResourcePathsTest(unittest.TestCase):
    def test_resources_dir_is_this_package_directory(self):
        self.assertTrue(os.path.isdir(resources.resources_dir))
        self.assertTrue(
            os.path.isfile(os.path.join(resources.resources_dir, "resources.py"))
        )

    def test_app_dir_is_parent_of_resources_dir(self):
        self.assertEqual(
            resources.app_dir,
            os.path.dirname(resources.resources_dir),
        )
        self.assertTrue(os.path.isabs(resources.app_dir))

    def test_media_sub_directories_hang_below_media_dir(self):
        self.assertEqual(resources.media_dir, os.path.join(resources.resources_dir, "media"))
        for path in (
            resources.fonts_dir,
            resources.icons_dir,
            resources.sounds_dir,
        ):
            self.assertTrue(path.startswith(resources.media_dir), path)
        self.assertEqual(resources.weather_icons_dir, f"{resources.icons_dir}/weather")
        self.assertEqual(resources.alarms_dir, f"{resources.sounds_dir}/alarms")

    def test_weather_icon_definitions_exist(self):
        self.assertTrue(
            os.path.isfile(os.path.join(resources.weather_icons_dir, "weathericons.xml"))
        )

    def test_config_file_lives_in_app_dir(self):
        self.assertEqual(resources.config_file, os.path.join(resources.app_dir, "config.json"))

    def test_webroot_file_points_into_web_interface(self):
        self.assertTrue(resources.webroot_file.endswith("template.html"))
        self.assertTrue(os.path.isfile(resources.webroot_file))

    def test_logging_configuration_file_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(resources.resources_dir, "logging.json")))


class ResourceConstantsTest(unittest.TestCase):
    def test_alarm_clock_endpoint_defaults(self):
        self.assertEqual(resources.the_alarm_clock_protocol, "https")
        self.assertEqual(resources.the_alarm_clock_hostname, "localhost")
        self.assertEqual(resources.the_alarm_clock_port, 443)

    def test_default_volume_is_a_valid_fraction(self):
        self.assertGreater(resources.default_volume, 0)
        self.assertLessEqual(resources.default_volume, 1)

    def test_mixer_names_are_preferred_digital_first(self):
        self.assertEqual(resources.valid_mixer_device_simple_control_names, ["Digital", "Master"])

    def test_librespotify_env_vars_are_unique_upper_case(self):
        names = resources.librespotify_env_vars
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n == n.upper() for n in names))
        self.assertIn("PLAYER_EVENT", names)
        self.assertIn("TRACK_ID", names)


class InitLoggingTest(unittest.TestCase):
    def test_loads_logging_json_and_passes_it_to_dict_config(self):
        with mock.patch.object(resources.logging.config, "dictConfig") as dict_config:
            init_logging()

        dict_config.assert_called_once()
        config = dict_config.call_args.args[0]
        with open(os.path.join(resources.resources_dir, "logging.json")) as f:
            self.assertEqual(config, json.load(f))
        self.assertEqual(config["version"], 1)

    def test_config_wires_queue_listener_to_this_module(self):
        with mock.patch.object(resources.logging.config, "dictConfig") as dict_config:
            init_logging()
        handler = dict_config.call_args.args[0]["handlers"]["queueHandler"]
        self.assertEqual(handler["listener"], "resources.resources.AutoStartQueueListener")

    def test_missing_file_raises(self):
        with mock.patch.object(resources, "resources_dir", "/nonexistent-dir"):
            with mock.patch.object(resources.logging.config, "dictConfig") as dict_config:
                with self.assertRaises(FileNotFoundError):
                    init_logging()
        dict_config.assert_not_called()

    def test_invalid_json_raises(self):
        with mock.patch("builtins.open", mock.mock_open(read_data="{not json")):
            with mock.patch.object(resources.logging.config, "dictConfig"):
                with self.assertRaises(json.JSONDecodeError):
                    init_logging()


class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class AutoStartQueueListenerTest(unittest.TestCase):
    def setUp(self):
        self.queue = queue.Queue()
        self.handler = CollectingHandler()
        self.listener = AutoStartQueueListener(self.queue, self.handler)
        self.addCleanup(self.stop_listener)

    def stop_listener(self):
        if self.listener._thread is not None:
            self.listener.stop()

    def test_listener_thread_is_started_on_construction(self):
        self.assertIsNotNone(self.listener._thread)
        self.assertTrue(self.listener._thread.is_alive())

    def test_records_put_on_queue_reach_handlers(self):
        logger = logging.getLogger("tests.autostart_listener")
        logger.propagate = False
        logger.setLevel(logging.INFO)
        queue_handler = logging.handlers.QueueHandler(self.queue)
        logger.addHandler(queue_handler)
        self.addCleanup(logger.removeHandler, queue_handler)

        logger.info("hello %s", "world")
        self.listener.stop()

        self.assertEqual([r.getMessage() for r in self.handler.records], ["hello world"])

    def test_stop_terminates_listener_thread(self):
        thread = self.listener._thread
        self.listener.stop()
        self.assertFalse(thread.is_alive())

    def test_respect_handler_level_flag_is_forwarded(self):
        queue_ = queue.Queue()
        listener = AutoStartQueueListener(queue_, self.handler, respect_handler_level=True)
        self.addCleanup(listener.stop)
        self.assertTrue(listener.respect_handler_level)
        self.assertEqual(listener.handlers, (self.handler,))


if __name__ == "__main__":
    unittest.main()
