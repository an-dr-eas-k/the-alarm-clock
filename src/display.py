import os
from luma.core.device import device as lumadevice
from luma.core.render import canvas
from PIL import ImageFont,Image, ImageOps

from domain import DisplayContent, Observation, Observer


class Display(Observer):

	resources_dir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"
	font_file = f"{resources_dir}/DSEG7ClassicMini-Bold.ttf"
	no_wifi_file = f"{resources_dir}/no-wifi.mono.png" 

	device: lumadevice
	content: DisplayContent

	def __init__(self, device: lumadevice, content: DisplayContent) -> None:
		self.device = device
		self.content = content
		self.content.attach(self)

	def update(self, observation: Observation):
		super().update(observation)
		self.adjust_display()
					
	def adjust_display(self):

		font=ImageFont.truetype(self.font_file, 40)
		font_BBox = font.getbbox(self.content.clock)
		width = font_BBox[2] - font_BBox[0]
		height = font_BBox[3] - font_BBox[1]
		with canvas(self.device) as draw:
			x = (draw.im.size[0]-width)/2
			y = (draw.im.size[1]-height)/2
 
			wifi = ImageOps.invert( Image.open( self.no_wifi_file ))
			draw.bitmap([10,10], wifi
							 .resize([int(0.05 * s) for s in wifi.size]), fill=1 )
			draw.text(
				stroke_width=0, 
				fill=1,
				align='left',
				text=self.content.clock,
				xy=[x, y],
				font=font)

