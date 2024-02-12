
from http.client import HTTPResponse
import json
import logging
import subprocess
import traceback
from urllib.request import Request, urlopen
from spotify.sync import Client
from spotify.models.track import Track

from domain import LibreSpotifyEvent, SpotifyAudioEffect, SpotifyTrack
from utils.observer import Observation, Observer


def is_ping_successful(hostname):
	result = subprocess.run(
		["ping", "-c", "1", hostname], 
		stdout=subprocess.DEVNULL, 
		stderr=subprocess.DEVNULL)
	return result.returncode == 0

def is_internet_available():
	return is_ping_successful("8.8.8.8")

def json_api(url, headers = {'Content-Type': 'application/json'}, data_bytes = None):
	try:
		request = Request(url, headers=headers, data=data_bytes)
		response: HTTPResponse = urlopen(request)
		return_code = response.getcode()
	except:
		logging.error("Error calling url %s. %s", url, traceback.format_exc())
		return False

	if return_code != 200:
		logging.error("Error calling url %s. status code: %s, response: %s", url, return_code, response.read())
		return False

	json.load(response)

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
		track: Track = Client(self.client_id, self.client_secret).get_track(track_id)
		return "%s - %s" % (track.name,",".join([a.name for a in track.artists]))

