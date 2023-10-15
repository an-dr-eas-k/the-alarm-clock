from  enum import Enum

class AudioDefinition:
	activeLivestreamUrl: str = 'https://streams.br.de/bayern2sued_2.m3u'
	pass

class DisplayContent:
	showVolume: False
	showBlinkSegment: True
	
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
	volume: int = 50

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
		pass

	pass
