import datetime
import io
import json
import types
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from astral import LocationInfo

from tests.support import local_datetime
from utils import geolocation
from utils.geolocation import (
    GeoLocation,
    SunEvent,
    Weather,
    WMO_Code,
    translate_keys,
)

BERLIN = LocationInfo("Berlin", "Germany", "Europe/Berlin", 52.52, 13.405)


class TranslateKeysTest(unittest.TestCase):
    def test_translates_mapped_keys_only(self):
        result = translate_keys({"a": 1, "b": 2}, {"a": "x"})
        self.assertEqual(result, {"x": 1, "b": 2})

    def test_empty_inputs(self):
        self.assertEqual(translate_keys({}, {"a": "x"}), {})
        self.assertEqual(translate_keys({"a": 1}, {}), {"a": 1})

    def test_does_not_mutate_input(self):
        source = {"a": 1}
        translate_keys(source, {"a": "x"})
        self.assertEqual(source, {"a": 1})


class WMOCodeTest(unittest.TestCase):
    def test_known_code_maps_to_icon_character(self):
        self.assertEqual(WMO_Code(0).to_character(), "\uf055")

    def test_thunderstorm_code_maps_to_icon_character(self):
        self.assertEqual(WMO_Code(95).to_character(), "\uf01e")

    def test_unknown_code_maps_to_none(self):
        self.assertIsNone(WMO_Code(123456).to_character())

    def test_str_contains_code_and_character(self):
        self.assertEqual(str(WMO_Code(0)), "code: 0, character: \uf055")

    def test_str_of_unknown_code_shows_none(self):
        self.assertEqual(str(WMO_Code(-1)), "code: -1, character: None")


class WeatherTest(unittest.TestCase):
    def test_wraps_code_in_wmo_code(self):
        weather = Weather(3, 12.5)
        self.assertIsInstance(weather.code, WMO_Code)
        self.assertEqual(weather.code.code, 3)
        self.assertEqual(weather.temperature, 12.5)

    def test_equal_when_code_and_temperature_match(self):
        self.assertEqual(Weather(3, 12.5), Weather(3, 12.5))

    def test_not_equal_when_temperature_differs(self):
        self.assertNotEqual(Weather(3, 12.5), Weather(3, 13.0))

    def test_not_equal_when_code_differs(self):
        self.assertNotEqual(Weather(3, 12.5), Weather(61, 12.5))

    def test_str_format(self):
        self.assertIn("temperature: 12.5", str(Weather(0, 12.5)))


class SunEventTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(SunEvent.sunrise.value, "sunrise")
        self.assertEqual(SunEvent.sunset.value, "sunset")
        self.assertEqual(SunEvent("sunrise"), SunEvent.sunrise)

    def test_has_exactly_two_members(self):
        self.assertEqual(set(SunEvent.__members__), {"sunrise", "sunset"})


class GeoLocationTestCase(unittest.TestCase):
    """Restores the process-wide GeoLocation singleton after each test."""

    def setUp(self):
        self.geo = GeoLocation()
        original = self.geo.location_info
        self.addCleanup(setattr, self.geo, "location_info", original)

    def use_berlin(self):
        self.geo.configure(BERLIN)


class GeoLocationBasicsTest(GeoLocationTestCase):
    def test_is_singleton(self):
        self.assertIs(GeoLocation(), GeoLocation())

    def test_default_location_comes_from_offline_ip_api_stub(self):
        self.assertEqual(self.geo.location_info.name, "Munich")
        self.assertEqual(str(self.geo.location_info.tzinfo), "Europe/Berlin")

    def test_now_is_timezone_aware_in_location_timezone(self):
        now = self.geo.now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset(), datetime.datetime.now(ZoneInfo("Europe/Berlin")).utcoffset())

    def test_now_follows_configured_timezone(self):
        self.geo.configure(LocationInfo("Tokyo", "Japan", "Asia/Tokyo", 35.68, 139.69))
        self.assertEqual(self.geo.now().utcoffset(), datetime.timedelta(hours=9))

    def test_configure_replaces_location_info(self):
        self.use_berlin()
        self.assertIs(self.geo.location_info, BERLIN)


