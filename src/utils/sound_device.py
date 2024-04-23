import logging
import alsaaudio
from resources import resources
from utils.singleton import singleton

logger = logging.getLogger("tac.sound_device")

class SoundDevice:

	mixer: alsaaudio.Mixer = None

	def __init__(self, control: str, device: str ):
		if self.mixer is not None:
			return
		
		self.control = control
		self.device = device
		self.mixer = self.get_mixer(control, device)
		pass

	def get_system_volume(self) -> float:
		volumes = self.mixer.getvolume()
		volume = sum(volumes) / len(volumes) /100 if len(volumes) > 0 else 0 
		logger.debug(f"volume is %s on %s:%s", volume, self.mixer.cardname(), self.mixer.mixer())
		return volume

	def set_system_volume(self, newVolume: float):
		logger.debug("setting %s:%s volume to %s" , self.mixer.cardname(), self.mixer.mixer(), newVolume)
		self.mixer.setvolume(int(newVolume * 100), units=alsaaudio.VOLUME_UNITS_PERCENTAGE)
		

	def get_mixer(self, control="Master", device = "default"):
		self.debug_info()
		return alsaaudio.Mixer(control=control, device=device)

	def get_controls_settings(self):
		settings = {}
		for control in alsaaudio.mixers(device=self.device):
			settings[control] = alsaaudio.Mixer(control=control, device=self.device).getvolume()

		return settings

	def set_controls_settings(self, settings):
		for control in settings.keys():
			for channel in range(len(settings[control])):
				alsaaudio.Mixer(control=control, device=self.device).setvolume(settings[control][channel], channel=channel)

	def debug_info(self):
		logger.info("installed cards: %s", ", ".join(alsaaudio.cards()))
		for pcm in alsaaudio.pcms():
			try:
				logger.info("pcm %s mixers: %s", pcm, ", ".join(alsaaudio.mixers(device=pcm)))
			except:
				logger.debug("pcm %s mixers: %s", pcm, "none")

@singleton
class TACSoundDevice(SoundDevice):
	def __init__(self):
		self.init_mixer(resources.valid_mixer_device_simple_control_names)

	def init_mixer(self, valid_mixers: list[str]):
		for mixer in valid_mixers:
			try:
				self.mixer = self.get_mixer(mixer)
				return
			except alsaaudio.ALSAAudioError:
				pass
		raise Exception("no valid mixer found")