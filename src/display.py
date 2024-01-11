import datetime
import logging
import math
import os
import traceback
from luma.core.device import device as luma_device
from luma.core.device import dummy as luma_dummy
from luma.core.render import canvas
from PIL import ImageFont, Image

from domain import Config, DisplayContent, Observation, Observer
from gpi import get_room_brightness
from utils.drawing import get_concat_h_multi_blank, grayscale_to_color, text_to_image
from utils.geolocation import GeoLocation

resources_dir = f"{os.path.dirname(os.path.realpath(__file__))}/resources"

class DisplayFormatter:
	foreground_grayscale_16: int
	background_grayscale_16: int
	clock_font: ImageFont

	def __init__(self, room_brightness: float, content: DisplayContent, config: Config):
		self.room_brightness = room_brightness
		self.display_content = content
		self.config = config
		self.adjust_display()
		logging.debug("room_brightness: %s, time_delta_to_alarm: %s, display_adjustments: %s", 
								room_brightness, self.display_content.get_timedelta_to_alarm(), self)

	def background_color(self):
		return grayscale_to_color(self.background_grayscale_16*16)

	def foreground_color(self, min_value: int=1):
		return grayscale_to_color(DisplayFormatter.respect_ranges(self.foreground_grayscale_16, min_value)*16)

	def respect_ranges(value: float, min_value: int = 1, max_value: int = 15) ->  int:
		return int(max(min_value, min(max_value, value)))

	def get_grayscale_value(self, room_brightness: float, min_value: int=1, max_value: int=15) -> int:
		return DisplayFormatter.respect_ranges( 32/(1+math.exp(-0.25*room_brightness))-16, min_value, max_value)

	def adjust_display(self):
		room_brightness = self.room_brightness
		time_delta_to_alarm = self.display_content.get_timedelta_to_alarm()
		self.adjust_display_internal(room_brightness, time_delta_to_alarm)

	def adjust_display_internal(self, room_brightness: float, time_delta_to_alarm: datetime.timedelta):
		bold_clock_font = ImageFont.truetype(f"{resources_dir}/DSEG7Classic-Regular.ttf", 50)
		light_clock_font = ImageFont.truetype(f"{resources_dir}/DSEG7ClassicMini-Light.ttf", 40)

		alarm_in_minutes = time_delta_to_alarm.total_seconds() / 60

		self.background_grayscale_16=0
		self.foreground_grayscale_16=self.get_grayscale_value(room_brightness)
		self.clock_font = bold_clock_font if room_brightness > 0.1 else light_clock_font

		if alarm_in_minutes < -8:
			return 

		if alarm_in_minutes < -4:
			self.background_grayscale_16=0
			self.foreground_grayscale_16=15
			self.clock_font=bold_clock_font
			return

		if alarm_in_minutes < -2:
			self.background_grayscale_16=7
			self.foreground_grayscale_16=0
			self.clock_font=bold_clock_font
			return

		if alarm_in_minutes < 0:
			self.background_grayscale_16=15
			self.foreground_grayscale_16=0
			self.clock_font=bold_clock_font
			return

	def format_clock_string(self, clock: datetime, show_blink_segment: bool = True) -> str:
		blink_segment = self.config.blink_segment if show_blink_segment else " "
		clock_string = clock.strftime(self.config.clock_format_string.replace("<blinkSegment>", blink_segment))
		clock_string = clock_string.replace("7", "`")
		desired_length = 5
		clock_string = "!" * (desired_length - len(clock_string)) + clock_string
		return clock_string

class Presentation:
	empty_image = Image.new("RGBA", (0, 0))
	font_file_7segment = f"{resources_dir}/DSEG7Classic-Regular.ttf"
	font_file_nerd = f"{resources_dir}/CousineNerdFontMono-Regular.ttf"

	content: DisplayContent

	def __init__(self, formatter: DisplayFormatter, content: DisplayContent) -> None:
		self.formatter = formatter
		self.content = content

	def draw(self) -> Image.Image:
		raise NotImplementedError("The draw method is not implemented.")

class ClockPresentation(Presentation):
	def __init__(self, formatter: DisplayFormatter, content: DisplayContent) -> None:
		super().__init__(formatter, content)

	def draw(self) -> Image.Image:
		font= self.formatter.clock_font
		clock_string = self.formatter.format_clock_string(GeoLocation().now(), self.content.show_blink_segment)
		clock_image = text_to_image(
			clock_string, 
			font, 
			fg_color=self.formatter.foreground_color(), 
			bg_color=self.formatter.background_color())
		return clock_image.resize([int(clock_image.width*0.95), clock_image.height])

