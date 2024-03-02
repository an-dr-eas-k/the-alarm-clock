from dataclasses import dataclass
from datetime import date, time, timedelta
import datetime
import os
from typing import List
from apscheduler.job import Job
from enum import Enum
import logging

import jsonpickle
from apscheduler.triggers.cron import CronTrigger
from utils.extensions import get_timedelta_to_alarm

from utils.observer import Observable, Observation, Observer
from utils.geolocation import GeoLocation, Weather
from resources.resources import alarms_dir
from utils.singleton import singleton

def try_update(object, property_name: str, value: str) -> bool:
	if hasattr(object, property_name):
		attr_value = getattr(object, property_name)
		attr_type = type(attr_value)
		if attr_type == bool:
			value = value.lower() in ("yes", "true", "t", "1")
		else:
			value = attr_type(value) if len(value) > 0 else None
		if value != attr_value:
			setattr(object, property_name, value)
			if isinstance(object, Observable):
				object.notify(property=property_name)
		return True
	return False


class StreamContent:

	name: str

	def __init__(self, dict: dict):
		for key, value in dict.items():
			setattr(self, key, value)

class SpotifyAlbum(StreamContent):
	pass

class SpotifyArtist(StreamContent):
	pass

class SpotifyTrack(StreamContent):

	album: SpotifyAlbum
	artists: List[SpotifyArtist]

class LibreSpotifyEvent(StreamContent):

	player_event: str = None
	track_id: str
	old_track_id: str
	duration_ms: str
	position_ms: str
	volume: str
	sink_status: str
	home: str

	def is_playback_changed(self) -> bool:
		return self.player_event in ['preloading', 'started', 'changed', 'volume_set', 'stopped', 'paused']

	def is_playback_active(self) -> bool:
		return self.player_event in ['preloading', 'started', 'changed', 'volume_set']

	def is_playback_stopped(self) -> bool:
		return self.player_event in ['stopped', 'paused']

class Mode(Enum):
	Boot = 0
	Idle = 1
	Alarm = 2
	Music = 3

class Weekday(Enum):
	MONDAY = 1
	TUESDAY = 2
	WEDNESDAY = 3
	THURSDAY = 4
	FRIDAY = 5
	SATURDAY = 6
	SUNDAY = 7

class VisualEffect:
	pass

@dataclass
class AudioStream:
	stream_name: str
	stream_url: str
	id: int = -1

	def __str__(self):
		return f"stream_name: {self.stream_name}, stream_url: {self.stream_url}"

@dataclass
class AudioEffect:
	volume: float
	display_content: str = None

	def __str__(self):
		return f"volume: {self.volume}, display_content: {self.display_content}"

@dataclass
class StreamAudioEffect(AudioEffect):
	stream_definition: AudioStream = None

	def __str__(self):
		return f"stream_definition: {self.stream_definition} {super().__str__()}"

@singleton
@dataclass
class OfflineAlarmEffect(StreamAudioEffect):
	pass

@dataclass
class SpotifyAudioEffect(AudioEffect, Observable):
	_spotify_event = None

	@property
	def spotify_event(self) -> LibreSpotifyEvent:
		return self._spotify_event

	@spotify_event.setter
	def spotify_event(self, value: LibreSpotifyEvent):
		self._spotify_event = value
		self.notify(property='spotify_event')

	def get_display_content(self) -> str:
		return self.display_content

	def __str__(self):
		return f"spotify_event: {self.spotify_event} {super().__str__()}"



class AlarmDefinition:
	id: int
	hour: int
	min: int
	weekdays: List[Weekday]
	date: datetime
	alarm_name: str
	is_active: bool
	visual_effect: VisualEffect
	_audio_effect: AudioEffect

	def to_cron_trigger(self) -> CronTrigger:
		if (self.weekdays is not None and len(self.weekdays) > 0):
			return CronTrigger(
				day_of_week=",".join([ str(Weekday[wd].value -1) for wd in self.weekdays]),
				hour=self.hour,
				minute=self.min
			)
		elif (self.date is not None):
			return CronTrigger(
				start_date=self.date,
				end_date=self.date+timedelta(days=1),
				hour=self.hour,
				minute=self.min
			)

	def to_time_string(self) -> str:
		return time(hour=self.hour, minute=self.min).strftime("%H:%M")

	def to_weekdays_string(self) -> str:
		if self.weekdays is not None and len(self.weekdays) > 0:
			return ", ".join([ Weekday[wd].name.lower().capitalize() for wd in self.weekdays ])
		elif (self.date is not None):
			return self.date.strftime("%Y-%m-%d")

	def set_future_date(self, hour: int, minute: int):
		now = GeoLocation().now()
		target = now.replace(hour=hour, minute=minute)
		if target < now:
				target = target + timedelta(days=1)
		self.date = target.date()
		self.weekdays = None

	def is_one_time(self) -> bool:
		return self.date is not None

	@property
	def audio_effect(self) -> AudioEffect:
		return self._audio_effect

	@audio_effect.setter
	def audio_effect(self, value: AudioEffect):
		self._audio_effect = value

