import logging
import os
import re
import subprocess
import alsaaudio
from resources import resources
from resources import resources
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

	sound_device_id: int = None
	mixer_control_id: str = None
	mixer: alsaaudio.Mixer = None

	def __init__(self):
		if (self.mixer_control_id is not None and self.sound_device_id is not None):
			return
		
		self.mixer = self.get_mixer(resources.valid_mixer_device_simple_control_names)
		pass

	def get_system_volume(self) -> float:
		logger.debug("getting system volume")
		volumes = self.mixer.getvolume()
		volume = sum(volumes) / len(volumes) /100 if len(volumes) > 0 else 0 
		logger.debug(f"volume is %s", volume)
		return volume

	def set_system_volume(self, newVolume: float):
		logger.debug("setting system volume to %s" % newVolume)
		self.mixer.setvolume(int(newVolume * 100), units=alsaaudio.VOLUME_UNITS_PERCENTAGE)
		

	def get_mixer(self, valid_mixers: list[str]):
		for putative_mixer in valid_mixers:	
			try:
				return alsaaudio.Mixer(putative_mixer)
			except alsaaudio.ALSAAudioError:
				pass