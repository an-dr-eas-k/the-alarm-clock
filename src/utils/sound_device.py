import logging
import math
import threading
import alsaaudio
from resources import resources
from utils.singleton import singleton

logger = logging.getLogger("tac.sound_device")

class SoundDevice:

	_mixer: alsaaudio.Mixer = None

	@property
	def mixer(self) -> alsaaudio.Mixer:
		return self.get_mixer(control=self.control, device=self.device)

	def __init__(self, control="Master", device = "default"):
		self.control = control
		self.device = device

	def get_system_volume(self) -> float:
		[min_volume_db, max_volume_db] = self.mixer.getrange(units=alsaaudio.VOLUME_UNITS_DB)

		human_volume = 0
		algorithm = "cubic"
		if (min_volume_db >= max_volume_db):
			algorithm = "linear"
			[min_volume_raw, max_volume_raw] = self.mixer.getrange(units=alsaaudio.VOLUME_UNITS_RAW)
			volume_raw = self.combine_channel_values(self.mixer.getvolume(units=alsaaudio.VOLUME_UNITS_RAW))
			human_volume = self.convert_to_normalized_volume(volume_raw, min_volume_raw, max_volume_raw)
		else:
			volume_db = self.combine_channel_values(self.mixer.getvolume(units=alsaaudio.VOLUME_UNITS_DB))
			human_volume = self.convert_to_human_volume(volume_db, max_volume_db)

		logger.debug(f"human_volume is %s on %s:%s (%s)" % (human_volume, self.mixer.cardname(), self.mixer.mixer(), algorithm))
		return human_volume

	@staticmethod
	def round(value: float, multiple_of: float=0.02) -> float:
		return round(value / multiple_of) * multiple_of

	def set_system_volume(self, new_human_volume: float):
		# new_human_volume = self.round(new_human_volume)
		[min_volume_db, max_volume_db] = self.mixer.getrange(units=alsaaudio.VOLUME_UNITS_DB)
		algorithm = "cubic"

		if (min_volume_db >= max_volume_db):
			algorithm = "linear"
			[min_volume_raw, max_volume_raw] = self.mixer.getrange(units=alsaaudio.VOLUME_UNITS_RAW)
			volume_raw = self.convert_from_normalized_volume(new_human_volume, min_volume_raw, max_volume_raw)
			self.mixer.setvolume(int(volume_raw), units=alsaaudio.VOLUME_UNITS_RAW)
		else:
			volume_db = self.convert_from_human_volume(new_human_volume, min_volume_db, max_volume_db)
			self.mixer.setvolume(int(volume_db), units=alsaaudio.VOLUME_UNITS_DB)

		logger.debug("set %s:%s human_volume to %s (%s)" , self.mixer.cardname(), self.mixer.mixer(), new_human_volume, algorithm)

	def combine_channel_values(self, values):
		return sum(values) / len(values) if len(values) > 0 else 0
		
	def convert_to_human_volume(self, volume: float, max_volume: float) -> float:
		return 10 ** ((volume - max_volume) / 6000.0)

	def convert_to_normalized_volume(self, volume_raw: float, min_volume_raw: float, max_volume_raw: float) -> float:
		return (volume_raw - min_volume_raw) / (max_volume_raw - min_volume_raw)

	def convert_from_human_volume(self, human_volume: float, min_volume: float, max_volume: float) -> float:
		volume_db = min_volume

		try:
			volume_db = 6000.0 * math.log10(human_volume) + max_volume
		except:
			pass

		if (volume_db <= min_volume):
			return min_volume
		if (volume_db >= max_volume):
			return max_volume

		return volume_db

	def convert_from_normalized_volume(self, human_volume: float, min_volume: float, max_volume: float) -> float:
		volume_raw = human_volume * (max_volume - min_volume) + min_volume

		if (volume_raw <= min_volume):
			return min_volume
		if (volume_raw >= max_volume):
			return max_volume

		return volume_raw
		

	def get_mixer(self, control, device) -> alsaaudio.Mixer:

		if (self._mixer is None):
			self._mixer = alsaaudio.Mixer(control=control, device=device)

		return self._mixer

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
		self.threadLock = threading.Lock()
		self.init_mixer(resources.valid_mixer_device_simple_control_names)

	def init_mixer(self, valid_mixers: list[str], device: str = 'default'):
		self.device = device
		self.debug_info()

		self.threadLock.acquire(True)

		for mixer in valid_mixers:
			try:
				self.control = mixer
				self._mixer = self.get_mixer(control=mixer, device=device)
				break
			except alsaaudio.ALSAAudioError:
				pass

		self.threadLock.release()

		if (self._mixer is None):
			raise Exception("no valid mixer found")