class Config(Observable):

	clock_format_string: str
	blink_segment: str
	offline_alarm: AudioStream
	alarm_duration_in_mins: int
	refresh_timeout_in_secs: int
	powernap_duration_in_mins: int
	default_volume: float = 0.3
	spotify_client_id: str
	spotify_client_secret: str

	_alarm_definitions: List[AlarmDefinition] = []
	_audio_streams: List[AudioStream] = []

	@property
	def alarm_definitions(self) -> List[AlarmDefinition]:
		return self._alarm_definitions

	def append_item_with_id(item_with_id, list) -> List[object]:
		Config.assure_item_id(item_with_id, list)
		list.append(item_with_id)
		return sorted(list, key=lambda x: x.id)

	def assure_item_id(item_with_id, list):
		if not hasattr(item_with_id, 'id') or item_with_id.id is None:
			item_with_id.id = Config.get_next_id(list)

	def get_next_id(array_with_ids: List[object]) -> int:
		return sorted(array_with_ids, key=lambda x: x.id, reverse=True)[0].id+1 if len(array_with_ids) > 0 else 1

	def add_alarm_definition_for_powernap(self):

		duration = GeoLocation().now() + timedelta(minutes=(1+self.powernap_duration_in_mins))
		audio_effect = StreamAudioEffect(
			stream_definition=self.audio_streams[0],
			volume=self.default_volume)

		powernap_alarm_def = AlarmDefinition()
		powernap_alarm_def.alarm_name = "Powernap"
		powernap_alarm_def.hour = duration.hour
		powernap_alarm_def.min = duration.minute
		powernap_alarm_def.is_active = True
		powernap_alarm_def.set_future_date(duration.hour, duration.minute)
		powernap_alarm_def.audio_effect = audio_effect
		powernap_alarm_def.visual_effect = None

		self.add_alarm_definition(powernap_alarm_def)


	def add_alarm_definition(self, value: AlarmDefinition):
		self._alarm_definitions = Config.append_item_with_id(value, self._alarm_definitions)
		self.notify(property='alarm_definitions')

	def remove_alarm_definition(self, id: int):
		self._alarm_definitions = [ alarm_def for alarm_def in self._alarm_definitions if alarm_def.id != id ]
		self.notify(property='alarm_definitions')

	def get_alarm_definition(self, id: int) -> AlarmDefinition:
		return next((alarm for alarm in self._alarm_definitions if alarm.id == id), None)

	@property
	def audio_streams(self) -> List[AudioStream]:
		return self._audio_streams

	def add_audio_stream(self, value: AudioStream):
		self._audio_streams = Config.append_item_with_id(value, self._audio_streams)
		self.notify(property='audio_streams')

	def get_audio_stream(self, id: int) -> AudioStream:
		return next((stream for stream in self._audio_streams if stream.id == id), None)

	def remove_audio_stream(self, id: int):
		self._audio_streams = [ stream_def for stream_def in self._audio_streams if stream_def.id != id ]
		self.notify(property='audio_streams')

	@property
	def local_alarm_file(self) -> str:
		return self.offline_alarm.stream_url

	@local_alarm_file.setter
	def local_alarm_file(self, value: str):
		self.offline_alarm = AudioStream(stream_name='Offline Alarm', stream_url=value)
		self.notify(property='blink_segment')

	def __init__(self):
		logging.debug("initializing default config")
		self.ensure_valid_config()
		super().__init__()

	def get_offline_alarm_effect(self, volume: float = default_volume) -> OfflineAlarmEffect:
		full_path = os.path.join(alarms_dir, self.offline_alarm.stream_url)
		return OfflineAlarmEffect(
			volume=volume, 
			stream_definition=AudioStream(stream_name='Offline Alarm', stream_url=full_path))

	def	ensure_valid_config(self):
		for conf_prop in ([
			dict(key='alarm_duration_in_mins', value=60), 
			dict(key='offline_alarm', value = AudioStream(stream_name='Offline Alarm', stream_url='Enchantment.ogg')),
			dict(key='clock_format_string', value='%-H<blinkSegment>%M'),
			dict(key='blink_segment', value=':'),
			dict(key='refresh_timeout_in_secs', value=1),
			dict(key='powernap_duration_in_mins', value=18),
			dict(key='spotify_client_id', value=''),
			dict(key='spotify_client_secret', value=''),
			dict(key='default_volume', value=0.3)
			]):
			if not hasattr(self, conf_prop['key']):
				logging.debug("key not found: %s, adding default value: %s", conf_prop['key'], conf_prop['value'])
				setattr(self, conf_prop['key'], conf_prop['value'])
	
	def serialize(self):
		return jsonpickle.encode(self, indent=2)

	def deserialize(config_file):
		logging.debug("initializing config from file: %s", config_file)
		with open(config_file, "r") as file:
			file_contents = file.read()
			persisted_config: Config = jsonpickle.decode(file_contents)
			persisted_config.ensure_valid_config()
			return persisted_config
			

