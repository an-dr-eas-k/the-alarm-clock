import logging
import vlc
import time
import subprocess 
import threading
import re

from domain import AudioDefinition, AudioEffect, InternetRadio, Observation, Observer, Spotify

class MediaPlayer:

	def play(self):
		pass

	def stop(self):
		pass

class SpotifyPlayer(MediaPlayer):
	pass

class InternetRadioPlayer(MediaPlayer):
	vlc_player: vlc.MediaListPlayer = None
	url: str

	def __init__(self, url: str):
		self.url = url

	def play(self):
		if (self.vlc_player is not None):
			return

		self.vlc_player = vlc.MediaListPlayer() 
	
		player = vlc.Instance([
			"--no-video", 
			"--network-caching=3000",
			"--live-caching=3000",
			# "--file-logging",
      # "--logfile=/var/log/the-alarm-clock-vlc.log",
      # "--log-verbose=3"
		]) 
		media_list = vlc.MediaList() 
		media = player.media_new(self.url) 
		media_list.add_media(media) 
		self.vlc_player.set_media_list(media_list) 
		self.vlc_player.play()
		logging.info('started audio %s', self.url)

	def stop(self):
		if (self.vlc_player is None):
			return

		self.vlc_player.stop()
		self.vlc_player = None
		logging.info(f'stopped audio')


class Speaker(Observer):
	audio_effect: AudioEffect = None
	media_player: MediaPlayer = None

	def __init__(self) -> None:
		self.threadLock = threading.Lock()

	def update(self, observation: Observation):
		super().update(observation)
		if not isinstance(observation.observable, AudioDefinition):
			return

		if (observation.property_name == 'volume'):
			self.adjust_volume(observation.observable.volume)
		elif (observation.property_name == 'is_streaming'):
			self.adjust_streaming(observation.observable.is_streaming)
		elif (observation.property_name == 'audio_effect'):
			self.audio_effect = observation.observable.audio_effect

	def adjust_volume(self, newVolume: float):
		control_name = self.get_first_control_name()
		subprocess.call(["amixer", "sset", control_name, f"{newVolume * 100}%"], stdout=subprocess.DEVNULL)
		pass

	def get_first_control_name(self):
		output = subprocess.check_output(["amixer", "scontrols"])
		lines = output.decode().splitlines()
		first_control_line = next(line for line in lines if line.startswith("Simple"))
		pattern = r"^Simple.+'(\S+)',\d+$"
		first_control_name = re.match(pattern, first_control_line).group(1)
		return first_control_name


	def adjust_streaming(self, isStreaming: bool):
		self.threadLock.acquire(True)

		if (isStreaming):
			self.startStreaming(self.audio_effect)
		else:
			self.stopStreaming()

		self.threadLock.release()
	
	def startStreaming(self, audio_effect: AudioEffect):
		if isinstance(audio_effect, InternetRadio):
			self.media_player = InternetRadioPlayer(audio_effect.url)

		elif isinstance(audio_effect, Spotify):
			self.media_player = SpotifyPlayer(audio_effect.play_id)
		
		self.media_player.play()

	def stopStreaming(self):
		if self.media_player is not None:
			self.media_player.stop()

		self.media_player = None


if __name__ == '__main__':
		s = Speaker()
		s.audio_effect = InternetRadio(url='https://streams.br.de/bayern2sued_2.m3u')
		s.adjust_streaming(True)
		time.sleep(100)