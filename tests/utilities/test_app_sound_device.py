import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import app_sound_device
from app_sound_device import SoundDeviceApp


def build_app(*argv):
    with mock.patch.object(sys, "argv", ["sound", *argv]):
        return SoundDeviceApp()


class ArgumentParsingTest(unittest.TestCase):
    def test_defaults(self):
        args = build_app().args
        self.assertEqual((args.device, args.action, args.file), ("default", "get", None))

    def test_all_options(self):
        args = build_app("-D", "hw:1", "-a", "set", "-f", "x.json").args
        self.assertEqual((args.device, args.action, args.file), ("hw:1", "set", "x.json"))

    def test_long_options(self):
        args = build_app("--device", "hw:2", "--action", "get", "--file", "y").args
        self.assertEqual((args.device, args.action, args.file), ("hw:2", "get", "y"))

    def test_invalid_action_exits(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_app("-a", "delete")


class GoTest(unittest.TestCase):
    SETTINGS = {"Master": [30, 30], "PCM": [80]}

    def setUp(self):
        patcher = mock.patch.object(app_sound_device, "SoundDevice")
        self.device_class = patcher.start()
        self.addCleanup(patcher.stop)
        self.device = self.device_class.return_value
        self.device.get_controls_settings.return_value = self.SETTINGS
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "settings.json")

    def test_sound_device_is_created_for_requested_device(self):
        with contextlib.redirect_stdout(io.StringIO()):
            build_app("-D", "hw:3").go()
        self.device_class.assert_called_once_with(device="hw:3")

    def test_get_without_file_prints_json_to_stdout(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            build_app().go()
        self.assertEqual(json.loads(out.getvalue()), self.SETTINGS)

    def test_get_with_file_writes_json_file_and_prints_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            build_app("-f", self.path).go()
        with open(self.path) as f:
            self.assertEqual(json.load(f), self.SETTINGS)
        self.assertEqual(out.getvalue(), "")

    def test_set_without_file_raises(self):
        with self.assertRaisesRegex(Exception, "no file specified"):
            build_app("-a", "set").go()
        self.device.set_controls_settings.assert_not_called()

    def test_set_applies_settings_from_file_and_logs_new_state(self):
        with open(self.path, "w") as f:
            json.dump({"Master": [10]}, f)

        with self.assertLogs("tac.app_sound_device", "INFO") as logs:
            build_app("-a", "set", "-f", self.path).go()

        self.device.set_controls_settings.assert_called_once_with({"Master": [10]})
        self.assertIn(json.dumps(self.SETTINGS), logs.output[0])

    def test_set_with_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            build_app("-a", "set", "-f", self.path).go()
        self.device.set_controls_settings.assert_not_called()

    def test_set_with_invalid_json_raises(self):
        with open(self.path, "w") as f:
            f.write("{broken")
        with self.assertRaises(json.JSONDecodeError):
            build_app("-a", "set", "-f", self.path).go()

    def test_get_roundtrips_into_set(self):
        with contextlib.redirect_stdout(io.StringIO()):
            build_app("-f", self.path).go()
        self.device.reset_mock()
        with self.assertLogs("tac.app_sound_device", "INFO"):
            build_app("-a", "set", "-f", self.path).go()
        self.device.set_controls_settings.assert_called_once_with(self.SETTINGS)


if __name__ == "__main__":
    unittest.main()
