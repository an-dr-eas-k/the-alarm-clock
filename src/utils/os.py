import logging
import os
import re
import subprocess
from resources.resources import valid_mixer_device_simple_control_names as valid_mixers
from resources.resources import valid_sound_card_pattern as valid_cards

logger = logging.getLogger("tac.os")

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
	card_id = get_system_sound_card_id()
	if control_name is None:
		control_name = get_system_volume_control_name(card_id)
	output = subprocess.check_output(["amixer", "sget", "-c", card_id, control_name])
	lines = output.decode().splitlines()
	pattern = r"\[(\d+)%\]"
	volumes = [ float(re.search(pattern, line).group(1)) for line in lines if re.search(pattern, line)]
	volume = sum(volumes) / len(volumes) /100 if len(volumes) > 0 else 0 
	logger.debug(f"volume is %s", volume)
	return volume

def set_system_volume(newVolume: float):
	logger.debug("setting system volume to %s" % newVolume)
	control_name = get_tac_volume_control()
	subprocess.call(["amixer", "sset", control_name, f"{newVolume * 100}%"], stdout=subprocess.DEVNULL)

def get_system_sound_card_id():
	pattern = rf"^card (\d+):"
	output = subprocess.check_output(["aplay", "-l"]).decode().splitlines()
	sound_card_id = next(re.search(pattern, line).group(1) for line in output if any([re.search(pattern_entry, line) for pattern_entry in valid_cards]))
	logger.debug(f"sound card id: {sound_card_id}")
	return sound_card_id

def get_tac_volume_control():
	card_id = get_system_sound_card_id()
	return get_system_volume_control_name(card_id)

def get_system_volume_control_name(sound_card_id: int):
	pattern = r"^Simple.+'(.+)',\d+$"
	output = subprocess.check_output(["amixer", "scontrols", "-c", sound_card_id]).decode()
	available_mixers = [re.search(pattern, line).group(1) for line in output.splitlines() if line.startswith("Simple")]
	control_name = next((control_name for control_name in available_mixers if control_name in valid_mixers), None)
	logger.debug(f"volume mixer control name: {control_name}")
	return control_name
