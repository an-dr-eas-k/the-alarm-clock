import logging
import os
import traceback
from luma.core.device import device as luma_device
from luma.core.render import canvas
from PIL import ImageFont, ImageDraw

from domain import DisplayContent, Observation, Observer
from gpi import get_room_brightness_16, get_room_brightness_16_v2

resources_dir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"

class Presentation:
	font_file_7segment = f"{resources_dir}/DSEG7ClassicMini-Bold.ttf"
	font_file_nerd = f"{resources_dir}/CousineNerdFontMono-Regular.ttf"

	device: luma_device
	content: DisplayContent

	def __init__(self, device: luma_device, content: DisplayContent) -> None:
		logging.info("used presentation: %s", self.__class__.__name__)
		self.device = device
		self.content = content

	def get_clock_string(self) -> str:
		clock_string = self.content.clock.replace("7", "`")
		desired_length = 5
		clock_string = "!" * (desired_length - len(clock_string)) + clock_string
		return clock_string

	def get_fill(self):
		greyscale_value = 1
		return (greyscale_value << 16) | (greyscale_value << 8) | greyscale_value

	def write_wifi_status(self, draw: ImageDraw.ImageDraw):
		if not self.content.get_is_wifi_available():
			font=ImageFont.truetype(self.font_file_nerd, 40)
			draw.text([2,-9], '\U000f16b5', fill=self.get_fill(), font=font)

	def write_clock(self, draw: ImageDraw.ImageDraw):
		font=ImageFont.truetype(self.font_file_7segment, 50)
		font_BBox = font.getbbox(self.get_clock_string())
		width = font_BBox[2] - font_BBox[0]
		height = font_BBox[3] - font_BBox[1]
		x = (draw.im.size[0]-width)/2
		y = (draw.im.size[1]-height)/2

		draw.text(
			stroke_width=0, 
			fill=self.get_fill(),
			align='left',
			text=self.get_clock_string(),
			xy=[x, y],
			font=font)


	def present(self):
		with canvas(self.device) as draw: 
			self.write_clock(draw)
			self.write_wifi_status(draw)

class DozyPresentation(Presentation):

	def present(self):
		self.device.contrast(1)
		super().present()
		pass

class BrightPresentation(Presentation):

	def present(self):
		pass

class Display(Observer):

	device: luma_device
	content: DisplayContent

	def __init__(self, device: luma_device, content: DisplayContent) -> None:
		self.device = device
		logging.info("device mode: %s", self.device.mode)
		self.content = content
		self.content.attach(self)

	def update(self, observation: Observation):
		super().update(observation)
		try:
			self.adjust_display()
		except Exception as e:
			logging.warning("%s", traceback.format_exc())
			with canvas(self.device) as draw:
				draw.text((20,20), f"exception! ({e})", fill="white")

	def adjust_display(self):
		p: Presentation
		if (get_room_brightness_16() < 10 ):
			p = DozyPresentation(self.device, self.content)
		else:
			p = BrightPresentation(self.device, self.content)

		p.present()
		
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
