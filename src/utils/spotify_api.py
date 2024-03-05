from spotify.sync import Client
from spotify.models.track import Track

from domain import PlaybackContent, SpotifyAudioEffect
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
		if isinstance(observation.observable, PlaybackContent):
			self.update_from_playback_content(observation, observation.observable)

	def update_from_playback_content(self, observation: Observation, playback_content: PlaybackContent):
		if observation.property_name == 'audio_effect' and isinstance(playback_content.audio_effect, SpotifyAudioEffect):
			playback_content.audio_effect.attach(self)

	def update_from_spotify_audio_effect(self, observation: Observation, spotify_audio_effect: SpotifyAudioEffect):
		if observation.property_name == 'track_id':
			if spotify_audio_effect.track_id:
				spotify_audio_effect.track_name = self.to_title(spotify_audio_effect.track_id)

	def to_title(self, track_id) -> str:
		if not self.client_id:
			return "Spotify"
		track: Track = Client(self.client_id, self.client_secret).get_track(track_id)
		return "%s - %s" % (track.name,",".join([a.name for a in track.artists]))

