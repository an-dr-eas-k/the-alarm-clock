import datetime
import json
import logging
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import tornado
import tornado.ioloop
import tornado.testing
from PIL import Image

from core.application import api as api_module
from core.application.api import Api, parse_path_arguments, try_update
from core.domain.events import (
    ConfigChangedEvent,
    PlaybackChangedEvent,
    ShutdownSystemRequest,
    SpotifyApiEvent,
    TerminateAppRequest,
    VolumeChangeRequest,
    WifiStatusChangedEvent,
)
from core.domain.model import AlarmClockContext, Mode
from tests.support import RecordingEventBus, make_alarm, make_config, make_stream

logging.getLogger("tac").addHandler(logging.NullHandler())
logging.getLogger("tornado").addHandler(logging.NullHandler())


class ParsePathArgumentsTests(unittest.TestCase):
    def test_splits_type_id_and_property(self):
        self.assertEqual(
            parse_path_arguments(["alarm/a1/is_active"]), ("alarm", "a1", "is_active")
        )

    def test_missing_segments_are_none(self):
        self.assertEqual(parse_path_arguments(["alarm"]), ("alarm", None, None))
        self.assertEqual(parse_path_arguments(["alarm/a1"]), ("alarm", "a1", None))

    def test_empty_id_segment_is_none(self):
        self.assertEqual(parse_path_arguments(["alarm//name"]), ("alarm", None, "name"))

    def test_empty_path(self):
        self.assertEqual(parse_path_arguments([""]), ("", None, None))


class TryUpdateTests(unittest.TestCase):
    class Target:
        flag = False
        count = 3
        ratio = 0.5
        name = "old"
        items = ["a"]

    def setUp(self):
        self.target = self.Target()

    def test_unknown_property_is_rejected(self):
        self.assertFalse(try_update(self.target, "missing", "x"))
        self.assertFalse(hasattr(self.target, "missing"))

    def test_bool_values_are_parsed_case_insensitively(self):
        for text in ("on", "yes", "TRUE", "t", "1"):
            self.target.flag = False
            self.assertTrue(try_update(self.target, "flag", text))
            self.assertTrue(self.target.flag, text)
        for text in ("off", "no", "false", "0", ""):
            self.target.flag = True
            self.assertTrue(try_update(self.target, "flag", text))
            self.assertFalse(self.target.flag, text)

    def test_numbers_are_converted_to_the_current_type(self):
        try_update(self.target, "count", "7")
        try_update(self.target, "ratio", "0.25")
        self.assertEqual(self.target.count, 7)
        self.assertEqual(self.target.ratio, 0.25)

    def test_invalid_number_raises(self):
        with self.assertRaises(ValueError):
            try_update(self.target, "count", "abc")
        self.assertEqual(self.target.count, 3)

    def test_lists_are_decoded_from_json(self):
        try_update(self.target, "items", '["x", "y"]')
        self.assertEqual(self.target.items, ["x", "y"])

    def test_empty_list_value_resets_list(self):
        try_update(self.target, "items", "")
        self.assertEqual(self.target.items, [])

    def test_invalid_list_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            try_update(self.target, "items", "[oops")

    def test_empty_value_resets_scalar_to_none(self):
        try_update(self.target, "name", "")
        self.assertIsNone(self.target.name)

    def test_unchanged_value_is_not_reassigned(self):
        class Guarded:
            def __init__(self):
                self.writes = 0

            @property
            def name(self):
                return "same"

            @name.setter
            def name(self, value):
                self.writes += 1

        guarded = Guarded()
        self.assertTrue(try_update(guarded, "name", "same"))
        self.assertEqual(guarded.writes, 0)


class ApiTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.bus = RecordingEventBus()
        self.streams = [
            make_stream("One", "http://one", id="s1"),
            make_stream("Two", "http://two", id="s2"),
        ]
        self.config = make_config(self.bus, streams=self.streams)
        self.context = AlarmClockContext(self.config, is_online=True)
        self.alarm_audio_service = mock.MagicMock()
        self.alarm_audio_service.alarm_clock_context = self.context
        self.system_service = mock.MagicMock()
        self.display = mock.MagicMock()
        self.executor = mock.MagicMock(spec=ThreadPoolExecutor)
        self.executor.submit.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        self.api = Api(
            self.alarm_audio_service,
            self.system_service,
            self.display,
            self.bus,
            self.executor,
            encrypted=False,
        )
        return self.api.app

    def post(self, path: str, body="", **kwargs):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        return self.fetch(path, method="POST", body=body, **kwargs)

    def config_events(self):
        return self.bus.emitted_of(ConfigChangedEvent)

    def add_alarm(self, **kwargs):
        kwargs.setdefault("recurring", ["MONDAY"])
        alarm = make_alarm(**kwargs)
        self.config.add_alarm_definition(alarm)
        return alarm


ALARM_FORM = dict(
    alarmName="Weekday",
    time="06:45",
    recurring=["monday", "Friday"],
    streamId="s2",
    volume="0.4",
    visualEffectActive="on",
    isActive="on",
    fadein_in_secs="30",
    alarmLabel="Job",
)


class ConfigApiGetTests(ApiTestCase):
    # production bug: the route passes a path argument but ConfigApiHandler.get() accepts none (HTTP 500)
    @unittest.expectedFailure
    def test_returns_serialized_config_as_json(self):
        response = self.fetch("/api/config")
        self.assertEqual(response.code, 200)
        self.assertIn("application/json", response.headers["Content-Type"])
        self.assertEqual(response.body.decode(), self.config.serialize())