class LocationLookupTest(GeoLocationTestCase):
    def test_ip_api_builds_location_info(self):
        payload = {
            "city": "Hamburg",
            "region": "Hamburg",
            "timezone": "Europe/Berlin",
            "lat": 53.55,
            "lon": 9.99,
        }
        with mock.patch.object(geolocation, "json_api", return_value=payload) as api:
            info = self.geo.ip_api()

        api.assert_called_once_with("http://ip-api.com/json")
        self.assertEqual((info.name, info.region), ("Hamburg", "Hamburg"))
        self.assertAlmostEqual(info.latitude, 53.55, places=2)
        self.assertAlmostEqual(info.longitude, 9.99, places=2)
        self.assertEqual(str(info.tzinfo), "Europe/Berlin")

    def test_ip_api_raises_when_service_fails(self):
        with mock.patch.object(geolocation, "json_api", return_value=False):
            with self.assertRaises(TypeError):
                self.geo.ip_api()

    def test_geolocation_db_builds_location_info_with_london_timezone(self):
        payload = {
            "city": "Paris",
            "country_name": "France",
            "latitude": 48.85,
            "longitude": 2.35,
        }
        with mock.patch.object(geolocation, "json_api", return_value=payload) as api:
            info = self.geo.geolocation_db()

        api.assert_called_once_with("https://geolocation-db.com/json/")
        self.assertEqual((info.name, info.region), ("Paris", "France"))
        self.assertEqual(str(info.tzinfo), "Europe/London")

    def test_get_location_info_uses_ip_api_result(self):
        sentinel = LocationInfo("X", "Y", "UTC", 1, 2)
        with mock.patch.object(self.geo, "ip_api", return_value=sentinel):
            self.assertIs(self.geo.get_location_info(), sentinel)

    def test_get_location_info_falls_back_to_munich_on_exception(self):
        with mock.patch.object(
            self.geo, "ip_api", side_effect=RuntimeError("down")
        ), self.assertLogs("tac.geolocation", "WARNING"):
            info = self.geo.get_location_info()
        self.assertEqual((info.name, info.region), ("Munich", "Bavaria"))
        self.assertEqual(str(info.tzinfo), "Europe/Berlin")
        self.assertAlmostEqual(info.latitude, 48.1372, places=3)

    def test_get_location_info_falls_back_when_api_returns_false(self):
        with mock.patch.object(
            geolocation, "json_api", return_value=False
        ), self.assertLogs("tac.geolocation", "WARNING"):
            info = self.geo.get_location_info()
        self.assertEqual(info.name, "Munich")


class SunEventCalculationTest(GeoLocationTestCase):
    def setUp(self):
        super().setUp()
        self.use_berlin()

    def test_summer_sunrise_precedes_sunset_on_same_day(self):
        day = datetime.date(2024, 6, 21)
        sunrise = self.geo.get_sun_event(SunEvent.sunrise, day)
        sunset = self.geo.get_sun_event(SunEvent.sunset, day)
        self.assertLess(sunrise, sunset)
        self.assertEqual(sunrise.date(), day)

    def test_summer_days_are_longer_than_winter_days(self):
        def length(day):
            return self.geo.get_sun_event(SunEvent.sunset, day) - self.geo.get_sun_event(
                SunEvent.sunrise, day
            )

        self.assertGreater(
            length(datetime.date(2024, 6, 21)), length(datetime.date(2024, 12, 21))
        )

    def test_default_day_is_today_in_location_timezone(self):
        now = local_datetime(2024, 3, 20, 12, 0)
        with mock.patch.object(self.geo, "now", return_value=now):
            event = self.geo.get_sun_event(SunEvent.sunrise)
        self.assertEqual(event.date(), datetime.date(2024, 3, 20))

    def test_polar_night_raises_value_error(self):
        self.geo.configure(
            LocationInfo("Longyearbyen", "Norway", "Arctic/Longyearbyen", 78.22, 15.65)
        )
        with self.assertRaises(ValueError):
            self.geo.get_sun_event(SunEvent.sunrise, datetime.date(2024, 12, 21))


