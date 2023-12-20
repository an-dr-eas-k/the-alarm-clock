import os
import traceback
from luma.core.device import device as luma_device
from luma.core.render import canvas
from PIL import ImageFont,Image, ImageOps, ImageDraw
from PIL.Image import Image as pil_image

from domain import DisplayContent, Observation, Observer


class Display(Observer):

	resources_dir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"
	font_file_7segment = f"{resources_dir}/DSEG7ClassicMini-Bold.ttf"
	font_file_nerd = f"{resources_dir}/CousineNerdFontMono-Regular.ttf"
	no_wifi_file = f"{resources_dir}/no-wifi.mono.png" 

	device: luma_device
	content: DisplayContent

	def __init__(self, device: luma_device, content: DisplayContent) -> None:
		self.device = device
		print(f"device mode: {self.device.mode}")
		self.content = content
		self.content.attach(self)

	def fix_image(self, image: pil_image) -> pil_image:
		background_color =  (255, 255, 255)
		new_image = Image.new("RGBA", image.size, background_color)
		foo = image.split()

		new_image.paste(image)
		return new_image

	def update(self, observation: Observation):
		super().update(observation)
		self.device.contrast(self.content.contrast_16*16)
		try:
			self.adjust_display()
		except Exception as e:
			print(traceback.format_exc())
			with canvas(self.device) as draw:
				draw.text((20,20), f"exception! ({e})", fill="white")
					
	def adjust_display(self):
		with canvas(self.device) as draw: 
			self.write_clock(draw)
			self.write_wifi_status(draw)
		
	def write_wifi_status(self, draw: ImageDraw.ImageDraw):
		font=ImageFont.truetype(self.font_file_nerd, 40)
		draw.text([2,-9], '\U000f16b5', fill=self.get_fill(), font=font)

	def write_clock(self, draw: ImageDraw.ImageDraw):
		fill = Display.to_fill(self.content.brightness_16*16)
		font=ImageFont.truetype(self.font_file, 50)
		font_BBox = font.getbbox(self.content.clock)
		width = font_BBox[2] - font_BBox[0]
		height = font_BBox[3] - font_BBox[1]
		x = (draw.im.size[0]-width)/2
		y = (draw.im.size[1]-height)/2

		draw.text(
			stroke_width=0, 
			fill=fill,
			align='left',
			text=self.content.clock,
			xy=[x, y],
			font=font)

	def to_fill(color):
		return (color << 16) | (color << 8) | color


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
		save_file = f"{os.path.dirname(os.path.realpath(__file__))}/../../display_test.png"
		dev.image.save(save_file, format="png")
