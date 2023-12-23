from dataclasses import dataclass
from datetime import  date, time, timedelta
from enum import Enum
import logging

import jsonpickle
from apscheduler.triggers.cron import CronTrigger

from utils.observer import Observable, Observation, Observer
from utils.geolocation import GeoLocation

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

class AudioEffect:
	pass

@dataclass
class InternetRadio(AudioEffect):
	url: str

@dataclass
class Spotify(AudioEffect):
	play_id: str


class AlarmDefinition:
	hour: int
	min: int
	weekdays: []
	date: date
	alarm_name: str
	is_active: bool
	visual_effect: VisualEffect
	audio_effect: AudioEffect = InternetRadio(url='https://streams.br.de/bayern2sued_2.m3u')

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

class AudioDefinition(Observable):

	@property
	def audio_effect(self) -> str:
		return self._audio_effect

	@audio_effect.setter
	def audio_effect(self, value: AudioEffect):
		self._audio_effect = value
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
		self.audio_effect = InternetRadio(url='https://streams.br.de/bayern2sued_2.m3u')
		self.volume = 0.8
		self.is_streaming = False

	def increase_volume(self):
		self.volume = min(self.volume + 0.05, 1.0)

	def decrease_volume(self):
		self.volume = max(self.volume - 0.05, 0.0)

	def toggle_stream(self):
		self.is_streaming = not self.is_streaming
	
class Config(Observable):

	_alarm_definitions: []

	@property
	def alarm_definitions(self) -> []:
		return self._alarm_definitions

	def add_alarm_definition(self, value: AlarmDefinition):
		if any(alarm_def.alarm_name == value.alarm_name for alarm_def in self._alarm_definitions):
			raise ValueError(f"Alarm with name '{value.alarm_name}' already exists.")
		self._alarm_definitions.append(value)
		self.notify(property='alarm_definitions')

	def remove_alarm_definition(self, alarm_name: str):
		self._alarm_definitions = [ alarm_def for alarm_def in self._alarm_definitions if alarm_def.alarm_name != alarm_name ]
		self.notify(property='alarm_definitions')

	@property
	def brightness(self) -> int:
		return self._brightness

	@brightness.setter
	def brightness(self, value: int):
		self._brightness = value
		self.notify(property='brightness')

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
		self.brightness = 15
		self.clock_format_string = "%-H<blinkSegment>%M"
		self.blink_segment = ":"
		self.refresh_timeout_in_secs = 1
		self._alarm_definitions = []

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
	def is_luminous(self)-> bool:
		return self._is_luminous

	@is_luminous.setter
	def is_luminous(self, value: bool):
		self._is_luminous = value
		self.notify(property='is_luminous')
	
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

class DisplayContent(Observable, Observer):
	is_volume_meter_shown: bool=False
	is_wifi_alarm: bool=False
	contrast_16: int=0
	brightness_16: int=1
	clock:str

	def notify(self):
		super().notify(reason="display_changed")

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, AlarmClockState):
			self.update_from_state(observation, observation.observable)
		if isinstance(observation.observable, Config):
			self.update_from_config(observation, observation.observable)

	def update_from_state(self, observation: Observation, state: AlarmClockState):
		if observation.property_name == 'is_wifi_available':
			self.is_wifi_alarm = not state.is_wifi_available
		if observation.property_name == 'is_luminous':
			self.contrast_16 = 10 if state.is_luminous else 1
		if observation.property_name == 'clock':
			self.clock = state.clock
			self.notify()

	def update_from_config(self, observation: Observation, config: Config):
		if observation.property_name == 'brightness':
			self.brightness_16 = int(config.brightness)

	def hide_volume_meter(self):
		logging.info("volume bar shown: %s", False)
		self.is_volume_meter_shown = False
		self.notify()

	def show_volume_meter(self):
		logging.info("volume bar shown: %s", True)
		self.is_volume_meter_shown = True 
		self.notify()

