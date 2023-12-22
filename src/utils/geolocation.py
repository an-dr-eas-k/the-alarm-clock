from enum import Enum
import json
from urllib.request import urlopen
import datetime
from astral import LocationInfo
from astral.sun import sun
from apscheduler.triggers.cron import CronTrigger

class SunEvent(Enum):
	sunrise = 'sunrise'
	sunset = 'sunset'

def ipinfo():
	url = 'http://ip-api.com/json'
	response = urlopen(url)
	return json.load(response)

def get_location_info() -> LocationInfo:
	ip_info = ipinfo()
	return LocationInfo(
		ip_info['city'], 
		ip_info['region'], 
		ip_info['timezone'], 
		ip_info['lat'], 
		ip_info['lon'])

def get_sun_event(
		event: SunEvent, 
		day: datetime.date = datetime.date.today()) -> datetime.datetime:

	location = get_location_info()
	return sun(location.observer, date=day)[event.value]

def get_sun_event_cron_trigger(
		event: SunEvent, 
		day: datetime.date = datetime.date.today()) -> CronTrigger:

	event_time = get_sun_event(event, day+datetime.timedelta(days=1))
	return CronTrigger(
		start_date=event_time.date(),
		end_date=event_time.date()+datetime.timedelta(days=1),
		hour=event_time.hour,
		minute=event_time.minute
	)

def last_sun_event(dt: datetime.datetime =None ) -> SunEvent:
	location = get_location_info()
	if dt is None:
		dt = datetime.datetime.now(location.tzinfo)
	localSun = sun(location.observer, date=dt.date(), tzinfo=location.tzinfo)
	return SunEvent.sunrise \
		if dt > localSun[SunEvent.sunrise.value] and dt < localSun[SunEvent.sunset.value] \
		else SunEvent.sunset

if __name__ == '__main__':
	data = ipinfo()

	print (data)

	print (get_sun_event('sunrise').strftime('%H:%M:%S'))
	print (get_sun_event('sunset').strftime('%H:%M:%S'))