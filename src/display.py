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

from domain import Config, DisplayContent, Observation, Observer
from gpi import get_room_brightness
from utils.geolocation import GeoLocation
from utils.singleton import singleton

resources_dir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"

def get_concat_h(im1, im2):
	height = max(im1.height, im2.height)
	dst = Image.new('RGBA', (im1.width + im2.width, height))
	y=int(( height - im1.height ) / 2)
	dst.paste(im1, (0, y))
	y=int(( height - im2.height ) / 2)
	dst.paste(im2, (im1.width, y))
	return dst

def get_concat_h_multi_blank(im_list):
	_im = im_list.pop(0)
	for im in im_list:
			_im = get_concat_h(_im, im)
	return _im

def text_to_image(
	text: str,
	font: FreeTypeFont,
	fg_color,
	bg_color = 'black',
	mode: str = 'RGB',
):
   box = font.getbbox(text)
   img = Image.new(mode, (box[2]-box[0], box[3]-box[1]), bg_color)
   ImageDraw.Draw(img).text([-box[0],-box[1]], text, font=font, fill=fg_color)
   return img

def greyscale_to_color(grayscale_value: int):
		return (grayscale_value << 16) | (grayscale_value << 8) | grayscale_value

class Presentation:
	empty_image = Image.new("RGBA", (0, 0))
	font_file_7segment = f"{resources_dir}/DSEG7Classic-Regular.ttf"
	font_file_nerd = f"{resources_dir}/CousineNerdFontMono-Regular.ttf"
	font_file_weather = f"{resources_dir}/weather-icons/weathericons-regular-webfont.ttf"

	content: DisplayContent
	room_brightness: float

	def __init__(self, content: DisplayContent, config: Config, size: tuple[int, int]) -> None:
		logging.info("used presentation: %s", self.__class__.__name__)
		self.content = content
		self.config = config
		self.display_size = size

	def get_clock_font(self):
		return ImageFont.truetype(self.font_file_7segment, 50)

	def format_clock_string(self, clock: datetime, show_blink_segment: bool = True) -> str:
		blink_segment = self.config.blink_segment if show_blink_segment else " "
		clock_string = clock.strftime(self.config.clock_format_string.replace("<blinkSegment>", blink_segment))
		clock_string = clock_string.replace("7", "`")
		desired_length = 5
		clock_string = "!" * (desired_length - len(clock_string)) + clock_string
		return clock_string

	def respect_ranges(value: float, min_value: int = 16, max_value: int = 255) ->  int:
		return int(max(min_value, min(max_value, value)))

	def get_grayscale_value(self, min_value: int=16, max_value: int=255):
		return Presentation.respect_ranges( 500/(1+math.exp(-0.25*self.room_brightness))-250, min_value, max_value)

	def get_fill(self, min_value: int=16, max_value: int=255):
		return greyscale_to_color( self.get_grayscale_value(min_value, max_value) )

	def write_wifi_status(self) -> Image.Image:
		font=ImageFont.truetype(self.font_file_nerd, 30)
		return text_to_image('\U000f05aa', font, self.get_fill(min_value=32))

	def draw_clock(self) -> Image.Image:
		font=self.get_clock_font()
		clock_string = self.format_clock_string(GeoLocation().now(), self.content.show_blink_segment)
		clock_image = text_to_image(clock_string, font, self.get_fill())
		return clock_image.resize([int(clock_image.width*0.95), clock_image.height])
	
	def draw_next_alarm(self) -> Image.Image:
		next_alarm_job = self.content.next_alarm_job
		if next_alarm_job is None:
			return self.empty_image
		next_run_time: datetime = next_alarm_job.next_run_time
		
		if next_run_time is None or (next_run_time - GeoLocation().now()).total_seconds() / 3600 > 12.0:
			return self.empty_image

		font_nerd=ImageFont.truetype(self.font_file_nerd, 20)
		font_7segment=ImageFont.truetype(self.font_file_7segment, 13)

		fill = self.get_fill(min_value=32)

		next_alarm_string = self.format_clock_string(next_run_time)
		next_alarm_img = text_to_image(next_alarm_string, font_7segment, fill)
		alarm_symbol = "󰀠"
		alarm_symbol_img = text_to_image(alarm_symbol, font_nerd, fill)

		return get_concat_h_multi_blank([alarm_symbol_img, Image.new(mode='RGB', size=(3, 2)), next_alarm_img])

	def draw_weather_status(self) -> Image.Image:
		weather = self.content.current_weather
		if weather is None:
			return self.empty_image
		weather_character = weather.code.to_character()
		font_weather=ImageFont.truetype(self.font_file_weather, 20)
		font_7segment=ImageFont.truetype(self.font_file_7segment, 24)
		
		weather_image = text_to_image(weather_character, font_weather, self.get_fill(min_value=32))
		formatter = "{: .1f}"
		if abs(weather.temperature) >=10:
			formatter = "{: .0f}"
		temperature_image = text_to_image(formatter.format(weather.temperature), font_7segment, self.get_fill(min_value=32))

		width = int(0.6*weather_image.width) +temperature_image.width
		height = int(0.6*weather_image.height) + temperature_image.height
		dst = Image.new('RGB', [width, height])
		x=int(0.6*weather_image.width)
		y=int(0.6*weather_image.height)
		dst.paste(temperature_image, (x, y))
		dst.paste(weather_image, (0, 0))
		return dst

	def present(self, room_brightness: float):
		self.room_brightness = room_brightness
		logging.debug("room_brightness: %s, greyscale_value: %s", self.room_brightness, self.get_grayscale_value())
		im = Image.new("RGB", self.display_size, color='black')

		clock_image= self.draw_clock()
		im.paste(clock_image, ((im.width-clock_image.width),int((im.height-clock_image.height)/2)))

		next_alarm_image = self.draw_next_alarm()
		im.paste(next_alarm_image, (2,im.height-next_alarm_image.height-2))
		if self.content.get_is_wifi_available():
			im.paste(self.draw_weather_status(), (2,4))
		else:
			im.paste(self.write_wifi_status(), (2,2))
		return im

@singleton
class DozyPresentation(Presentation):

	font_file_7segment = f"{resources_dir}/DSEG7ClassicMini-Light.ttf"

	def get_clock_font(self):
		return ImageFont.truetype(self.font_file_7segment, 40)

	def draw_clock(self) -> Image.Image:
		font=self.get_clock_font()
		clock_string = self.format_clock_string(GeoLocation().now(), self.content.show_blink_segment)
		return text_to_image(clock_string, font, self.get_fill())

	def draw_weather_status(self) -> Image.Image:
		return Image.new(mode='RGB', size=(1, 1), color='black')

@singleton
class BrightPresentation(Presentation):
	pass


class Display(Observer):

	device: luma_device
	content: DisplayContent
	current_display_image: Image.Image

	def __init__(self, device: luma_device, content: DisplayContent, config: Config) -> None:
		self.device = device
		logging.info("device mode: %s", self.device.mode)
		self.content = content
		self.config = config
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
			p = DozyPresentation(self.content, self.config, [self.device.width, self.device.height])
		else:
			p = BrightPresentation(self.content, self.config, [self.device.width, self.device.height])

		self.device.contrast(16)
		self.current_display_image = p.present(room_brightness)
		self.device.display(self.current_display_image)
		
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
