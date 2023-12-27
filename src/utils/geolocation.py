from enum import Enum
import json
from urllib.request import urlopen
import datetime
from astral import LocationInfo
from astral.sun import sun
from apscheduler.triggers.cron import CronTrigger

from utils.singleton import singleton

class SunEvent(Enum):
	sunrise = 'sunrise'
	sunset = 'sunset'

@singleton
class GeoLocation:

	def __init__(self):
		self.location_info = self.get_location_info()

	def now(self) -> datetime.datetime:
		return datetime.datetime.now(self.location_info.tzinfo)

	def ip_info(self):
		url = 'http://ip-api.com/json'
		response = urlopen(url)
		return json.load(response)

	def get_location_info(self) -> LocationInfo:
		ip_info = self.ip_info()
		return LocationInfo(
			ip_info['city'], 
			ip_info['region'], 
			ip_info['timezone'], 
			ip_info['lat'], 
			ip_info['lon'])

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

if __name__ == '__main__':
	gl = GeoLocation()
	data = GeoLocation.ip_info()

	print (data)

	print (gl.get_sun_event('sunrise').strftime('%H:%M:%S'))
	print (gl.get_sun_event('sunset').strftime('%H:%M:%S'))