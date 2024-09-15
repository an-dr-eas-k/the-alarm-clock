import logging
import os
import subprocess

logger = logging.getLogger("tac.os")


def is_ping_successful(hostname):
    result = subprocess.run(
        ["ping", "-c", "1", hostname],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def restart_spotify_daemon():
    logger.info("restarting spotify daemon")
    os.system("sudo systemctl restart raspotify.service")


def reboot_system():
    logger.info("rebooting system")
    os.system("sudo reboot")


def shutdown_system():
    logger.info("shutting down system")
    os.system("sudo shutdown -h now")
