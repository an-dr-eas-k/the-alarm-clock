
import logging
import os
import re
import subprocess

def is_ping_successful(hostname):
	result = subprocess.run(
		["ping", "-c", "1", hostname], 
		stdout=subprocess.DEVNULL, 
		stderr=subprocess.DEVNULL)
	return result.returncode == 0

def restart_spotify_daemon():
	logging.info("restarting spotify daemon")
	os.system('sudo systemctl stop raspotify.service')
	os.system('sudo systemctl start raspotify.service')

def reboot_system():
	logging.info("rebooting system")
	os.system('sudo reboot')

def shutdown_system():
	logging.info("shutting down system")
	os.system('sudo shutdown -h now')

def get_system_volume(self) -> float:
	logging.info("getting system volume")
	control_name = get_system_volume_control_name()
	output = subprocess.check_output(["amixer", "sget", control_name])
	lines = output.decode().splitlines()
	pattern = r"\[(\d+)%\]"
	volumes = [ float(re.match(pattern, line).group(1)) for line in lines if re.match(pattern, line)]
	volume = sum(volumes) / len(volumes) if len(volumes) > 0 else 0
	logging.debug(f"volume is %s", volume)
	return volume

def set_system_volume(self, newVolume: float):
	logging.info("setting system volume to %s" % newVolume)
	control_name = get_system_volume_control_name()
	subprocess.call(["amixer", "sset", control_name, f"{newVolume * 100}%"], stdout=subprocess.DEVNULL)
	logging.info(f"set volume to {newVolume}")
	pass

def get_system_volume_control_name(self):
	output = subprocess.check_output(["amixer", "scontrols"])
	lines = output.decode().splitlines()
	first_control_line = next(line for line in lines if line.startswith("Simple"))
	pattern = r"^Simple.+'(.+)',\d+$"
	first_control_name = re.match(pattern, first_control_line).group(1)
	logging.debug(f"volume mixer control name: {first_control_name}")
	return first_control_name
