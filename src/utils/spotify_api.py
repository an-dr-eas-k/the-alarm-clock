from spotify.sync import Client
from spotify.models.track import Track

from domain import SpotifyAudioEffect
from utils.observer import Observation, Observer
from utils.singleton import singleton

@singleton
class SpotifyApi (Observer):
	
	def __init__(self, client_id: str, client_secret: str):
		self.client_id = client_id
		self.client_secret = client_secret

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, SpotifyAudioEffect):
			self.update_from_spotify_audio_effect(observation, observation.observable)

	def update_from_spotify_audio_effect(self, observation: Observation, audio_effect: SpotifyAudioEffect):
		if observation.property_name == 'spotify_event':
			audio_effect.display_content = self.to_display_content(audio_effect.spotify_event.track_id)

	def to_display_content(self, track_id) -> str:
		if not self.client_id:
			return "spotify not configured"
		track: Track = Client(self.client_id, self.client_secret).get_track(track_id)
		return "%s - %s" % (track.name,",".join([a.name for a in track.artists]))

