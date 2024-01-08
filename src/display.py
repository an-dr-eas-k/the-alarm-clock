from cgitb import grey
import datetime
import logging
import math
import os
import traceback
from luma.core.device import device as luma_device
from luma.core.render import canvas
from PIL import ImageFont, ImageDraw, Image
from PIL.ImageFont import FreeTypeFont

from domain import DisplayContent, Observation, Observer
from gpi import get_room_brightness
from utils.geolocation import GeoLocation
from utils.singleton import singleton

resources_dir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"

def get_concat_h(im1, im2):
    dst = Image.new('RGB', (im1.width + im2.width, im1.height))
    dst.paste(im1, (0, 0))
    dst.paste(im2, (im1.width, 0))
    return dst

def get_concat_h_multi_blank(im_list):
    _im = im_list.pop(0)
    for im in im_list:
        _im = get_concat_h(_im, im)
    return _im

def text_to_image(
text: str,
font: FreeTypeFont,
color: (int, int, int), #color is in RGB
font_align="center"):

   box = font.getbbox(text)
   img = Image.new("RGBA", (box[0], box[1]))
   draw = ImageDraw.Draw(img)
   draw_point = (0, 0)
   draw.multiline_text(draw_point, text, font=font, fill=color, align=font_align)
   return img

class Presentation:
	font_file_7segment = f"{resources_dir}/DSEG7Classic-Regular.ttf"
	font_file_nerd = f"{resources_dir}/CousineNerdFontMono-Regular.ttf"
	font_file_weather = f"{resources_dir}/weather-icons/weathericons-regular-webfont.ttf"

	content: DisplayContent
	room_brightness: float

	def __init__(self, content: DisplayContent) -> None:
		logging.info("used presentation: %s", self.__class__.__name__)
		self.content = content

	def get_clock_font(self):
		return ImageFont.truetype(self.font_file_7segment, 50)

	def get_clock_string(clock: str) -> str:
		clock_string = clock.replace("7", "`")
		desired_length = 5
		clock_string = "!" * (desired_length - len(clock_string)) + clock_string
		return clock_string

	def respect_ranges(value: float, min_value: int = 16, max_value: int = 255) ->  int:
		return int(max(min_value, min(max_value, value)))

	def get_fill(self, min_value: int=16, max_value: int=255):
		greyscale_value = Presentation.respect_ranges( 500/(1+math.exp(-0.3*self.room_brightness))-250, min_value, max_value)
		logging.debug("greyscale_value: %s", greyscale_value)
		return (greyscale_value << 16) | (greyscale_value << 8) | greyscale_value

	# def write_wifi_status(self, draw: ImageDraw.ImageDraw):
	# 	# if not self.content.get_is_wifi_available():
	# 		no_wifi_symbol = '\U000f1eb9'
	# 		font=ImageFont.truetype(self.font_file_nerd, 20)

	# 		bbox = font.getbbox(no_wifi_symbol)
	# 		wifi_image = Image.new("RGBA", [bbox[2], bbox[3]])
	# 		ImageDraw.Draw(wifi_image).text([0,0], no_wifi_symbol, fill='white', font=font)
			
	# 		draw.bitmap([0,0], wifi_image, fill='white')


	def write_wifi_status(self, draw: ImageDraw.ImageDraw):
		if not self.content.get_is_wifi_available():
			font=ImageFont.truetype(self.font_file_nerd, 30)
			draw.text([2,-6], '\U000f05aa', fill=self.get_fill(min_value=32), font=font)

	def write_clock(self, draw: ImageDraw.ImageDraw):
		font=self.get_clock_font()
		clock_string = Presentation.get_clock_string(self.content.clock)
		font_BBox = font.getbbox(clock_string)
		width = font_BBox[2] - font_BBox[0]
		height = font_BBox[3] - font_BBox[1]
		x = (draw.im.size[0]-width)
		y = (draw.im.size[1]-height)/2

		draw.text(
			stroke_width=0, 
			fill=self.get_fill(),
			align='left',
			text=clock_string,
			xy=[x, y],
			font=font)
	
	def write_next_alarm(self, draw: ImageDraw.ImageDraw):
		next_alarm_job = self.content.next_alarm_job
		if next_alarm_job is None:
			return
		next_run_time: datetime = next_alarm_job.next_run_time
		
		if next_run_time is None or (next_run_time - GeoLocation().now()).total_seconds() / 3600 > 12.0:
			return

		font_nerd=ImageFont.truetype(self.font_file_nerd, 20)
		font_7segment=ImageFont.truetype(self.font_file_7segment, 13)

		fill = self.get_fill(min_value=32)

		next_alarm_string = Presentation.get_clock_string(next_run_time.strftime("%-H:%M"))
		font_BBox_7segment = font_7segment.getbbox(next_alarm_string)
		alarm_symbol = "󰀠"
		font_BBox_symbol = font_nerd.getbbox(alarm_symbol)
		height = max(font_BBox_7segment[3], font_BBox_symbol[3])

		pos = [
			4,
			draw.im.size[1]-height-8]
		draw.text(pos, alarm_symbol, fill=fill, font=font_nerd)

		pos = [
			font_BBox_symbol[2] +6,
			draw.im.size[1]-height-2]
		draw.text(pos, next_alarm_string, fill=fill, font=font_7segment)

	def write_weather_status(self, draw: ImageDraw.ImageDraw):
		weather = self.content.current_weather
		if weather is None:
			return
		weather_character = weather.code.to_character()
		font_weather=ImageFont.truetype(self.font_file_weather, 20)
		font_7segment=ImageFont.truetype(self.font_file_7segment, 20)
		
		# weather_image = text_to_image(weather_character, font_weather, (150, 150, 150))
		# weather_image.save("weather.png")
		# temperature_image = text_to_image(str(weather.temperature), font_7segment, (255,255,255))
		# get_concat_h(weather_image, temperature_image).save("weather.png")
		# draw.bitmap([0,0], get_concat_h_multi_blank([weather_image, temperature_image]), fill=self.get_fill())
		# i: Image.Image = draw.im
		# draw.paste(weather_image, (0,0))
		# draw.im.paste(weather_image, None)

		draw.text([2,-4], weather_character, fill=self.get_fill(min_value=32), font=font_weather)
		# weather_temperature = "{:.{}f}".format(weather.temperature, 1 if weather.temperature < 10 else 0)
		# draw.text([2, 24], weather_temperature, fill=self.get_fill(), font=font_7segment)

	def present(self, draw, room_brightness: float):
		self.room_brightness = room_brightness
		self.write_clock(draw)
		self.write_next_alarm(draw)
		if not self.content.get_is_wifi_available():
			self.write_wifi_status(draw)
		else:
			self.write_weather_status(draw)

@singleton
class DozyPresentation(Presentation):

	font_file_7segment = f"{resources_dir}/DSEG7ClassicMini-Light.ttf"

	def get_clock_font(self):
		return ImageFont.truetype(self.font_file_7segment, 40)

@singleton
class BrightPresentation(Presentation):
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
		room_brightness = get_room_brightness()
		if (room_brightness <= 0.1 ):
			p = DozyPresentation(self.content)
		else:
			p = BrightPresentation(self.content)

		self.device.contrast(16)
		with canvas(self.device) as draw: 
			p.present(draw, room_brightness)
		
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
