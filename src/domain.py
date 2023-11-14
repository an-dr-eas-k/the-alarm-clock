from dataclasses import dataclass
from enum import Enum
import re
import sched
import time

import jsonpickle
from apscheduler.triggers.cron import CronTrigger

class Observation:
	during_registration: bool
	reason: str = None
	property_name: str = None
	new_value: any = None
	observable: any = None

	def __init__(self, property_name: str = None, reason: str = None, during_registration: bool = False, observable: any = None) -> None:
		assert property_name or reason
		self.during_registration = during_registration
		self.reason = reason
		self.property_name = property_name
		self.observable = observable

	def to_string(self):
		property_segment = ""
		if self.property_name:
			property_segment = f"property {self.property_name}={self.new_value}"
		reason_segment = ""
		if self.reason:
			reason_segment = f"reason {self.reason}"
		return f"observation {self.observable.__class__.__name__}: {reason_segment}{property_segment}"


class Observer:

	def update(self, observation: Observation):
		print(f"{self.__class__.__name__} is notified: {observation.to_string()}")

class Observable:
	observers : []

	def __init__(self):
		self.observers = []

	def notify(self, property=None, reason = None, during_registration: bool = False):

		o: Observation
		if property:
			assert property in dir(self)
			o = Observation(property_name=property, during_registration=during_registration, observable=self)
			o.new_value = self.__getattribute__(o.property_name)
		else:
			o = Observation(reason=reason, during_registration=during_registration, observable=self)

		for observer in self.observers:
			assert isinstance(observer, Observer)
			observer.update( o )

	def attach(self, observer: Observer):
		self.observers.append(observer)
		properties = [
			attr for attr in dir(self) 
			if True
				and attr != 'observers'
				and not re.match(r"^__.*__$", attr) 
				and hasattr(self, attr) 
				and not callable(getattr(self, attr)) ]
		for property_name in properties:
			try:
				self.notify(property=property_name, during_registration=True) 
			except:
				pass

	def __getstate__(self):
		state = self.__dict__.copy()
		del state['observers']
		return state

	def __setstate__(self, state):
		state['observers'] = []
		self.__dict__.update(state)

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
	alarm_name: str
	is_active: bool
	visual_effect: VisualEffect
	audio_effect: AudioEffect = InternetRadio(url='https://streams.br.de/bayern2sued_2.m3u')

	def toCronTrigger(self) -> CronTrigger:
		return CronTrigger(
			day_of_week=",".join([ str(wd.value -1) for wd in self.weekdays]),
			hour=self.hour,
			minute=self.min
		)

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
	
class DisplayContent(Observable, Observer):
	show_volume: bool= False
	show_volume_timer: sched.scheduler
	show_blink_segment:bool= True

	def __init__(self):
		super().__init__()
		self.show_volume_timer = sched.scheduler(time.time, time.sleep)
		self.show_volume_timer.run()

	@property
	def clock(self) -> str:
		return self._clock

	@clock.setter
	def clock(self, value: str):
		self._clock = value
		self.notify(property='clock')

	def reset_volume(self):
		print("resetting volume")
		self.show_volume = False

	def update(self, observation: Observation):
		super().update(observation)
		if (observation.property_name == 'volume'):
			self.show_volume = True 
			self.show_volume_timer.queue.clear()
			self.show_volume_timer.enter(5, 1, self.reset_volume)
			print("started volumetimer")


class Config(Observable):

	_alarm_definitions: []

	@property
	def alarm_definitions(self) -> []:
		return self._alarm_definitions

	@alarm_definitions.setter
	def alarm_definitions(self, value: AlarmDefinition):
		self._alarm_definitions.append(value)
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
		return jsonpickle.encode(self, indent=2, )

	def deserialize(config_file):
		with open(config_file, "r") as file:
			file_contents = file.read()
			return jsonpickle.decode(file_contents)

class AlarmClockState(Observable):

	configuration: Config
	display_content: DisplayContent
	audio_state: AudioDefinition

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
		self.display_content = DisplayContent()
		self.audio_state.attach(self.display_content)
		self.mode = Mode.Boot