class SunEventCronArgsTest(GeoLocationTestCase):
    def setUp(self):
        super().setUp()
        self.use_berlin()

    def cron_args(self, now, event, day=None):
        with mock.patch.object(self.geo, "now", return_value=now):
            return self.geo.get_sun_event_cron_args(event, day)

    def test_upcoming_event_today_is_used(self):
        now = local_datetime(2024, 6, 21, 0, 30)
        args = self.cron_args(now, SunEvent.sunrise)
        expected = self.geo.get_sun_event(SunEvent.sunrise, datetime.date(2024, 6, 21))

        self.assertEqual(args["start_date"], expected.date())
        self.assertEqual(args["end_date"], expected.date() + datetime.timedelta(days=1))
        self.assertEqual(args["minute"], expected.minute)

    def test_event_already_passed_rolls_over_to_next_day(self):
        now = local_datetime(2024, 6, 21, 22, 0)
        args = self.cron_args(now, SunEvent.sunset)
        tomorrow = self.geo.get_sun_event(SunEvent.sunset, datetime.date(2024, 6, 22))

        self.assertEqual(args["start_date"], tomorrow.date())
        self.assertEqual(args["minute"], tomorrow.minute)

    def test_explicit_day_is_respected(self):
        now = local_datetime(2024, 1, 1, 0, 0)
        args = self.cron_args(now, SunEvent.sunset, datetime.date(2024, 6, 21))
        expected = self.geo.get_sun_event(SunEvent.sunset, datetime.date(2024, 6, 21))
        self.assertEqual(args["start_date"], expected.date())

    def test_result_contains_exactly_the_cron_keys(self):
        args = self.cron_args(local_datetime(2024, 6, 21, 0, 0), SunEvent.sunrise)
        self.assertEqual(set(args), {"start_date", "end_date", "hour", "minute"})

    def test_hour_is_expressed_in_location_timezone(self):
        # suspected bug: sun() returns UTC times, so cron hour is UTC, not local
        now = local_datetime(2024, 6, 21, 0, 30)
        args = self.cron_args(now, SunEvent.sunrise)
        local_sunrise = self.geo.get_sun_event(
            SunEvent.sunrise, datetime.date(2024, 6, 21)
        ).astimezone(self.geo.location_info.tzinfo)
        self.assertEqual(args["hour"], local_sunrise.hour)


class LastSunEventTest(GeoLocationTestCase):
    def setUp(self):
        super().setUp()
        self.use_berlin()

    def test_midday_means_sunrise_was_last(self):
        dt = datetime.datetime(2024, 6, 21, 12, 0, tzinfo=BERLIN.tzinfo)
        self.assertEqual(self.geo.last_sun_event(dt), SunEvent.sunrise)

    def test_late_evening_means_sunset_was_last(self):
        dt = datetime.datetime(2024, 6, 21, 23, 0, tzinfo=BERLIN.tzinfo)
        self.assertEqual(self.geo.last_sun_event(dt), SunEvent.sunset)

    def test_before_dawn_means_sunset_was_last(self):
        dt = datetime.datetime(2024, 6, 21, 2, 0, tzinfo=BERLIN.tzinfo)
        self.assertEqual(self.geo.last_sun_event(dt), SunEvent.sunset)

    def test_winter_late_afternoon_is_already_after_sunset(self):
        dt = datetime.datetime(2024, 12, 21, 17, 30, tzinfo=BERLIN.tzinfo)
        self.assertEqual(self.geo.last_sun_event(dt), SunEvent.sunset)

    def test_defaults_to_current_time(self):
        fake_now = datetime.datetime(2024, 6, 21, 12, 0, tzinfo=BERLIN.tzinfo)

        class FakeDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now

        fake_module = types.SimpleNamespace(
            datetime=FakeDatetime, date=datetime.date, timedelta=datetime.timedelta
        )
        with mock.patch.object(geolocation, "datetime", fake_module):
            self.assertEqual(self.geo.last_sun_event(), SunEvent.sunrise)


class CurrentWeatherTest(GeoLocationTestCase):
    def setUp(self):
        super().setUp()
        self.use_berlin()

    @staticmethod
    def response(payload):
        return io.BytesIO(json.dumps(payload).encode())

    def test_returns_weather_from_api_payload(self):
        payload = {"current": {"weather_code": 61, "temperature_2m": 7.5}}
        with mock.patch.object(
            geolocation, "urlopen", return_value=self.response(payload)
        ):
            weather = self.geo.get_current_weather()

        self.assertEqual(weather, Weather(61, 7.5))

    def test_request_url_contains_coordinates_and_uses_timeout(self):
        payload = {"current": {"weather_code": 0, "temperature_2m": 1}}
        with mock.patch.object(
            geolocation, "urlopen", return_value=self.response(payload)
        ) as urlopen:
            self.geo.get_current_weather()

        url = urlopen.call_args.args[0]
        self.assertIn("api.open-meteo.com", url)
        self.assertIn(f"latitude={BERLIN.latitude}", url)
        self.assertIn(f"longitude={BERLIN.longitude}", url)
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 10})

    def test_network_error_returns_none(self):
        with mock.patch.object(geolocation, "urlopen", side_effect=OSError("offline")):
            self.assertIsNone(self.geo.get_current_weather())

    def test_malformed_payload_returns_none(self):
        with mock.patch.object(
            geolocation, "urlopen", return_value=self.response({"unexpected": 1})
        ):
            self.assertIsNone(self.geo.get_current_weather())

    def test_invalid_json_returns_none(self):
        with mock.patch.object(
            geolocation, "urlopen", return_value=io.BytesIO(b"not json")
        ):
            self.assertIsNone(self.geo.get_current_weather())


if __name__ == "__main__":
    unittest.main()
