from enum import Enum


class Observer:

	def notify(self, _):
		pass


class Observable:
	observers = []

	def notifyObservers(self, propertyName):
		newValue = self.__dict__.get(propertyName)
		print (f"changing {propertyName}, new value {newValue}")
		for o in self.observers:
			o.notify(propertyName, newValue)

	def registerObserver(self, observer: Observer):
		self.observers.append(observer)

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

class DisplayContent(Observable):
	showVolume:bool= False
	showBlinkSegment:bool= True

class Mode(Enum):
	Boot = 1
	PreAlarm = 2
	Alarm = 3

class Config(Observable):

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

	def __init__(self) -> None:
		super().__init__()
		self.brightness = 15
		self.clockFormatString = "%-H<blinkSegment>%M"
		self.blinkSegment = ":"
		self.refreshTimeoutInSecs = 1

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
		self.configuration = c
		self.audioState = AudioDefinition()
		self.displayContent = DisplayContent()
		self.mode = Mode.Boot

	def registerObserver(self, observer: Observer):
		super().registerObserver(observer)
		self.configuration.registerObserver(observer)
		self.displayContent.registerObserver(observer)
		self.audioState.registerObserver(observer)