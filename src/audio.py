import logging
import os
import vlc
import time
import subprocess 
import threading
import re

from domain import AudioDefinition, AudioEffect, AudioStream, Config, OfflineAlarmEffect, StreamAudioEffect, Observation, Observer, SpotifyAudioEffect
from utils.network import is_internet_available
from resources.resources import alarms_dir, init_logging

class MediaPlayer:

	def play(self):
		pass

	def stop(self):
		pass

class SpotifyPlayer(MediaPlayer):
	pass

class MediaListPlayer(MediaPlayer):
	vlc_player: vlc.MediaListPlayer = None
	url: str

	def __init__(self, url: str, error_callback = None):
		self.url = url
		self.error_callback = error_callback

	def callback_from_player(self, event: vlc.Event, *args):
		try:
			player_state = self.vlc_player.get_state()
			logging.debug(f'callback called: {event.type}, from {args[0]}, player state: {player_state}')
			if (player_state == vlc.State.Error):
				logging.info('vlc player error')
				self.error_callback()
		except Exception as e:
			logging.error(f'callback error: {e}')
			self.error_callback()

	def register_error_callback(self, event_manager: vlc.EventManager, called_from: str = None):
		for event_type in vlc.EventType._enum_names_:
			event_manager.event_attach(vlc.EventType(event_type), self.callback_from_player, called_from)

	def play(self):
		if (self.vlc_player is not None):
			return

		self.vlc_player = vlc.MediaListPlayer() 
		self.register_error_callback(self.vlc_player.event_manager(), "medialistplayer")

		player: vlc.Instance = vlc.Instance([
			"--no-video", 
			"--network-caching=3000",
			"--live-caching=3000",
			# "--file-logging",
      # "--logfile=/var/log/the-alarm-clock-vlc.log",
      # "--log-verbose=3"
		]) 
		self.register_error_callback(player.vlm_get_event_manager(), "instance")
		# player.log_set(self.error_callback, "log")
		media_list: vlc.MediaList = vlc.MediaList() 
		self.register_error_callback(media_list.event_manager(), "medialist")
		media: vlc.Media = player.media_new(self.url) 
		self.register_error_callback(media.event_manager(), "media")

		media_list.add_media(media) 
		self.vlc_player.set_media_list(media_list) 
		self.vlc_player.set_playback_mode(vlc.PlaybackMode.loop)
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

	def __init__(self, config: Config) -> None:
		self.threadLock = threading.Lock()
		self.config = config

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
		logging.info(f"set volume to {newVolume}")
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
	
	def get_fallback_player(self) -> MediaPlayer:
		return MediaListPlayer(self.config.get_offline_alarm_effect(), self.handle_player_error)
	
	def get_player(self, audio_effect: AudioEffect) -> MediaPlayer:
		if not is_internet_available() and audio_effect.guaranteed:
			return self.get_fallback_player()
		
		if isinstance(audio_effect, StreamAudioEffect):
			return MediaListPlayer(audio_effect.stream_definition.stream_url, self.handle_player_error)

		if isinstance(audio_effect, SpotifyAudioEffect):
			return SpotifyPlayer(audio_effect.play_id)

		raise ValueError('unknown audio effect type')

	def handle_player_error(self):
		logging.info('handling player error')
		if not self.audio_effect.guaranteed:
			return

		if isinstance(self.audio_effect.stream_definition, OfflineAlarmEffect):
			logging.info("starting system beep fallback")
			self.system_beep() 
			return

		logging.info("starting offline fallback playback")
		self.stopStreaming()
		logging.debug("stopped, restarting...")
		self.startStreaming(self.config.get_offline_alarm_effect())
	
	def startStreaming(self, audio_effect: AudioEffect):
		try:
			self.stopStreaming()
			self.media_player = self.get_player(audio_effect)
			self.media_player.play()
		except Exception as e:
			self.handle_player_error()
	
	def system_beep(self):
		self.adjust_streaming(False)
		os.system("speaker-test -t sine -c 2 -f 1000 -l 0 -p 23 -S 80")

	def stopStreaming(self):
		if self.media_player is not None:
			self.media_player.stop()

		self.media_player = None


def main():
		s = Speaker(Config())
		s.audio_effect = StreamAudioEffect(
			guaranteed=True, 
			volume=0.5,
			stream_definition=AudioStream(stream_name="test", stream_url='fahttps://streams.br.de/bayern2sued_2.m3u'))
		s.adjust_streaming(True)
		time.sleep(10)
		s.adjust_streaming(False)

def main_mlp():
	def ecb(event: vlc.Event, *args):
		try:
			print(f'callback called: {event.type}, {args}')
			foo:vlc.MediaListPlayer = args[1]
			print(foo.get_state())
		except Exception as e:
			print(f'callback error: {e}')
	mlp = MediaListPlayer("foo", ecb)
	mlp.play()

if __name__ == '__main__':
	init_logging()
	main()