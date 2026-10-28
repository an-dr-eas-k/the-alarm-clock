import subprocess
import unittest
from unittest import mock

from utils.os_interactions import OSInteraction

ACTIONS = [
    ("restart_spotify_daemon", "sudo systemctl restart raspotify.service"),
    ("reboot_system", "sudo reboot"),
    ("shutdown_system", "sudo shutdown -h now"),
    ("restart_networking_service", "sudo systemctl restart NetworkManager"),
    ("reset_usb_wifi_adapter", "sudo /opt/wifi-watchdog/reset-wifi-usb.sh"),
]


class PingTest(unittest.TestCase):
    def test_ping_successful_when_return_code_is_zero(self):
        with mock.patch("utils.os_interactions.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertTrue(OSInteraction(True).is_ping_successful("example.com"))

    def test_ping_unsuccessful_when_return_code_is_nonzero(self):
        with mock.patch("utils.os_interactions.subprocess.run") as run:
            run.return_value.returncode = 1
            self.assertFalse(OSInteraction(True).is_ping_successful("example.com"))

    def test_ping_command_line_and_timeout(self):
        with mock.patch("utils.os_interactions.subprocess.run") as run:
            run.return_value.returncode = 0
            OSInteraction(True).is_ping_successful("example.com")

        run.assert_called_once_with(
            ["ping", "-c", "1", "-W", "5", "example.com"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )

    def test_ping_timeout_propagates(self):
        with mock.patch(
            "utils.os_interactions.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ping", 10),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                OSInteraction(True).is_ping_successful("example.com")

    def test_internet_available_pings_google_dns(self):
        osi = OSInteraction(True)
        with mock.patch.object(osi, "is_ping_successful", return_value=True) as ping:
            self.assertTrue(osi.is_internet_available())
        ping.assert_called_once_with("8.8.8.8")

    def test_internet_unavailable_when_ping_fails(self):
        osi = OSInteraction(True)
        with mock.patch.object(osi, "is_ping_successful", return_value=False):
            self.assertFalse(osi.is_internet_available())


class SystemActionsTest(unittest.TestCase):
    def test_software_mode_is_stored(self):
        self.assertTrue(OSInteraction(True).software_mode)
        self.assertFalse(OSInteraction(False).software_mode)

    def test_software_mode_skips_every_action(self):
        osi = OSInteraction(True)
        for method, _ in ACTIONS:
            with self.subTest(method=method):
                with mock.patch("utils.os_interactions.os.system") as system:
                    getattr(osi, method)()
                system.assert_not_called()

    def test_hardware_mode_runs_expected_command(self):
        osi = OSInteraction(False)
        for method, command in ACTIONS:
            with self.subTest(method=method):
                with mock.patch("utils.os_interactions.os.system") as system:
                    getattr(osi, method)()
                system.assert_called_once_with(command)

    def test_actions_never_spawn_real_subprocesses_when_mocked(self):
        osi = OSInteraction(False)
        with mock.patch("utils.os_interactions.os.system") as system, mock.patch(
            "utils.os_interactions.subprocess.run"
        ) as run:
            for method, _ in ACTIONS:
                getattr(osi, method)()
        self.assertEqual(system.call_count, len(ACTIONS))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
