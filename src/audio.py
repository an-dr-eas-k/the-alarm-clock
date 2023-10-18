import vlc
import time
import subprocess 
import threading
import re

from domain import AudioDefinition, Observer

class Speaker(Observer):
	audioDefinition: AudioDefinition
	mediaPlayer: vlc.MediaListPlayer = None

	def __init__(self, audioDefinition: AudioDefinition= AudioDefinition()) -> None:
		self.audioDefinition = audioDefinition
		self.threadLock = threading.Lock()
		self.audioDefinition.registerObserver(self)

	def notify(self, propertyName, propertyValue):
		super().notify(propertyName, propertyValue)
		self.adjustSpeaker()

	def adjustSpeaker(self):
		self.adjustStreaming()
		self.adjustVolume()
		pass

	def adjustVolume(self):
		controlName = self.get_first_control_name()
		subprocess.call(["amixer", "sset", controlName, f"{self.audioDefinition.volumeInPercent * 100}%"], stdout=subprocess.DEVNULL)
		pass

	def get_first_control_name(self):
		output = subprocess.check_output(["amixer", "scontrols"])
		lines = output.decode().splitlines()
		first_control_line = next(line for line in lines if line.startswith("Simple"))
		pattern = r"^Simple.+'(\S+)',\d+$"
		first_control_name = re.match(pattern, first_control_line).group(1)
		return first_control_name


	def adjustStreaming(self):
		self.threadLock.acquire(True)

		if (self.audioDefinition.isStreaming):
			self.startStreaming()
		else:
			self.stopStreaming()

		self.threadLock.release()
	
	def startStreaming(self):
		if (self.mediaPlayer is not None):
			return

		self.mediaPlayer = vlc.MediaListPlayer() 
	
		player = vlc.Instance() 
		media_list = vlc.MediaList() 
		media = player.media_new(self.audioDefinition.activeLivestreamUrl) 
		media_list.add_media(media) 
		self.mediaPlayer.set_media_list(media_list) 
		print(f'start audio {self.audioDefinition.activeLivestreamUrl}')
		self.mediaPlayer.play()



	def stopStreaming(self):
		if (self.mediaPlayer is None):
			return

		self.mediaPlayer.stop()
		self.mediaPlayer = None
		pass

if __name__ == '__main__':
		Speaker().adjustStreaming()