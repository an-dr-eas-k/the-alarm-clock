import logging
import os
import subprocess

logger = logging.getLogger("tac.os_interactions")


class OSInteraction:

    software_mode: bool = False

    def __init__(self, software_mode: bool):
        self.software_mode = software_mode

    def is_internet_available(self):
        return self.is_ping_successful("8.8.8.8")

    def is_ping_successful(self, hostname):
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "5", hostname],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return result.returncode == 0

    def restart_spotify_daemon(self):
        if self.software_mode:
            logger.info("software mode - skipping spotify daemon restart")
            return
        logger.info("restarting spotify daemon")
        os.system("sudo systemctl restart raspotify.service")

    def reboot_system(self):
        if self.software_mode:
            logger.info("software mode - skipping system reboot")
            return
        logger.info("rebooting system")
        os.system("sudo reboot")

    def shutdown_system(self):
        if self.software_mode:
            logger.info("software mode - skipping system shutdown")
            return
        logger.info("shutting down system")
        os.system("sudo shutdown -h now")

    def restart_networking_service(self):
        if self.software_mode:
            logger.info("software mode - skipping networking service restart")
            return
        logger.info("restarting networking service")
        os.system("sudo systemctl restart NetworkManager")

    def reset_usb_wifi_adapter(self):
        if self.software_mode:
            logger.info("software mode - skipping USB WiFi adapter reset")
            return
        logger.info("resetting USB WiFi adapter")
        os.system("sudo /opt/wifi-watchdog/reset-wifi-usb.sh")
