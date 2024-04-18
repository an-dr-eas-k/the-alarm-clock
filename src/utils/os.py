import logging
import os
import re
import subprocess
from resources.resources import mixer_device_simple_control

logger = logging.getLogger("os")

def is_ping_successful(hostname):
	result = subprocess.run(
		["ping", "-c", "1", hostname], 
		stdout=subprocess.DEVNULL, 
		stderr=subprocess.DEVNULL)
	return result.returncode == 0

def restart_spotify_daemon():
	logger.info("restarting spotify daemon")
	os.system('sudo systemctl restart raspotify.service')

def reboot_system():
	logger.info("rebooting system")
	os.system('sudo reboot')

def shutdown_system():
	logger.info("shutting down system")
	os.system('sudo shutdown -h now')

def get_system_volume(control_name: str = None) -> float:
	logger.debug("getting system volume")
	if control_name is None:
		control_name = mixer_device_simple_control
	output = subprocess.check_output(["amixer", "sget", control_name])
	lines = output.decode().splitlines()
	pattern = r"\[(\d+)%\]"
	volumes = [ float(re.search(pattern, line).group(1)) for line in lines if re.search(pattern, line)]
	volume = sum(volumes) / len(volumes) /100 if len(volumes) > 0 else 0 
	logger.debug(f"volume is %s", volume)
	return volume

def set_system_volume(newVolume: float):
	logger.debug("setting system volume to %s" % newVolume)
	control_name = mixer_device_simple_control
	subprocess.call(["amixer", "sset", control_name, f"{newVolume * 100}%"], stdout=subprocess.DEVNULL)

def get_system_volume_control_name():
	output = subprocess.check_output(["amixer", "scontrols"])
	lines = output.decode().splitlines()
	first_control_line = next(line for line in lines if line.startswith("Simple"))
	pattern = r"^Simple.+'(.+)',\d+$"
	first_control_name = re.match(pattern, first_control_line).group(1)
	logger.debug(f"volume mixer control name: {first_control_name}")
	return first_control_name