class WifiStatusPresentation(Presentation):
	def __init__(self, formatter: DisplayFormatter, content: DisplayContent) -> None:
		super().__init__(formatter, content)

	def draw(self) -> Image.Image:
		font=ImageFont.truetype(self.font_file_nerd, 30)
		no_wifi_symbol = "\U000f05aa"
		return text_to_image(
			no_wifi_symbol, font, 
			fg_color=self.formatter.foreground_color(min_value=2), 
			bg_color=self.formatter.background_color())

class NextAlarmPresentation(Presentation):
	def __init__(self, formatter: DisplayFormatter, content: DisplayContent) -> None:
		super().__init__(formatter, content)

	def draw(self) -> Image.Image:
		if self.content.get_timedelta_to_alarm().total_seconds() / 3600 < -12: # 12 hours
			return self.empty_image

		font_nerd=ImageFont.truetype(self.font_file_nerd, 20)
		font_7segment=ImageFont.truetype(self.font_file_7segment, 13)

		next_alarm_string = self.formatter.format_clock_string(self.content.get_next_alarm())
		next_alarm_img = text_to_image(
			next_alarm_string, 
			font_7segment, 
			fg_color=self.formatter.foreground_color(min_value=2),
			bg_color=self.formatter.background_color())
		alarm_symbol = "󰀠"
		alarm_symbol_img = text_to_image(
			alarm_symbol, 
			font_nerd, 
			fg_color=self.formatter.foreground_color(min_value=2),
			bg_color=self.formatter.background_color())

		return get_concat_h_multi_blank(
			[alarm_symbol_img, Image.new(mode='RGBA', size=(3, 0), color=(0, 0, 0, 0)), next_alarm_img])

class WeatherStatusPresentation(Presentation):
	def __init__(self, formatter: DisplayFormatter, content: DisplayContent) -> None:
		super().__init__(formatter, content)
		self.font_file_weather = f"{resources_dir}/weather-icons/weathericons-regular-webfont.ttf"

	def draw(self) -> Image.Image:
		weather = self.content.current_weather
		if weather is None:
			return self.empty_image
		weather_character = weather.code.to_character()
		font_weather=ImageFont.truetype(self.font_file_weather, 20)
		font_7segment=ImageFont.truetype(self.font_file_7segment, 24)
		
		weather_image = text_to_image(
			weather_character, font_weather, 
			fg_color=self.formatter.foreground_color(min_value=2),
			bg_color=self.formatter.background_color())
		formatter = "{: .1f}"
		if abs(weather.temperature) >=10:
			formatter = "{: .0f}"
		temperature_image = text_to_image(
			formatter.format(weather.temperature), font_7segment, 
			fg_color=self.formatter.foreground_color(min_value=2),
			bg_color=self.formatter.background_color())

		width = int(0.6*weather_image.width) +temperature_image.width
		height = int(0.6*weather_image.height) + temperature_image.height
		dst = Image.new('RGB', [width, height], color=self.formatter.background_color())
		x=int(0.6*weather_image.width)
		y=int(0.6*weather_image.height)
		dst.paste(temperature_image, (x, y))
		dst.paste(weather_image, (0, 0))
		return dst

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
		self.device.contrast(16)
		room_brightness = get_room_brightness()

		self.current_display_image = self.present(room_brightness)
		self.device.display(self.current_display_image)
		if isinstance (self.device, luma_dummy):
			self.current_display_image.save(f"{os.path.dirname(os.path.realpath(__file__))}/../../display_test.png", format="png")


	def present(self, room_brightness: float):
		formatter = DisplayFormatter(room_brightness, self.content, self.config)
		im = Image.new("RGB", self.device.size, color=formatter.background_color())

		clock_image= ClockPresentation(formatter, self.content).draw()
		im.paste(clock_image, ((im.width-clock_image.width),int((im.height-clock_image.height)/2)))

		next_alarm_image = NextAlarmPresentation(formatter, self.content).draw()
		im.paste(next_alarm_image, (2,im.height-next_alarm_image.height-2), next_alarm_image)
		if self.content.get_is_wifi_available():
			im.paste(WeatherStatusPresentation(formatter, self.content).draw(), (2,4))
		else:
			im.paste(WifiStatusPresentation(formatter, self.content).draw(), (2,2))
		return im
		
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
