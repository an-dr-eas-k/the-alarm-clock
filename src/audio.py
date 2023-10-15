import vlc
import time

from domain import AudioDefinition

class LivestreamPlayer:
	audioDefinition: AudioDefinition

	def __init__(self, audioDefinition: AudioDefinition= None) -> None:
		if (audioDefinition != None):
			self.audioDefinition = audioDefinition

	def play(self):
		self.media_player = vlc.MediaListPlayer() 
  
		player = vlc.Instance() 
		media_list = vlc.MediaList() 
		media = player.media_new(self.audioDefinition.activeLivestreamUrl) 
		media_list.add_media(media) 
		self.media_player.set_media_list(media_list) 
		print(f'start audio {self.audioDefinition.activeLivestreamUrl}')
		self.media_player.play()

		time.sleep(20)
		print('stop audio')

	def stop(self):
		self.media_player.stop()
		pass

if __name__ == '__main__':
		LivestreamPlayer().play()