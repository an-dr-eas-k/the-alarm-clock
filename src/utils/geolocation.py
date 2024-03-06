from enum import Enum
import json
import logging
import traceback
import xml.etree.ElementTree as ET
from urllib.request import urlopen
import datetime
from astral import LocationInfo
from astral.sun import sun
from apscheduler.triggers.cron import CronTrigger
from utils.network import json_api

from utils.singleton import singleton

from resources.resources import weather_icons_dir

weather_icons_tree = ET.parse(f"{weather_icons_dir}/weathericons.xml").getroot()

def translate_keys(input_dict, translation_map):
	return {translation_map.get(k, k): v for k, v in input_dict.items()}

class WMO_Code:

	def __init__(self, code: int):
		self.code = code

	def to_character(self):
		weather_icon_element = weather_icons_tree.find(f".//string[@name='wi_wmo4680_{self.code}']")
		if weather_icon_element is not None:
			return weather_icon_element.text
		else:
			return None

	def __str__(self):
		return f"code: {self.code}, character: {self.to_character()}"

class Weather:
	code: WMO_Code
	temperature: float

	def __init__(self, code: int, temperature: float):
		self.code = WMO_Code(code)
		self.temperature = temperature

	def __str__(self):
		return f"code: {self.code}, temperature: {self.temperature}"

class SunEvent(Enum):
	sunrise = 'sunrise'
	sunset = 'sunset'

@singleton
class GeoLocation:

	def __init__(self):
		self.location_info = self.get_location_info()

	def now(self) -> datetime.datetime:
		return datetime.datetime.now(self.location_info.tzinfo)

	def ip_api(self):
		location_from_ip = json_api('http://ip-api.com/json')
		return LocationInfo(
			location_from_ip['city'], 
			location_from_ip['region'], 
			location_from_ip['timezone'], 
			location_from_ip['lat'], 
			location_from_ip['lon'])

	def geolocation_db(self):
		location_from_ip = json_api('https://geolocation-db.com/json/')
		return LocationInfo(
			location_from_ip['city'], 
			location_from_ip['country_name'], 
			'Europe/London',
			location_from_ip['latitude'], 
			location_from_ip['longitude'])

	def get_location_info(self) -> LocationInfo:
		try:
			return self.ip_api()
			# ip_info = self.ip_api()
			# geolocation_db = self.geolocation_db()
			# return LocationInfo(
			# 	geolocation_db.name, 
			# 	geolocation_db.region, 
			# 	ip_info.timezone, 
			# 	geolocation_db.latitude, 
			# 	geolocation_db.longitude
			# )
		except:
			logging.warning("%s", traceback.format_exc())
			return LocationInfo(
				'Munich',
				'Bavaria',
				'Europe/Berlin',
				48.1112,
				11.5501)

	def get_sun_event(self,
			event: SunEvent, 
			day: datetime.date = None) -> datetime.datetime:

		day = self.now().date() if day is None else day

		return sun(self.location_info.observer, date=day)[event.value]

	def get_sun_event_cron_trigger(self,
			event: SunEvent, 
			day: datetime.date = None) -> CronTrigger:

		day = self.now().date() if day is None else day

		event_time = self.get_sun_event(event, day+datetime.timedelta(days=1))
		return CronTrigger(
			start_date=event_time.date(),
			end_date=event_time.date()+datetime.timedelta(days=1),
			hour=event_time.hour,
			minute=event_time.minute
		)

	def last_sun_event(self, dt: datetime.datetime =None ) -> SunEvent:
		if dt is None:
			dt = datetime.datetime.now(self.location_info.tzinfo)
		localSun = sun(self.location_info.observer, date=dt.date(), tzinfo=self.location_info.tzinfo)
		return SunEvent.sunrise \
			if dt > localSun[SunEvent.sunrise.value] and dt < localSun[SunEvent.sunset.value] \
			else SunEvent.sunset

	def get_current_weather(self):
		try:
			url = f"https://api.open-meteo.com/v1/forecast?latitude={self.location_info.latitude}&longitude={self.location_info.longitude}&current=temperature_2m&current=weather_code"
			data = json.load(urlopen(url))
			return Weather (code=data['current']['weather_code'], temperature=data['current']['temperature_2m']) 
		except:
			return None

if __name__ == '__main__':
	gl = GeoLocation()
	data = GeoLocation.ip_api()

	print (data)

	print (gl.get_sun_event('sunrise').strftime('%H:%M:%S'))
	print (gl.get_sun_event('sunset').strftime('%H:%M:%S'))