class ConfigApiPostTests(ApiTestCase):
    def test_scalar_setting_is_updated_and_announced(self):
        response = self.post("/api/config/alarm_duration_in_mins", "42")
        self.assertEqual(response.code, 200)
        self.assertEqual(self.config.alarm_duration_in_mins, 42)
        self.assertEqual(len(self.config_events()), 1)
        self.assertIs(self.config_events()[0].config, self.config)

    def test_boolean_setting_is_parsed(self):
        self.post("/api/config/use_analog_clock", "on")
        self.assertTrue(self.config.use_analog_clock)

    def test_float_setting_is_parsed(self):
        self.post("/api/config/default_volume", "0.55")
        self.assertEqual(self.config.default_volume, 0.55)

    def test_list_setting_is_decoded(self):
        self.post("/api/config/predefined_alarm_labels", '["Job", "Gym"]')
        self.assertEqual(self.config.predefined_alarm_labels, ["Job", "Gym"])

    def test_invalid_setting_value_changes_nothing_and_sends_no_event(self):
        before = self.config.alarm_duration_in_mins
        response = self.post("/api/config/alarm_duration_in_mins", "abc")
        self.assertEqual(response.code, 200)
        self.assertEqual(self.config.alarm_duration_in_mins, before)
        self.assertEqual(self.config_events(), [])

    def test_alarm_is_created_from_form(self):
        response = self.post("/api/config/alarm", ALARM_FORM)
        self.assertEqual(response.code, 200)
        (alarm,) = self.config.alarm_definitions
        self.assertEqual(alarm.alarm_name, "Weekday")
        self.assertEqual((alarm.hour, alarm.min), (6, 45))
        self.assertEqual(alarm.recurring, ["MONDAY", "FRIDAY"])
        self.assertIsNone(alarm.onetime)
        self.assertIs(alarm.audio_effect.audio_stream, self.streams[1])
        self.assertEqual(alarm.audio_effect.volume, 0.4)
        self.assertIsNotNone(alarm.visual_effect)
        self.assertTrue(alarm.is_active)
        self.assertEqual(alarm.fadein_in_secs, 30)
        self.assertEqual(alarm.alarm_label, "Job")
        self.assertTrue(alarm.id)
        self.assertEqual(len(self.config_events()), 1)

    def test_single_weekday_string_is_accepted(self):
        self.post("/api/config/alarm", dict(ALARM_FORM, recurring="sunday"))
        self.assertEqual(self.config.alarm_definitions[0].recurring, ["SUNDAY"])

    def test_alarm_without_weekdays_becomes_onetime_alarm(self):
        form = {k: v for k, v in ALARM_FORM.items() if k != "recurring"}
        self.post("/api/config/alarm", form)
        (alarm,) = self.config.alarm_definitions
        self.assertIsNone(alarm.recurring)
        self.assertIsInstance(alarm.onetime, datetime.date)

    def test_optional_form_fields_default_to_off(self):
        form = {
            k: v
            for k, v in ALARM_FORM.items()
            if k not in ("visualEffectActive", "isActive", "fadein_in_secs", "alarmLabel")
        }
        self.post("/api/config/alarm", form)
        (alarm,) = self.config.alarm_definitions
        self.assertIsNone(alarm.visual_effect)
        self.assertFalse(alarm.is_active)
        self.assertEqual(alarm.fadein_in_secs, 0)
        self.assertIsNone(alarm.alarm_label)

    def test_existing_alarm_is_replaced_keeping_its_id(self):
        old = self.add_alarm(id="a1", hour=5)
        other = self.add_alarm(id="a2")

        self.post("/api/config/alarm/a1", ALARM_FORM)

        self.assertEqual({a.id for a in self.config.alarm_definitions}, {"a1", "a2"})
        replaced = self.config.get_alarm_definition_by_id("a1")
        self.assertIsNot(replaced, old)
        self.assertEqual(replaced.hour, 6)
        self.assertIs(self.config.get_alarm_definition_by_id("a2"), other)
        self.assertEqual(len(self.config_events()), 1)

    def test_alarm_property_can_be_toggled(self):
        self.add_alarm(id="a1", is_active=True)
        self.post("/api/config/alarm/a1/is_active", "false")
        alarm = self.config.get_alarm_definition_by_id("a1")
        self.assertFalse(alarm.is_active)
        self.assertEqual(len(self.config.alarm_definitions), 1)
        self.assertEqual(len(self.config_events()), 1)

    def test_alarm_property_update_for_unknown_alarm_is_ignored(self):
        self.add_alarm(id="a1")
        self.post("/api/config/alarm/unknown/is_active", "false")
        self.assertTrue(self.config.get_alarm_definition_by_id("a1").is_active)

    def test_invalid_alarm_form_is_rejected_without_changes(self):
        invalid_forms = [
            {k: v for k, v in ALARM_FORM.items() if k != "alarmName"},
            dict(ALARM_FORM, time="25-99"),
            dict(ALARM_FORM, recurring=["funday"]),
            dict(ALARM_FORM, volume="loud"),
            dict(ALARM_FORM, alarmLabel="toolong"),
            dict(ALARM_FORM, fadein_in_secs="soon"),
        ]
        for form in invalid_forms:
            response = self.post("/api/config/alarm", form)
            self.assertEqual(response.code, 200)
        self.assertEqual(self.config.alarm_definitions, [])
        self.assertEqual(self.config_events(), [])

    def test_invalid_replacement_keeps_original_alarm(self):
        original = self.add_alarm(id="a1")
        self.post("/api/config/alarm/a1", dict(ALARM_FORM, recurring=["funday"]))
        alarm = self.config.get_alarm_definition_by_id("a1")
        self.assertIsNotNone(alarm)
        self.assertIs(alarm, original)
        self.assertEqual(alarm.hour, original.hour)
        self.assertEqual(alarm.min, original.min)
        self.assertEqual(alarm.recurring, original.recurring)
        self.assertEqual(alarm.audio_effect.volume, original.audio_effect.volume)

    def test_malformed_json_body_is_rejected(self):
        self.post("/api/config/alarm", "{not json")
        self.assertEqual(self.config.alarm_definitions, [])
        self.assertEqual(self.config_events(), [])

    def test_stream_is_added(self):
        self.post(
            "/api/config/stream",
            dict(streamName="New", streamUrl="http://new.example/stream"),
        )
        self.assertEqual(len(self.config.audio_streams), 3)
        added = self.config.audio_streams[-1]
        self.assertEqual(added.stream_name, "New")
        self.assertEqual(added.stream_url, "http://new.example/stream")
        self.assertTrue(added.id)

    def test_stream_without_url_is_rejected(self):
        self.post("/api/config/stream", dict(streamName="New"))
        self.assertEqual(len(self.config.audio_streams), 2)
        self.assertEqual(self.config_events(), [])

    def test_powernap_alarm_is_added(self):
        self.post("/api/config/start_powernap")
        (alarm,) = self.config.alarm_definitions
        self.assertEqual(alarm.alarm_name, "Powernap")
        self.assertTrue(alarm.is_active)
        self.assertIs(alarm.audio_effect.audio_stream, self.streams[0])
        self.assertEqual(len(self.config_events()), 1)

    def test_powernap_without_streams_is_rejected(self):
        self.config.audio_streams.clear()
        self.post("/api/config/start_powernap")
        self.assertEqual(self.config.alarm_definitions, [])
        self.assertEqual(self.config_events(), [])

    def test_unknown_type_only_announces_config_change(self):
        self.post("/api/config/whatever")
        self.assertEqual(self.config.alarm_definitions, [])
        self.assertEqual(len(self.config_events()), 1)


