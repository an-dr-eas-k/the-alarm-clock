from dataclasses import dataclass
from datetime import  date, time, timedelta
from apscheduler.job import Job
from enum import Enum
import logging

import jsonpickle
from apscheduler.triggers.cron import CronTrigger

from utils.observer import Observable, Observation, Observer
from utils.geolocation import GeoLocation, Weather

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


class Mode(Enum):
	Boot = 1
	PreAlarm = 2
	Alarm = 3

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

class AudioStream:
	id: int
	stream_name: str
	stream_url: str

class AudioEffect:
	volume: float

@dataclass
class InternetRadio(AudioEffect):
	stream_definition: AudioStream = None

@dataclass
class Spotify(AudioEffect):
	play_id: str

class AlarmDefinition:
	id: int
	hour: int
	min: int
	weekdays: []
	date: date
	alarm_name: str
	is_active: bool
	visual_effect: VisualEffect
	audio_effect: AudioEffect

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

	def set_future_date(self, hour, minute):
		now = GeoLocation().now()
		target = now.replace(hour=hour, minute=minute)
		if target < now:
				target = target + timedelta(days=1)
		self.date = target.date()

	def is_one_time(self) -> bool:
		return self.date is not None

class AudioDefinition(Observable):

	@property
	def audio_effect(self) -> AudioEffect:
		return self._audio_effect

	@audio_effect.setter
	def audio_effect(self, value: AudioEffect):
		self._audio_effect = value
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

	def __init__(self):
		super().__init__()
		self.audio_effect = None
		self.volume = 0.8
		self.is_streaming = False

	def increase_volume(self):
		self.volume = min(self.volume + 0.05, 1.0)

	def decrease_volume(self):
		self.volume = max(self.volume - 0.05, 0.0)

	def toggle_stream(self):
		self.is_streaming = not self.is_streaming
	
class Config(Observable):

	_alarm_definitions: [] = []
	_audio_streams: [] = []
	dwd_station_id: str = None

	@property
	def alarm_definitions(self) -> []:
		return self._alarm_definitions

	def append_item_with_id(item_with_id, list) -> []:
		Config.assure_item_id(item_with_id, list)
		list.append(item_with_id)
		return sorted(list, key=lambda x: x.id)

	def assure_item_id(item_with_id, list):
		if not hasattr(item_with_id, 'id') or item_with_id.id is None:
			item_with_id.id = Config.get_next_id(list)

	def get_next_id(array_with_ids: []) -> int:
		return sorted(array_with_ids, key=lambda x: x.id, reverse=True)[0].id+1 if len(array_with_ids) > 0 else 1

	def add_alarm_definition(self, value: AlarmDefinition):
		self._alarm_definitions = Config.append_item_with_id(value, self._alarm_definitions)
		self.notify(property='alarm_definitions')

	def remove_alarm_definition(self, id: int):
		self._alarm_definitions = [ alarm_def for alarm_def in self._alarm_definitions if alarm_def.id != id ]
		self.notify(property='alarm_definitions')

	def get_alarm_definition(self, id: int) -> AlarmDefinition:
		return next((alarm for alarm in self._alarm_definitions if alarm.id == id), None)

	@property
	def audio_streams(self) -> []:
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
	def refresh_timeout_in_secs(self) -> int:
		return self._refresh_timeout_in_secs

	@refresh_timeout_in_secs.setter
	def refresh_timeout_in_secs(self, value: int):
		self._refresh_timeout_in_secs = value
		self.notify(property='refresh_timeout_in_secs')

	@property
	def clock_format_string(self) -> str:
		return self._clock_format_string

	@clock_format_string.setter
	def clock_format_string(self, value: str):
		self._clock_format_string = value
		self.notify(property='clock_format_string')

	@property
	def blink_segment(self) -> str:
		return self._blink_segment

	@blink_segment.setter
	def blink_segment(self, value: str):
		self._blink_segment = value
		self.notify(property='blink_segment')
	
	def __init__(self) -> None:
		super().__init__()
		self.clock_format_string = "%-H<blinkSegment>%M"
		self.blink_segment = ":"
		self.refresh_timeout_in_secs = 1

	def serialize(self):
		return jsonpickle.encode(self, indent=2)

	def deserialize(config_file):
		with open(config_file, "r") as file:
			file_contents = file.read()
			return jsonpickle.decode(file_contents)
			

class AlarmClockState(Observable):

	configuration: Config
	audio_state: AudioDefinition
	show_blink_segment: bool = True

	@property
	def clock(self) -> str:
		return self._clock

	@clock.setter
	def clock(self, value: str):
		self._clock = value
		self.notify(property='clock')

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

	def __init__(self, c: Config) -> None:
		super().__init__()
		self.configuration = c
		self.audio_state = AudioDefinition()
		self.mode = Mode.Boot
		self.geo_location = GeoLocation()
		self.is_wifi_available = True

class DisplayContent(Observable, Observer):
	is_volume_meter_shown: bool=False
	clock:str
	next_alarm_job: Job
	current_weather: Weather

	def __init__(self, state: AlarmClockState):
		super().__init__()
		self.state = state

	def get_is_wifi_available(self)-> bool:
		return self.state.is_wifi_available

	def notify(self):
		super().notify(reason="display_changed")

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, AlarmClockState):
			self.update_from_state(observation, observation.observable)

	def update_from_state(self, observation: Observation, state: AlarmClockState):
		if observation.property_name == 'clock':
			self.clock = state.clock
			self.notify()

	def hide_volume_meter(self):
		logging.info("volume bar shown: %s", False)
		self.is_volume_meter_shown = False
		self.notify()

	def show_volume_meter(self):
		logging.info("volume bar shown: %s", True)
		self.is_volume_meter_shown = True 
		self.notify()

