import logging
import os
import traceback
import vlc
from vlc import EventType
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
	list_player: vlc.MediaListPlayer = None
	url: str

	def __init__(self, url: str, error_callback = None):
		self.url = url
		self.list_player = None

		self.error_callback = lambda: threading.Thread(target=error_callback).start() if error_callback else None

	def callback_from_player(self, event: vlc.Event, *args):
		try:
			logging.debug(f'media list player callback called: {event.type}, from {args[0]}')

			if (event.type == vlc.EventType.MediaPlayerEncounteredError):
				logging.info('vlc player error')
				self.error_callback()
		except Exception as e:
			logging.error("callback error: %s", traceback.format_exc())

	def play(self):
		if (self.list_player is not None):
			return

		instance: vlc.Instance = vlc.Instance([
			"--no-video", 
			"--network-caching=3000",
			"--live-caching=3000"
		]) 

		self.list_player: vlc.MediaListPlayer = instance.media_list_player_new()
		self.list_player.set_playback_mode(vlc.PlaybackMode.loop)
		media_player: vlc.MediaPlayer = self.list_player.get_media_player()
		media_player.event_manager().event_attach(vlc.EventType.MediaPlayerEncounteredError, self.callback_from_player, "media_player")
		# media_player.audio_set_volume(10)

		media: vlc.Media = instance.media_new(self.url) 

		media_list: vlc.MediaList = instance.media_list_new([])
		self.list_player.set_media_list(media_list)
		media_list.add_media(media) 

		self.list_player.play()
		logging.info('started audio %s', self.url)

	def stop(self):
		if (self.list_player is None):
			return

		self.list_player.stop()
		self.list_player = None
		logging.info(f'stopped audio')

class Speaker(Observer):
	media_player: MediaPlayer = None
	fallback_player_proc: subprocess.Popen = None

	def __init__(self, audio_state: AudioDefinition, config: Config) -> None:
		self.threadLock = threading.Lock()
		self.audio_state = audio_state
		self.config = config
		self.audio_state.attach(self)

	def update(self, observation: Observation):
		super().update(observation)
		if not isinstance(observation.observable, AudioDefinition):
			return

		if (observation.property_name == 'volume'):
			self.adjust_volume(observation.observable.volume)
		elif (observation.property_name == 'is_streaming'):
			self.adjust_streaming(observation.observable.is_streaming)
		elif (observation.property_name == 'audio_effect'):
			self.adjust_effect()

	def adjust_effect(self):
			if self.audio_state.is_streaming:
				self.adjust_streaming(False)
				self.adjust_streaming(True)

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
			self.startStreaming(self.audio_state.audio_effect)
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
		if not self.audio_state.audio_effect.guaranteed:
			return

		if isinstance(self.audio_state.audio_effect, OfflineAlarmEffect):
			self.system_beep() 
			return

		logging.info("starting offline fallback playback")
		self.audio_state.is_streaming = False
		self.audio_state.audio_effect = self.config.get_offline_alarm_effect()
		self.audio_state.is_streaming = True
	
	def startStreaming(self, audio_effect: AudioEffect):
		try:
			self.stopStreaming()
			self.media_player = self.get_player(audio_effect)
			self.media_player.play()
		except Exception as e:
			self.handle_player_error()
	
	def system_beep(self):
		self.adjust_streaming(False)
		logging.info("starting alternative fallback player")
		# self.fallback_player_proc = subprocess.Popen(['speaker-test', '-t', 'sine', '-c', '2', '-f', '1000', '-l', '0', '-p', '23', '-S', '80'])
		self.fallback_player_proc = subprocess.Popen(['ogg123', '-r', os.path.join(alarms_dir, 'fallback', 'Timer.ogg')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

	def stopStreaming(self):
		if self.fallback_player_proc is not None:
			self.fallback_player_proc.kill()
			logging.info('killed fallback player')
		self.fallback_player_proc = None		

		if self.media_player is not None:
			self.media_player.stop()
		self.media_player = None


def main():
		c = Config()
		c.offline_alarm = AudioStream(stream_name='Offline Alarm', stream_url='Enchantment.ogg')
		a = AudioDefinition()
		a.audio_effect = StreamAudioEffect(
			guaranteed=True, 
			volume=0.5,
			stream_definition=AudioStream(stream_name="test", stream_url='fahttps://streams.br.de/bayern2sued_2.m3u'))
			# stream_definition=c.get_offline_alarm_effect().stream_definition)
		s = Speaker(a, c)
		s.adjust_streaming(True)
		time.sleep(8)
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