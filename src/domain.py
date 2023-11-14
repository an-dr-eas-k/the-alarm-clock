from dataclasses import dataclass
from enum import Enum
import re
import sched
import time

import jsonpickle
from apscheduler.triggers.cron import CronTrigger

class Observation:
	duringRegistration: bool
	reason: str = None
	propertyName: str = None
	newValue: any = None
	observable: any = None

	def __init__(self, propertyName: str = None, reason: str = None, duringRegistration: bool = False, observable: any = None) -> None:
		assert propertyName or reason
		self.duringRegistration = duringRegistration
		self.reason = reason
		self.propertyName = propertyName
		self.observable = observable

	def to_string(self):
		property_segment = ""
		if self.propertyName:
			property_segment = f"property {self.propertyName}={self.newValue}"
		reason_segment = ""
		if self.reason:
			reason_segment = f"reason {self.reason}"
		return f"observation {self.observable.__class__.__name__}: {reason_segment}{property_segment}"


class Observer:

	def notify(self, observation: Observation):
		print(f"{self.__class__.__name__} is notified: {observation.to_string()}")
		pass

class Observable:
	observers : []

	def __init__(self):
		self.observers = []

	def notifyObservers(self, property=None, reason = None, duringRegistration: bool = False):

		o: Observation
		if property:
			assert property in dir(self)
			o = Observation(propertyName=property, duringRegistration=duringRegistration, observable=self)
			o.newValue = self.__getattribute__(o.propertyName)
		else:
			o = Observation(reason=reason, duringRegistration=duringRegistration, observable=self)

		for observer in self.observers:
			observer.notify( o )

	def registerObserver(self, observer: Observer):
		self.observers.append(observer)
		properties = [
			attr for attr in dir(self) 
			if True
				and attr != 'observers'
				and not re.match(r"^__.*__$", attr) 
				and hasattr(self, attr) 
				and not callable(getattr(self, attr)) ]
		for propertyName in properties:
			try:
				self.notifyObservers(property=propertyName, duringRegistration=True) 
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
	playId: str


class AlarmDefinition:
	hour: int
	min: int
	weekdays: []
	alarmName: str
	isActive: bool
	visualEffect: VisualEffect
	audioEffect: AudioEffect = InternetRadio(url='https://streams.br.de/bayern2sued_2.m3u')

	def toCronTrigger(self) -> CronTrigger:
		return CronTrigger(
			day_of_week=",".join([ str(wd.value -1) for wd in self.weekdays]),
			hour="*", # self.hour,
			minute="*" # self.min
		)

class AudioDefinition(Observable):
	_audioEffect: AudioEffect = InternetRadio(url='https://streams.br.de/bayern2sued_2.m3u')
	isStreaming = False
	volumeInPercent: float = 0.50

	@property
	def audioEffect(self) -> str:
		return self._audioEffect

	@audioEffect.setter
	def audioEffect(self, value: AudioEffect):
		self._audioEffect = value
		self.notifyObservers(property='audioEffect')

	def increaseVolume(self):
		self.volumeInPercent += 0.05
		if self.volumeInPercent > 1:
			self.volumeInPercent = 1
		self.notifyObservers(property='volumeInPercent')

	def decreaseVolume(self):
		self.volumeInPercent -= 0.05
		if self.volumeInPercent < 0:
			self.volumeInPercent = 0
		self.notifyObservers(property='volumeInPercent')

	def toggleStream(self):
		self.isStreaming = not self.isStreaming
		self.notifyObservers(property='isStreaming')
	
	def startStream(self):
		self.isStreaming = True
		self.notifyObservers(property='isStreaming')

	def endStream(self):
		self.isStreaming = False
		self.notifyObservers(property='isStreaming')


class DisplayContent(Observable, Observer):
	showVolume:bool= False
	showVolumeTimer: sched.scheduler
	showBlinkSegment:bool= True

	def __init__(self):
		super().__init__()
		self.showVolumeTimer = sched.scheduler(time.time, time.sleep)
		self.showVolumeTimer.run()

	@property
	def clock(self) -> str:
		return self._clock

	@clock.setter
	def clock(self, value: str):
		self._clock = value
		self.notifyObservers(property='clock')

	def resetVolume(self):
		print("resetting volume")
		self.showVolume = False

	def notify(self, observation: Observation):
		super().notify(observation)
		if (observation.propertyName == 'volumeInPercent'):
			self.showVolume = True 
			self.showVolumeTimer.queue.clear()
			self.showVolumeTimer.enter(5, 1, self.resetVolume)
			print("started volumetimer")


class Config(Observable):

	_alarmDefinitions: []

	@property
	def alarmDefinitions(self) -> []:
		return self._alarmDefinitions

	@alarmDefinitions.setter
	def alarmDefinitions(self, value: AlarmDefinition):
		self._alarmDefinitions.append(value)
		self.notifyObservers(property='alarmDefinitions')

	@property
	def brightness(self) -> int:
		return self._brightness

	@brightness.setter
	def brightness(self, value: int):
		self._brightness = value
		self.notifyObservers(property='brightness')

	@property
	def refreshTimeoutInSecs(self) -> int:
		return self._refreshTimeoutInSecs

	@refreshTimeoutInSecs.setter
	def refreshTimeoutInSecs(self, value: int):
		self._refreshTimeoutInSecs = value
		self.notifyObservers(property='refreshTimeoutInSecs')

	@property
	def clockFormatString(self) -> str:
		return self._clockFormatString

	@clockFormatString.setter
	def clockFormatString(self, value: str):
		self._clockFormatString = value
		self.notifyObservers(property='clockFormatString')

	@property
	def blinkSegment(self) -> str:
		return self._blinkSegment

	@blinkSegment.setter
	def blinkSegment(self, value: str):
		self._blinkSegment = value
		self.notifyObservers(property='blinkSegment')
	
	def __init__(self) -> None:
		super().__init__()
		self.brightness = 15
		self.clockFormatString = "%-H<blinkSegment>%M"
		self.blinkSegment = ":"
		self.refreshTimeoutInSecs = 1
		self._alarmDefinitions = []

	def serialize(self):
		return jsonpickle.encode(self, indent=2, )

	def deserialize(configFile):
		with open(configFile, "r") as file:
			fileContents = file.read()
			return jsonpickle.decode(fileContents)

class AlarmClockState(Observable):

	configuration: Config
	displayContent: DisplayContent
	audioState: AudioDefinition

	@property
	def isWifiAvailable(self) -> bool:
		return self._isWifiAvailable

	@isWifiAvailable.setter
	def isWifiAvailable(self, value: bool):
		self._isWifiAvailable = value
		self.notifyObservers(property='isWifiAvailable')

	@property
	def isLuminous(self)-> bool:
		return self._isLuminous

	@isLuminous.setter
	def isLuminous(self, value: bool):
		self._isLuminous = value
		self.notifyObservers(property='isLuminous')
	
	@property
	def mode(self)-> Mode:
		return self._mode

	@mode.setter
	def mode(self, value: Mode):
		self._mode = value
		self.notifyObservers(property='mode')

	def __init__(self, c: Config) -> None:
		super().__init__()
		self.configuration = c
		self.audioState = AudioDefinition()
		self.displayContent = DisplayContent()
		self.audioState.registerObserver(self.displayContent)
		self.mode = Mode.Boot
