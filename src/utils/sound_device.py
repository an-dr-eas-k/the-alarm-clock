import logging
import alsaaudio
from resources import resources
from utils.singleton import singleton

logger = logging.getLogger("tac.sound_device")

@singleton
class SoundDevice:

	sound_device_id: int = None
	mixer_control_id: str = None
	mixer: alsaaudio.Mixer = None

	def __init__(self, mixer_devices: list[str] = None):
		if (mixer_devices is None):
			mixer_devices = resources.valid_mixer_device_simple_control_names
		if (self.mixer_control_id is not None and self.sound_device_id is not None):
			return
		
		self.mixer = self.get_mixer(mixer_devices)
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
		self.debug_info()

		for putative_mixer in valid_mixers:	
			try:
				return alsaaudio.Mixer(putative_mixer)
			except alsaaudio.ALSAAudioError:
				pass

	def debug_info(self):
		logger.info("installed cards: %s", ", ".join(alsaaudio.cards()))
		for pcm in alsaaudio.pcms():
			try:
				logger.info("pcm %s mixers: %s", pcm, ", ".join(alsaaudio.mixers(device=pcm)))
			except:
				logger.debug("pcm %s mixers: %s", pcm, "none")