class ConfigApiDeleteTests(ApiTestCase):
    def test_alarm_is_removed(self):
        self.add_alarm(id="a1")
        keep = self.add_alarm(id="a2")
        response = self.fetch("/api/config/alarm/a1", method="DELETE")
        self.assertEqual(response.code, 200)
        self.assertEqual(self.config.alarm_definitions, [keep])
        self.assertEqual(len(self.config_events()), 1)

    def test_stream_is_removed(self):
        self.fetch("/api/config/stream/s1", method="DELETE")
        self.assertEqual([s.id for s in self.config.audio_streams], ["s2"])
        self.assertEqual(len(self.config_events()), 1)

    def test_unknown_id_is_a_noop_but_still_announced(self):
        self.add_alarm(id="a1")
        self.fetch("/api/config/alarm/missing", method="DELETE")
        self.assertEqual(len(self.config.alarm_definitions), 1)
        self.assertEqual(len(self.config_events()), 1)

    def test_unknown_type_is_ignored(self):
        self.fetch("/api/config/foo/bar", method="DELETE")
        self.assertEqual(len(self.config.audio_streams), 2)


class ActionApiTests(ApiTestCase):
    def only_event(self, event_type):
        events = self.bus.emitted_of(event_type)
        self.assertEqual(len(events), 1, self.bus.emitted)
        return events[0]

    def test_play_starts_the_requested_stream(self):
        response = self.post("/api/action/play/s2")
        self.assertEqual(response.code, 200)
        event = self.only_event(PlaybackChangedEvent)
        self.assertEqual(event.playback_mode, Mode.Music)
        self.assertIs(event.audio_stream, self.streams[1])

    def test_play_unknown_stream_passes_no_stream(self):
        self.post("/api/action/play/missing")
        event = self.only_event(PlaybackChangedEvent)
        self.assertEqual(event.playback_mode, Mode.Music)
        self.assertIsNone(event.audio_stream)

    def test_stop_switches_to_idle(self):
        self.post("/api/action/stop")
        self.assertEqual(self.only_event(PlaybackChangedEvent).playback_mode, Mode.Idle)

    def test_volume_up_and_down(self):
        self.post("/api/action/volume/1")
        self.post("/api/action/volume/0")
        relatives = [e.relative for e in self.bus.emitted_of(VolumeChangeRequest)]
        self.assertEqual(relatives, [1, -1])

    def test_reboot_and_shutdown(self):
        self.post("/api/action/reboot")
        self.post("/api/action/shutdown")
        events = self.bus.emitted_of(ShutdownSystemRequest)
        self.assertEqual([e.reboot for e in events], [True, False])

    def test_update_terminates_app_and_stops_io_loop(self):
        fake_loop = mock.MagicMock()
        fake_ioloop_module = mock.MagicMock()
        fake_ioloop_module.IOLoop.current.return_value = fake_loop
        with mock.patch.object(api_module.tornado, "ioloop", fake_ioloop_module):
            response = self.post("/api/action/update")
        self.assertEqual(response.code, 200)
        self.only_event(TerminateAppRequest)
        fake_loop.stop.assert_called_once_with()

    def test_unknown_action_emits_nothing(self):
        response = self.post("/api/action/explode")
        self.assertEqual(response.code, 200)
        self.assertEqual(self.bus.emitted, [])

    def test_get_is_not_allowed(self):
        self.assertEqual(self.fetch("/api/action/stop").code, 405)


