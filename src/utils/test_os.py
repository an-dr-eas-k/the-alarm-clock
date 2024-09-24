import unittest
import re
import subprocess
from unittest.mock import patch
import utils.os as my_os  # To avoid conflicts with the imported os module
import logging
from resources.resources import default_volume


class TestOS(unittest.TestCase):
    @patch("subprocess.run")
    def test_is_ping_successful(self, mock_subprocess):
        mock_subprocess.return_value.returncode = 0
        result = my_os.is_ping_successful("example.com")
        self.assertTrue(result)

    @patch("logging.info")
    @patch("subprocess.check_output")
    def test_get_system_volume(self, mock_check_output, mock_logging_info):
        mock_check_output.return_value = b"Simple mixer control 'Master',0\nCapabilities: pvolume pswitch pswitch-joined\nPlayback channels: Front Left - Front Right\nLimits: Playback 0 - 65536\nMono:\nFront Left: Playback 19661 [30%] [on]\nFront Right: Playback 19661 [30%] [on]"
        volume = my_os.get_system_volume("foo")
        self.assertEqual(volume, default_volume)
        mock_logging_info.assert_called_once_with("getting system volume")
