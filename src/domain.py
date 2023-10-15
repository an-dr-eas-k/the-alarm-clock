from  enum import Enum

class AudioDefinition:
	activeLivestreamUrl: str = 'https://streams.br.de/bayern2sued_2.m3u'
	isStreaming = False
	volumeInPercent: float = 0.50

	def increaseVolume(self):
		self.volumeInPercent += 0.05
		if self.volumeInPercent > 1:
			self.volumeInPercent = 1
		print (f"increasing Volume, new value {self.volumeInPercent}")

	def decreaseVolume(self):
		self.volumeInPercent -= 0.05
		if self.volumeInPercent < 0:
			self.volumeInPercent = 0
		print (f"decreasing Volume, new value {self.volumeInPercent}")

	def toggleStream(self):
		self.isStreaming = not self.isStreaming
		print (f"toggle streaming, new value isStreaming={self.isStreaming}")

class DisplayContent:
	showVolume:bool= False
	showBlinkSegment:bool= True
	
	pass

class Mode(Enum):
	Boot = 1
	PreAlarm = 2
	Alarm = 3

	pass

class Config:
	brightness: int = 15
	clockFormatString: str = "%-H<blinkSegment>%M"
	blinkSegment: str = ":"
	refreshTimeoutInSecs = 1

	pass

class AlarmClockState:
	configuration: Config
	displayContent: DisplayContent
	audioState: AudioDefinition
	isWifiAvailable: bool
	isLight: bool
	mode: Mode = Mode.Boot

	def __init__(self, c: Config) -> None:
		self.configuration = c
		self.audioState = AudioDefinition()
		self.displayContent = DisplayContent()
		pass

	pass
