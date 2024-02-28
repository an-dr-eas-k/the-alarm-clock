
from domain import PlaybackContent, Observation, Observer
from gpiozero import DigitalOutputDevice

audio_power_pin_id = 22

class GeneralPurposeOutput(Observer):

	power_audio_pin: DigitalOutputDevice

	def __init__(self):
		self.power_audio_pin = DigitalOutputDevice(audio_power_pin_id)

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, PlaybackContent):
			self.update_from_playback_content(observation, observation.observable)

	def update_from_playback_content(self, observation: Observation, playback_content: PlaybackContent):
		if observation.property_name == 'is_streaming':
			if playback_content.is_streaming:
				self.power_audio_pin.on()
			else:
				self.power_audio_pin.off()

