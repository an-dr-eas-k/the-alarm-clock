
from domain import PlaybackContent, Observation, Observer
from gpiozero import DigitalOutputDevice
import logging

audio_mute_pin_id = 22

class GeneralPurposeOutput(Observer):

	audio_unmute_pin: DigitalOutputDevice

	def __init__(self):
		try:
			self.audio_unmute_pin = DigitalOutputDevice(audio_mute_pin_id)
		except:
			logging.warning("audio unmute pin not available")
			self.audio_unmute_pin = None

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, PlaybackContent):
			self.update_from_playback_content(observation, observation.observable)

	def update_from_playback_content(self, observation: Observation, playback_content: PlaybackContent):
		if self.audio_unmute_pin is None:
			return
		if observation.property_name == 'is_streaming':
			if playback_content.is_streaming:
				logging.info('unmuting audio on pin %s', audio_mute_pin_id)
				self.audio_unmute_pin.on()
			else:
				self.audio_unmute_pin.off()

