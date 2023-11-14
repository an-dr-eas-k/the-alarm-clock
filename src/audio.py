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
	vlcPlayer: vlc.MediaListPlayer = None
	url: str

	def __init__(self, url: str):
		self.url = url

	def play(self):
		if (self.vlcPlayer is not None):
			return

		self.vlcPlayer = vlc.MediaListPlayer() 
	
		player = vlc.Instance() 
		media_list = vlc.MediaList() 
		media = player.media_new(self.url) 
		media_list.add_media(media) 
		self.vlcPlayer.set_media_list(media_list) 
		print(f'start audio {self.url}')
		self.vlcPlayer.play()

	def stop(self):
		if (self.vlcPlayer is None):
			return

		self.vlcPlayer.stop()
		self.vlcPlayer = None


class Speaker(Observer):
	audioEffect: AudioEffect = None

	def __init__(self) -> None:
		self.threadLock = threading.Lock()

	def notify(self, observation: Observation):
		super().notify(observation)
		if not isinstance(observation.observable, AudioDefinition):
			return

		if (observation.propertyName == 'volumeInPercent'):
			self.adjustVolume(observation.observable.volumeInPercent)
		elif (observation.propertyName == 'isStreaming'):
			self.adjustStreaming(observation.observable.isStreaming)
		elif (observation.propertyName == 'audioEffect'):
			self.audioEffect = observation.observable.audioEffect

	def adjustVolume(self, newVolumeInPercent: float):
		controlName = self.get_first_control_name()
		subprocess.call(["amixer", "sset", controlName, f"{newVolumeInPercent}%"], stdout=subprocess.DEVNULL)
		pass

	def get_first_control_name(self):
		output = subprocess.check_output(["amixer", "scontrols"])
		lines = output.decode().splitlines()
		first_control_line = next(line for line in lines if line.startswith("Simple"))
		pattern = r"^Simple.+'(\S+)',\d+$"
		first_control_name = re.match(pattern, first_control_line).group(1)
		return first_control_name


	def adjustStreaming(self, isStreaming: bool):
		self.threadLock.acquire(True)

		if (isStreaming):
			self.startStreaming(self.audioEffect)
		else:
			self.stopStreaming()

		self.threadLock.release()
	
	def startStreaming(self, audioEffect: AudioEffect):
		if isinstance(audioEffect, InternetRadio):
			self.mediaPlayer = InternetRadioPlayer(audioEffect.url)

		elif isinstance(audioEffect, Spotify):
			self.mediaPlayer = SpotifyPlayer(audioEffect.playId)
		
		self.mediaPlayer.play()

	def stopStreaming(self):
		self.mediaPlayer.stop()
		self.mediaPlayer = None


if __name__ == '__main__':
		s = Speaker()
		s.audioEffect = InternetRadio(url='https://streams.br.de/bayern2sued_2.m3u')
		s.adjustStreaming(True)
		time.sleep(100)