class SystemApiTests(ApiTestCase):
    def test_wifi_connected_and_disconnected(self):
        self.post("/api/system/wifi?status=connected")
        self.post("/api/system/wifi?status=disconnected")
        events = self.bus.emitted_of(WifiStatusChangedEvent)
        self.assertEqual([e.is_online for e in events], [True, False])

    def test_wifi_status_can_be_sent_as_form_field(self):
        self.post("/api/system/wifi", "status=connected")
        events = self.bus.emitted_of(WifiStatusChangedEvent)
        self.assertEqual([e.is_online for e in events], [True])

    def test_unknown_wifi_status_is_ignored(self):
        for path in ("/api/system/wifi?status=weird", "/api/system/wifi"):
            self.assertEqual(self.post(path).code, 200)
        self.assertEqual(self.bus.emitted, [])

    def test_unknown_system_action_is_ignored(self):
        self.assertEqual(self.post("/api/system/format-disk").code, 200)
        self.assertEqual(self.bus.emitted, [])


class LibreSpotifyApiTests(ApiTestCase):
    def test_event_payload_is_forwarded_to_event_bus(self):
        payload = dict(player_event="playing", name="Song", artists="Artist")
        response = self.post("/api/librespotify", payload)
        self.assertEqual(response.code, 200)
        (event,) = self.bus.emitted_of(SpotifyApiEvent)
        self.assertEqual(event.player_event, "playing")
        self.assertEqual(event.name, "Song")
        self.assertTrue(event.is_playback_started())
        self.executor.submit.assert_called_once()

    def test_empty_body_is_forwarded_as_empty_event(self):
        self.assertEqual(self.post("/api/librespotify").code, 200)
        (event,) = self.bus.emitted_of(SpotifyApiEvent)
        self.assertIsNone(event.player_event)

    def test_invalid_json_is_ignored(self):
        self.assertEqual(self.post("/api/librespotify", "{broken").code, 200)
        self.assertEqual(self.bus.emitted_of(SpotifyApiEvent), [])

    def test_non_object_json_is_ignored(self):
        self.assertEqual(self.post("/api/librespotify", "[1, 2]").code, 200)
        self.assertEqual(self.bus.emitted_of(SpotifyApiEvent), [])


class DisplayHandlerTests(ApiTestCase):
    def test_current_display_image_is_returned_as_inline_png(self):
        self.display.current_display_image = Image.new("RGB", (4, 2), "white")
        response = self.fetch("/display")
        self.assertEqual(response.code, 200)
        self.assertTrue(
            response.body.decode().startswith('<img src="data:image/png;base64, ')
        )

    def test_missing_image_results_in_server_error(self):
        self.display.current_display_image = None
        with self.assertLogs("tornado.application", level="ERROR"):
            response = self.fetch("/display")
        self.assertEqual(response.code, 500)


class StaticAndIndexRouteTests(ApiTestCase):
    def test_unknown_media_file_is_not_found(self):
        with self.assertLogs("tornado.access", level="WARNING"):
            response = self.fetch("/media/does-not-exist.png")
        self.assertEqual(response.code, 404)

    def test_index_page_renders_template_with_config(self):
        response = self.fetch("/")
        self.assertEqual(response.code, 200)
        self.assertIn(b"html", response.body.lower())