class AlarmClockState(Observable):

	configuration: Config

	@property
	def show_blink_segment(self) -> bool:
		return self._show_blink_segment

	@show_blink_segment.setter
	def show_blink_segment(self, value: bool):
		self._show_blink_segment = value
		self.notify(property='show_blink_segment')

	@property
	def is_wifi_available(self) -> bool:
		return self._is_wifi_available

	@is_wifi_available.setter
	def is_wifi_available(self, value: bool):
		self._is_wifi_available = value
		self.notify(property='is_wifi_available')

	@property
	def is_daytime(self)-> bool:
		return self._is_daytime

	@is_daytime.setter
	def is_daytime(self, value: bool):
		self._is_daytime = value
		self.notify(property='is_daytime')
	
	@property
	def mode(self)-> Mode:
		return self._mode

	@mode.setter
	def mode(self, value: Mode):
		self._mode = value
		self.notify(property='mode')

	@property
	def spotify_event(self) -> LibreSpotifyEvent:
		return self._spotify_event

	@spotify_event.setter
	def spotify_event(self, value: LibreSpotifyEvent):
		self._spotify_event = value
		self.notify(property='spotify_event')

	def __init__(self, c: Config) -> None:
		super().__init__()
		self.configuration = c
		self.mode = Mode.Boot
		self.geo_location = GeoLocation()
		self.is_wifi_available = True
		self.show_blink_segment = True

class MediaContent(Observable, Observer):

	def __init__(self, state: AlarmClockState):
		super().__init__()
		self.state = state


class PlaybackContent(MediaContent):

	desired_audio_effect: AudioEffect

	@property
	def audio_effect(self) -> AudioEffect:
		return self._audio_effect

	@audio_effect.setter
	def audio_effect(self, value: AudioEffect):

		self._audio_effect = value
		if value is not None and value.volume != self.volume:
			self.volume = value.volume
		self.notify(property='audio_effect')

	@property
	def volume(self) -> float:
		return self._volume

	@volume.setter
	def volume(self, value: float):
		self._volume = value
		self.notify(property='volume')

	@property
	def is_streaming(self) -> str:
		return self._is_streaming

	@is_streaming.setter
	def is_streaming(self, value: bool):
		self._is_streaming = value
		self.notify(property='is_streaming')

	def __init__(self, state: AlarmClockState):
		super().__init__(state)
		self.audio_effect = None
		self.volume = 0.3
		self.is_streaming = False

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, AlarmClockState):
			self.update_from_state(observation, observation.observable)

	def update_from_state(self, observation: Observation, state: AlarmClockState):
		if observation.property_name == 'mode':
			self.toggle_stream(new_value=(state.mode in (Mode.Alarm, Mode.Music)))
		if observation.property_name == 'is_wifi_available':
			self.wifi_availability_changed(state.is_wifi_available)

	def wifi_availability_changed(self, wifi_available: bool):
		if self.state.mode == Mode.Alarm:
			if not wifi_available:
				self.audio_effect = self.state.configuration.get_offline_alarm_effect(self.volume)
			else:
				self.audio_effect = self.desired_audio_effect
		else:
			self.is_streaming = self.is_streaming and wifi_available

	def increase_volume(self):
		self.volume = min(self.volume + 0.05, 1.0)

	def decrease_volume(self):
		self.volume = max(self.volume - 0.05, 0.0)

	def toggle_stream(self, new_value: bool = None):
		self.is_streaming = new_value if new_value is not None else not self.is_streaming
	
class DisplayContent(MediaContent):
	is_volume_meter_shown: bool=False
	next_alarm_job: Job
	current_weather: Weather
	show_blink_segment: bool
	current_playback_title: str


	def __init__(self, state: AlarmClockState, playback_content: PlaybackContent):
		super().__init__(state)
		self.playback_content = playback_content

	def get_is_wifi_available(self)-> bool:
		return self.state.is_wifi_available

	def notify(self):
		super().notify(reason="display_changed")

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, AlarmClockState):
			self.update_from_state(observation, observation.observable)
		if isinstance(observation.observable, PlaybackContent):
			self.update_from_playback_content(observation, observation.observable)

	def update_from_playback_content(self, observation: Observation, playback_content: PlaybackContent):
		if observation.property_name == 'audio_effect':
			self.current_playback_title = playback_content.audio_effect.display_content


	def update_from_state(self, observation: Observation, state: AlarmClockState):
		if observation.property_name == 'show_blink_segment':
			self.show_blink_segment = state.show_blink_segment
			self.notify()

	def hide_volume_meter(self):
		logging.info("volume bar shown: %s", False)
		self.is_volume_meter_shown = False
		self.notify()

	def show_volume_meter(self):
		logging.info("volume bar shown: %s", True)
		self.is_volume_meter_shown = True 
		self.notify()

	def get_timedelta_to_alarm(self) -> timedelta:
		if self.next_alarm_job is None:
			return timedelta.max
		return get_timedelta_to_alarm(self.next_alarm_job)
	
	def get_next_alarm(self) -> datetime:
		return None if self.next_alarm_job is None else self.next_alarm_job.next_run_time

