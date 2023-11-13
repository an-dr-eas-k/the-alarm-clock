import vlc
import time
import subprocess 
import threading
import re

from domain import Observation, Observer

class Speaker(Observer):
	mediaPlayer: vlc.MediaListPlayer = None
	activeLivestreamUrl: str

	def __init__(self) -> None:
		self.threadLock = threading.Lock()

	def notify(self, observation: Observation):
		super().notify(observation)
		if (observation.propertyName == 'volumeInPercent'):
			self.adjustVolume(observation.propertyValue)
		elif (observation.propertyName == 'isStreaming'):
			self.adjustStreaming(observation.propertyValue)
		elif (observation.propertyName == 'activeLivestreamUrl'):
			self.activeLivestreamUrl = observation.propertyValue

	def adjustVolume(self, newVolume: float):
		controlName = self.get_first_control_name()
		subprocess.call(["amixer", "sset", controlName, f"{newVolume * 100}%"], stdout=subprocess.DEVNULL)
		pass

	def get_first_control_name(self):
		output = subprocess.check_output(["amixer", "scontrols"])
		lines = output.decode().splitlines()
		first_control_line = next(line for line in lines if line.startswith("Simple"))
		pattern = r"^Simple.+'(\S+)',\d+$"
		first_control_name = re.match(pattern, first_control_line).group(1)
		return first_control_name


	def adjustStreaming(self, isStreaming: bool):
		self.threadLock.acquire(True)

		if (isStreaming):
			self.startStreaming(self.activeLivestreamUrl)
		else:
			self.stopStreaming()

		self.threadLock.release()
	
	def startStreaming(self, activeLivestreamUrl: str):
		if (self.mediaPlayer is not None):
			return

		self.mediaPlayer = vlc.MediaListPlayer() 
	
		player = vlc.Instance() 
		media_list = vlc.MediaList() 
		media = player.media_new(activeLivestreamUrl) 
		media_list.add_media(media) 
		self.mediaPlayer.set_media_list(media_list) 
		print(f'start audio {activeLivestreamUrl}')
		self.mediaPlayer.play()



	def stopStreaming(self):
		if (self.mediaPlayer is None):
			return

		self.mediaPlayer.stop()
		self.mediaPlayer = None
		pass

if __name__ == '__main__':
		Speaker().adjustStreaming(True)