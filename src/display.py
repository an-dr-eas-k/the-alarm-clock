import os
from luma.core.device import device as lumadevice
from luma.core.render import canvas
from PIL import ImageFont,Image, ImageOps

from domain import DisplayContent, Observation, Observer


class Display(Observer):

	resourcesDir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"
	fontFile = f"{resourcesDir}/DSEG7ClassicMini-Bold.ttf"
	noWifiFile = f"{resourcesDir}/no-wifi.mono.png" 

	device: lumadevice
	content: DisplayContent

	def __init__(self, device: lumadevice, content: DisplayContent) -> None:
		self.device = device
		self.content = content
		self.content.registerObserver(self)

	def notify(self, observation: Observation):
		super().notify(observation)
		self.adjustDisplay()
					
	def adjustDisplay(self):

		font=ImageFont.truetype(self.fontFile, 40)
		fontBBox = font.getbbox(self.content.clock)
		width = fontBBox[2] - fontBBox[0]
		height = fontBBox[3] - fontBBox[1]
		with canvas(self.device) as draw:
			x = (draw.im.size[0]-width)/2
			y = (draw.im.size[1]-height)/2
 
			wifi = ImageOps.invert( Image.open( self.noWifiFile ))
			draw.bitmap([10,10], wifi
							 .resize([int(0.05 * s) for s in wifi.size]), fill=1 )
			draw.text(
				stroke_width=0, 
				fill=1,
				align='left',
				text=self.content.clock,
				xy=[x, y],
				font=font)