class ApiClassTests(unittest.TestCase):
    def setUp(self):
        self.bus = RecordingEventBus()
        self.config = make_config(self.bus)
        self.context = AlarmClockContext(self.config, is_online=True)
        self.context.environment.is_daytime = True
        self.alarm_audio_service = mock.MagicMock()
        self.alarm_audio_service.alarm_clock_context = self.context
        self.alarm_audio_service.display_content.refresh_duration_in_ms = 12
        self.alarm_audio_service.playback_content.audio_stream = make_stream("Radio")
        self.alarm_audio_service.playback_content.volume = 0.3
        self.alarm_audio_service.playback_content.playback_mode = Mode.Music
        self.system_service = mock.MagicMock()
        self.system_service.get_room_brightness.return_value = 0.42
        self.display = mock.MagicMock()
        self.display.formatter.foreground_color.return_value = 15
        self.display.formatter.background_color.return_value = 0
        self.api = self.create_api(encrypted=False)

    def create_api(self, encrypted: bool) -> Api:
        return Api(
            self.alarm_audio_service,
            self.system_service,
            self.display,
            self.bus,
            mock.MagicMock(),
            encrypted=encrypted,
        )

    def test_state_json_reports_clock_state(self):
        with mock.patch.object(
            api_module.subprocess, "check_output", return_value=b" 10:00 up 1 day\n"
        ):
            state = json.loads(self.api.get_state_as_json())
        self.assertEqual(state["room_brightness"], 0.42)
        self.assertEqual(state["display"]["foreground_color"], 15)
        self.assertEqual(state["display"]["background_color"], 0)
        self.assertEqual(state["display"]["refresh_duration_in_ms"], 12)
        self.assertTrue(state["is_online"])
        self.assertTrue(state["is_daytime"])
        self.assertEqual(state["playback_content"]["mode"], "Music")
        self.assertEqual(state["playback_content"]["volume"], 0.3)
        self.assertIn("Radio", state["playback_content"]["audio_stream"])
        self.assertEqual(state["uptime"], "10:00 up 1 day")
        self.assertIn("geo_location", state)

    def test_git_log_combines_branch_and_last_commit(self):
        outputs = [b"main\n", b"commit abc123\n"]
        with mock.patch.object(
            api_module.subprocess, "check_output", side_effect=outputs
        ) as check_output:
            log = self.api.get_git_log()
        self.assertEqual(log, "Branch: main\n\ncommit abc123\n")
        self.assertEqual(check_output.call_args_list[1].args[0], ["git", "log", "-1"])

    def test_unencrypted_start_listens_on_8080_without_tls(self):
        with mock.patch.object(self.api.app, "listen") as listen:
            self.api.start()
        listen.assert_called_once_with(8080, ssl_options=None)

    def test_encrypted_start_without_certificates_falls_back_to_http(self):
        api = self.create_api(encrypted=True)
        with mock.patch.object(api_module.os.path, "exists", return_value=False):
            with mock.patch.object(api.app, "listen") as listen:
                api.start()
        listen.assert_called_once_with(8080, ssl_options=None)

    def test_encrypted_start_with_certificates_uses_tls_on_443(self):
        api = self.create_api(encrypted=True)
        with mock.patch.object(api_module.os.path, "exists", return_value=True):
            with mock.patch.object(api.app, "listen") as listen:
                api.start()
        listen.assert_called_once()
        self.assertEqual(listen.call_args.args, (443,))
        ssl_options = listen.call_args.kwargs["ssl_options"]
        self.assertTrue(ssl_options["certfile"].endswith("cert.crt"))
        self.assertTrue(ssl_options["keyfile"].endswith("cert.key"))

    def test_routes_cover_api_display_and_static_content(self):
        patterns = [
            rule.matcher.regex.pattern for rule in self.api.app.wildcard_router.rules
        ]
        for expected in (
            "/display$",
            "/api/config/?(.*)$",
            "/api/action/?(.*)$",
            "/api/system/?(.*)$",
            "/api/librespotify$",
            "/media/(.*)$",
            "/fonts/(.*)$",
            "/(.*)$",
        ):
            self.assertIn(expected, patterns)


if __name__ == "__main__":
    unittest.main()
