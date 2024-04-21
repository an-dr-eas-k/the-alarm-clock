import logging
import os
import re
import subprocess
import alsaaudio
from resources.resources import valid_mixer_device_simple_control_names as valid_mixers
from resources.resources import valid_sound_card_pattern as valid_cards
from utils.singleton import singleton

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

@singleton
class SoundDevice:

	sound_card_id: int = None
	mixer_control_name: str = None

	def __init__(self):
		if (self.mixer_control_name is not None and self.sound_card_id is not None):
			return
		
		alsaaudio
		self.sound_card_id = self.get_system_sound_card_id(valid_cards)
		self.mixer_control_name = self.get_system_volume_control_name(self.sound_card_id, valid_mixers)

	def get_system_volume(self) -> float:
		logger.debug("getting system volume")
		card_id = self.sound_card_id
		control_name = self.mixer_control_name
		lines = subprocess \
			.check_output(["amixer", "sget", "-c", card_id, control_name]) \
			.decode("utf-8") \
			.splitlines()
		pattern = r"\[(\d+)%\]"
		volumes = [ float(re.search(pattern, line).group(1)) for line in lines if re.search(pattern, line)]
		volume = sum(volumes) / len(volumes) /100 if len(volumes) > 0 else 0 
		logger.debug(f"volume is %s", volume)
		return volume

	def set_system_volume(self, newVolume: float):
		logger.debug("setting system volume to %s" % newVolume)
		card_id = self.sound_card_id
		control_name = self.mixer_control_name
		subprocess.call(["amixer", "sset", "-c", card_id, control_name, f"{newVolume * 100}%"], stdout=subprocess.DEVNULL)


	def get_system_sound_card_id(self,sound_card_patterns: list[str]):
		aplay_pattern = rf"^card (\d+):"
		output = subprocess.check_output(['aplay', '-l']).decode('utf-8')

		lines = output.split('\n')

		for line in lines:
			for sound_card_pattern in sound_card_patterns:
				if re.search(sound_card_pattern, line):
					card_id = re.search(aplay_pattern, line).group(1)
					logger.debug(f"sound card id: {card_id}")
					return card_id

		return None

	def get_system_volume_control_name(self, sound_card_id, valid_control_names):
		output = subprocess.check_output(['amixer', '-c', sound_card_id, 'scontrols']).decode('utf-8')

		lines = output.split('\n')

		for line in lines:
			for valid_control_name in valid_control_names:
				if valid_control_name in line:
					control_name = valid_control_name
					logger.debug(f"volume mixer control name: {control_name}")
					return control_name

		return None

	def get_system_sound_card_id_deprecated(self):
		pattern = rf"^card (\d+):"
		output = subprocess.check_output(["aplay", "-l"]).decode().splitlines()
		sound_card_id = next(re.search(pattern, line).group(1) for line in output if any([re.search(pattern_entry, line) for pattern_entry in valid_cards]))
		logger.debug(f"sound card id: {sound_card_id}")
		return sound_card_id

	def get_system_volume_control_name_deprecated(sound_card_id: int):
		pattern = r"^Simple.+'(.+)',\d+$"
		output = subprocess.check_output(["amixer", "scontrols", "-c", sound_card_id]).decode()
		available_mixers = [re.search(pattern, line).group(1) for line in output.splitlines() if line.startswith("Simple")]
		control_name = next((control_name for control_name in available_mixers if control_name in valid_mixers), None)
		logger.debug(f"volume mixer control name: {control_name}")
		return control_name
