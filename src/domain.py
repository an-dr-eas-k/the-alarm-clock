from enum import Enum
import re
import sched
import time
from apscheduler.schedulers.background import BackgroundScheduler


class Observer:

	def notify(self, propertyName: str, propertyValue: any):
		print(f"{self.__class__.__name__} is notified: {propertyName} changed to {propertyValue}")
		pass


class Observable:
	observers : []

	def __init__(self):
		self.observers = []

	def notifyObservers(self, propertyName):
		for k in [propertyName, f"_{propertyName}"]:
			if (k in self.__dict__):
				propertyName = k
			
		newValue = self.__getattribute__(propertyName)
		print (f"{self.__class__.__name__}: changing {propertyName}, new value {newValue}")
		for o in self.observers:
			o.notify(propertyName, newValue)

	def registerObserver(self, observer: Observer):
		self.observers.append(observer)
		for propertyName in filter(lambda x: not re.match(r"^__.*__$", x), dir(self)):
			try:
				self.notifyObservers(propertyName) 
			except:
				pass

class AudioDefinition(Observable):
	activeLivestreamUrl: str = 'https://streams.br.de/bayern2sued_2.m3u'
	isStreaming = False
	volumeInPercent: float = 0.50

	def increaseVolume(self):
		self.volumeInPercent += 0.05
		if self.volumeInPercent > 1:
			self.volumeInPercent = 1
		print (f"increasing Volume, new value {self.volumeInPercent}")
		self.notifyObservers('volumeInPercent')

	def decreaseVolume(self):
		self.volumeInPercent -= 0.05
		if self.volumeInPercent < 0:
			self.volumeInPercent = 0
		print (f"decreasing Volume, new value {self.volumeInPercent}")
		self.notifyObservers('volumeInPercent')

	def toggleStream(self):
		self.isStreaming = not self.isStreaming
		print (f"toggle streaming, new value isStreaming={self.isStreaming}")
		self.notifyObservers('isStreaming')

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
		self.notifyObservers('clock')

	def resetVolume(self):
		print("resetting volume")
		self.showVolume = False

	def notify(self, propertyName: str, propertyValue: any):
		super().notify(propertyName, propertyValue)
		if (propertyName == 'volumeInPercent'):
			self.showVolume = True 
			self.showVolumeTimer.queue.clear()
			self.showVolumeTimer.enter(5, 1, self.resetVolume)
			print("started volumetimer")




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

class AlarmDefinition:
	time: str
	weekdays: []
	alarmName: str
	isActive: bool

	def toJson(self):
		ret = {
			'time': self.time,
			'weekdays': list(map(lambda x: x.name, self.weekdays)), 
			'alarmName': self.alarmName,
			'isActive': self.isActive
		}        
		return ret


class Config(Observable):

	_alarmDefinitions: []

	@property
	def alarmDefinitions(self) -> []:
		return self._alarmDefinitions

	@alarmDefinitions.setter
	def alarmDefinitions(self, value: AlarmDefinition):
		self._alarmDefinitions.append(value)
		self.notifyObservers('alarmDefinitions')

	@property
	def brightness(self) -> int:
		return self._brightness

	@brightness.setter
	def brightness(self, value: int):
		self._brightness = value
		self.notifyObservers('brightness')

	@property
	def refreshTimeoutInSecs(self) -> int:
		return self._refreshTimeoutInSecs

	@refreshTimeoutInSecs.setter
	def refreshTimeoutInSecs(self, value: int):
		self._refreshTimeoutInSecs = value
		self.notifyObservers('refreshTimeoutInSecs')

	@property
	def clockFormatString(self) -> str:
		return self._clockFormatString

	@clockFormatString.setter
	def clockFormatString(self, value: str):
		self._clockFormatString = value
		self.notifyObservers('clockFormatString')

	@property
	def blinkSegment(self) -> str:
		return self._blinkSegment

	@blinkSegment.setter
	def blinkSegment(self, value: str):
		self._blinkSegment = value
		self.notifyObservers('blinkSegment')
	
	def toJson(self):
			ret = {
					'brightness': self.brightness,
					'clockFormatString': self.clockFormatString,
					'alarmDefinitions': ','.join( list(map(lambda x: x.toJson(), self.alarmDefinitions))), 
			}        
			return ret

	def __init__(self) -> None:
		super().__init__()
		self.brightness = 15
		self.clockFormatString = "%-H<blinkSegment>%M"
		self.blinkSegment = ":"
		self.refreshTimeoutInSecs = 1
		self._alarmDefinitions = []

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
		self.notifyObservers('isWifiAvailable')

	@property
	def isLuminous(self)-> bool:
		return self._isLuminous

	@isLuminous.setter
	def isLuminous(self, value: bool):
		self._isLuminous = value
		self.notifyObservers('isLuminous')
	
	@property
	def mode(self)-> Mode:
		return self._mode

	@mode.setter
	def mode(self, value: Mode):
		self._mode = value
		self.notifyObservers('mode')

	def __init__(self, c: Config) -> None:
		super().__init__()
		self.configuration = c
		self.audioState = AudioDefinition()
		self.displayContent = DisplayContent()
		self.audioState.registerObserver(self.displayContent)
		self.mode = Mode.Boot
