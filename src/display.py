import os
import traceback
from luma.core.device import device as luma_device
from luma.core.render import canvas
from PIL import ImageFont,Image, ImageOps

from domain import DisplayContent, Observation, Observer


class Display(Observer):

	resources_dir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"
	font_file = f"{resources_dir}/DSEG7ClassicMini-Bold.ttf"
	no_wifi_file = f"{resources_dir}/no-wifi.mono.png" 

	device: luma_device
	content: DisplayContent

	def __init__(self, device: luma_device, content: DisplayContent) -> None:
		self.device = device
		self.content = content
		self.content.attach(self)

	def fix_image(self, image: Image):
		background_color = (255, 255, 255)
		new_image = Image.new(self.device.mode, image.size, background_color)

		new_image.paste(image, mask=image.split()[3])
		return new_image

	def update(self, observation: Observation):
		super().update(observation)
		self.device.contrast(self.content.contrast)
		try:
			self.adjust_display()
		except Exception as e:
			print(traceback.format_exc())
			with canvas(self.device) as draw:
				draw.text((20,20), f"exception! ({e})", fill="white")
					
	def adjust_display(self):
		
		font=ImageFont.truetype(self.font_file, 50)
		font_BBox = font.getbbox(self.content.clock)
		width = font_BBox[2] - font_BBox[0]
		height = font_BBox[3] - font_BBox[1]
		with canvas(self.device) as draw:
			x = (draw.im.size[0]-width)/2
			y = (draw.im.size[1]-height)/2
 
			wifi = ImageOps.invert( self.fix_image(Image.open( self.no_wifi_file )) )
			draw.bitmap([10,10], wifi
							 .resize([int(0.05 * s) for s in wifi.size]), fill=1 )
			draw.text(
				stroke_width=0, 
				fill='white',
				align='left',
				text=self.content.clock,
				xy=[x, y],
				font=font)


if __name__ == '__main__':
	import argparse
	from luma.oled.device import ssd1322
	from luma.core.interface.serial import spi
	from luma.core.device import dummy
	import time
	parser = argparse.ArgumentParser("Display")
	parser.add_argument("-s", '--software', action='store_true')
	is_on_hardware = not parser.parse_args().software
	dev: luma_device

	if is_on_hardware:
		dev = ssd1322(serial_interface=spi(device=0, port=0))
	else:
		dev= dummy(height=64, width=256, mode="1")

	with canvas(dev) as draw:
		draw.text((20, 20), "Hello World!", fill="white")

	if is_on_hardware:
		time.sleep(10)
	else:
		dev.image.save("foo.png", format="png")
