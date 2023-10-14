import vlc
import time

class LivestreamPlayer:
	url = 'https://streams.br.de/bayern2sued_2.m3u'

	def __init__(self, url = None) -> None:
		if (url != None):
			self.url = url

	def play(self):
		media_player = vlc.MediaListPlayer() 
  
		player = vlc.Instance() 
		media_list = vlc.MediaList() 
		media = player.media_new(self.url) 
		media_list.add_media(media) 
		media_player.set_media_list(media_list) 
		print(f'start audio {self.url}')
		media_player.play()

		time.sleep(20)
		print('stop audio')

if __name__ == '__main__':
		LivestreamPlayer().play()