import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

from core.domain.events import (
    AlarmStoppedEvent,
    PlaybackChangedEvent,
    SpotifyStoppedEvent,
    VolumeChangeRequest,
    VolumeChangedEvent,
)
from core.domain.model import (
    FAILED_ALARM_ID,
    AlarmClockContext,
    AlarmDefinition,
    AlarmRecurrence,
    AudioEffect,
    AudioStream,
    Config,
    EnvironmentContext,
    LocationConfig,
    Mode,
    NextAlarmInfo,
    OfflineStream,
    PlaybackContent,
    RoomBrightness,
    SpotifyStream,
    StreamAudioEffect,
    VisualEffect,
    Weekday,
)
from resources.resources import alarms_dir
from utils.geolocation import GeoLocation, Weather

from tests.support import (
    RecordingEventBus,
    frozen_now,
    local_datetime,
    make_alarm,
    make_config,
    make_stream,
)


class RoomBrightnessTest(unittest.TestCase):

    def test_grayscale_thresholds(self):
        cases = {
            0.0: 0,
            0.005: 0,
            0.015: 3,
            0.03: 7,
            0.1: 10,
            0.15: 15,
            1.0: 15,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(RoomBrightness(value).get_grayscale_value(), expected)

    def test_grayscale_is_clamped_to_requested_range(self):
        self.assertEqual(RoomBrightness(0.0).get_grayscale_value(min_value=5), 5)
        self.assertEqual(RoomBrightness(1.0).get_grayscale_value(max_value=8), 8)

    def test_highly_dimmed_below_one_percent(self):
        self.assertTrue(RoomBrightness(0.009).is_highly_dimmed())
        self.assertFalse(RoomBrightness(0.01).is_highly_dimmed())

    def test_equality_compares_grayscale_steps_not_raw_values(self):
        self.assertEqual(RoomBrightness(0.5), RoomBrightness(0.9))
        self.assertNotEqual(RoomBrightness(0.5), RoomBrightness(0.1))
        self.assertFalse(RoomBrightness(0.5) != RoomBrightness(0.9))

    def test_value_is_callable(self):
        self.assertEqual(RoomBrightness(0.42)(), 0.42)


class EnvironmentContextTest(unittest.TestCase):

    def test_defaults_to_offline(self):
        self.assertFalse(EnvironmentContext().is_online)
        self.assertTrue(EnvironmentContext(is_online=True).is_online)

    def test_setters_update_state(self):
        env = EnvironmentContext()
        weather = Weather(code=3, temperature=12.5)
        env.is_online = True
        env.is_daytime = not env.is_daytime
        env.current_weather = weather
        self.assertTrue(env.is_online)
        self.assertIs(env.current_weather, weather)
        self.assertIs(env.geo_location, GeoLocation())

    def test_current_weather_is_initially_none(self):
        self.assertIsNone(EnvironmentContext().current_weather)


class VisualEffectTest(unittest.TestCase):

    def _effect_with_minutes_left(self, minutes: float):
        now = local_datetime(2030, 1, 1, 6, 0)
        alarm = make_alarm()
        info = NextAlarmInfo(now + datetime.timedelta(minutes=minutes), alarm)
        return info, alarm.visual_effect, now

    def test_inactive_without_next_alarm(self):
        self.assertFalse(VisualEffect().is_active())

    def test_active_only_within_eight_minutes(self):
        for minutes, expected in [(30, False), (9, False), (8, True), (1, True)]:
            with self.subTest(minutes=minutes):
                _, effect, now = self._effect_with_minutes_left(minutes)
                with frozen_now(now):
                    self.assertEqual(effect.is_active(), expected)

    def test_style_gets_brighter_when_alarm_approaches(self):
        for minutes, background, foreground in [
            (1.5, 15, 0),
            (2, 15, 0),
            (3, 7, 0),
            (4, 7, 0),
            (7, 0, 15),
        ]:
            with self.subTest(minutes=minutes):
                _, effect, now = self._effect_with_minutes_left(minutes)
                with frozen_now(now):
                    style = effect.get_style()
                self.assertEqual(style.background_grayscale_16, background)
                self.assertEqual(style.foreground_grayscale_16, foreground)
                self.assertTrue(style.be_bold)

    def test_style_without_next_alarm_is_dark_background(self):
        style = VisualEffect().get_style()
        self.assertEqual((style.background_grayscale_16, style.foreground_grayscale_16), (0, 15))


class AudioStreamsTest(unittest.TestCase):

    def test_audio_stream_str(self):
        self.assertEqual(
            str(AudioStream("Radio", "http://x")),
            "stream_name: Radio, stream_url: http://x",
        )

    def test_offline_stream_points_into_alarm_sound_dir(self):
        stream = OfflineStream("beep.ogg")
        self.assertEqual(stream.stream_name, "Offline Audio")
        self.assertEqual(stream.stream_url, os.path.join(alarms_dir, "beep.ogg"))

    def test_spotify_stream_from_dict(self):
        stream = SpotifyStream(
            {
                "player_event": "track_changed",
                "name": "Song",
                "track_id": "t1",
                "artists": ["A", "B"],
            }
        )
        self.assertEqual(stream.stream_name, "Spotify: Song by A, B")
        self.assertEqual(stream.stream_url, "")
        self.assertEqual(stream.track_id, "t1")
        self.assertEqual(stream.player_event, "track_changed")

    def test_spotify_stream_with_single_artist_string(self):
        stream = SpotifyStream({"name": "Song", "artists": "Solo"})
        self.assertEqual(stream.stream_name, "Spotify: Song by Solo")

    def test_spotify_stream_only_keeps_first_line_of_multiline_values(self):
        stream = SpotifyStream({"name": "Song", "artists": "A\nB"})
        self.assertEqual(stream.stream_name, "Spotify: Song by A")

    def test_spotify_stream_defaults_when_event_is_missing(self):
        for event in (None, {}):
            with self.subTest(event=event):
                self.assertEqual(
                    SpotifyStream(event).stream_name, "Unknown Spotify Track"
                )

    def test_spotify_stream_from_plain_object(self):
        event = mock.Mock(spec=["name", "player_event"])
        event.name = "Obj"
        event.player_event = "playing"
        stream = SpotifyStream(event)
        self.assertEqual(stream.stream_name, "Spotify: Obj")
        self.assertIsNone(stream.track_id)

    def test_spotify_stream_str(self):
        stream = SpotifyStream({"name": "Song", "track_id": "t1"})
        self.assertEqual(str(stream), "track_name: Song, track_id: t1")


class AudioEffectTest(unittest.TestCase):

    def test_base_effect_has_no_title(self):
        effect = AudioEffect(0.5)
        self.assertIsNone(effect.title())
        self.assertEqual(str(effect), "volume: 0.5")

    def test_stream_effect_title_is_stream_name(self):
        effect = StreamAudioEffect(make_stream("Jazz"), 0.4)
        self.assertEqual(effect.title(), "Jazz")
        self.assertIn("Jazz", str(effect))
        self.assertIn("volume: 0.4", str(effect))


class AlarmDefinitionTest(unittest.TestCase):

    def test_alarm_label_longer_than_three_characters_is_rejected(self):
        alarm = AlarmDefinition()
        with self.assertRaises(ValueError):
            alarm.alarm_label = "ABCD"

    def test_alarm_label_accepts_short_and_none(self):
        alarm = AlarmDefinition()
        alarm.alarm_label = "ABC"
        self.assertEqual(alarm.alarm_label, "ABC")
        alarm.alarm_label = None
        self.assertIsNone(alarm.alarm_label)

    def test_recurring_detection(self):
        self.assertTrue(make_alarm(recurring=["MONDAY"]).is_recurring())
        self.assertFalse(make_alarm(recurring=[]).is_recurring())
        self.assertFalse(make_alarm(recurring=None).is_recurring())
        self.assertFalse(
            make_alarm(recurring=["MONDAY"], onetime=datetime.date(2030, 1, 1)).is_recurring()
        )

    def test_onetime_is_the_complement_of_recurring(self):
        self.assertTrue(make_alarm(onetime=datetime.date(2030, 1, 1)).is_onetime())
        self.assertFalse(make_alarm(recurring=["FRIDAY"]).is_onetime())

    def test_recurrence_property(self):
        self.assertEqual(
            make_alarm(recurring=["FRIDAY"]).recurrence, AlarmRecurrence.RECURRING
        )
        self.assertEqual(
            make_alarm(onetime=datetime.date(2030, 1, 1)).recurrence,
            AlarmRecurrence.ONETIME,
        )

    def test_recurrence_setter_to_recurring_defaults_to_monday(self):
        alarm = make_alarm(onetime=datetime.date(2030, 1, 1))
        alarm.recurrence = AlarmRecurrence.RECURRING
        self.assertEqual(alarm.recurring, [Weekday.MONDAY.name])
        self.assertIsNone(alarm.onetime)

    def test_recurrence_setter_to_onetime_uses_today(self):
        alarm = make_alarm(recurring=["MONDAY"])
        alarm.recurrence = AlarmRecurrence.ONETIME
        self.assertIsNone(alarm.recurring)
        self.assertEqual(alarm.onetime, datetime.date.today())

    def test_recurrence_setter_with_unknown_value_clears_both(self):
        alarm = make_alarm(recurring=["MONDAY"])
        alarm.recurrence = None
        self.assertIsNone(alarm.recurring)
        self.assertIsNone(alarm.onetime)

    def test_cron_args_for_recurring_alarm_use_zero_based_weekdays(self):
        alarm = make_alarm(hour=6, minute=15, recurring=["MONDAY", "WEDNESDAY", "SUNDAY"])
        self.assertEqual(
            alarm.get_cron_args(),
            {"day_of_week": "0,2,6", "hour": 6, "minute": 15},
        )

    def test_cron_args_for_onetime_alarm_span_one_day(self):
        day = datetime.date(2030, 5, 17)
        alarm = make_alarm(hour=6, minute=15, onetime=day)
        self.assertEqual(
            alarm.get_cron_args(),
            {
                "start_date": day,
                "end_date": day + datetime.timedelta(days=1),
                "hour": 6,
                "minute": 15,
            },
        )

    def test_time_string_is_zero_padded(self):
        self.assertEqual(make_alarm(hour=7, minute=5).to_time_string(), "07:05")
        self.assertEqual(make_alarm(hour=23, minute=59).to_time_string(), "23:59")

    def test_day_string_for_recurring_alarm_abbreviates_weekdays(self):
        alarm = make_alarm(recurring=["MONDAY", "THURSDAY"])
        self.assertEqual(alarm.to_day_string(), "Mo, Th")

    def test_day_string_for_onetime_alarm_is_iso_date(self):
        alarm = make_alarm(onetime=datetime.date(2030, 5, 17))
        self.assertEqual(alarm.to_day_string(), "2030-05-17")

    def test_set_future_date_later_today(self):
        alarm = make_alarm(recurring=["MONDAY"])
        with frozen_now(local_datetime(2030, 1, 10, 8, 0)):
            alarm.set_future_date(9, 30)
        self.assertEqual(alarm.onetime, datetime.date(2030, 1, 10))
        self.assertIsNone(alarm.recurring)

    def test_set_future_date_rolls_over_to_tomorrow_when_time_has_passed(self):
        alarm = make_alarm()
        with frozen_now(local_datetime(2030, 1, 10, 8, 0)):
            alarm.set_future_date(7, 0)
        self.assertEqual(alarm.onetime, datetime.date(2030, 1, 11))

    def test_audio_effect_volume_property(self):
        alarm = make_alarm(volume=0.3)
        self.assertEqual(alarm.audio_effect_volume, 0.3)
        alarm.audio_effect_volume = 0.6
        self.assertEqual(alarm.audio_effect.volume, 0.6)

    def test_audio_effect_volume_creates_effect_on_demand(self):
        alarm = AlarmDefinition()
        alarm.audio_effect = None
        self.assertIsNone(alarm.audio_effect_volume)
        alarm.audio_effect_volume = 0.5
        self.assertIsInstance(alarm.audio_effect, StreamAudioEffect)
        self.assertEqual(alarm.audio_effect_volume, 0.5)

    def test_serialize_roundtrip_preserves_alarm(self):
        alarm = make_alarm(id="x1", recurring=["TUESDAY"], label="WRK", fadein_in_secs=30)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "alarm.json")
            alarm.serialize(path)
            restored = AlarmDefinition.deserialize(path)
        self.assertEqual(restored.id, "x1")
        self.assertEqual(restored.recurring, ["TUESDAY"])
        self.assertEqual(restored.alarm_label, "WRK")
        self.assertEqual(restored.fadein_in_secs, 30)
        self.assertEqual(restored.audio_effect.audio_stream.stream_name, "Radio")
        self.assertEqual(restored.audio_effect.volume, 0.3)


class ConfigTest(unittest.TestCase):

    def setUp(self):
        self.original_location = GeoLocation().location_info
        self.addCleanup(GeoLocation().configure, self.original_location)

    def test_defaults_are_filled_in(self):
        config = Config()
        self.assertEqual(config.alarm_duration_in_mins, 60)
        self.assertEqual(config.clock_format_string, "%-H<blinkSegment>%M")
        self.assertEqual(config.blink_segment, ":")
        self.assertEqual(config.powernap_duration_in_mins, 18)
        self.assertEqual(config.pre_alarm_trigger_in_mins, 10)
        self.assertEqual(config.predefined_alarm_labels, [])
        self.assertIsInstance(config.location, LocationConfig)
        self.assertEqual(config.alarm_definitions, [])
        self.assertEqual(config.audio_streams, [])

    def test_ensure_valid_config_does_not_overwrite_existing_values(self):
        config = Config()
        config.alarm_duration_in_mins = 5
        config.ensure_valid_config()
        self.assertEqual(config.alarm_duration_in_mins, 5)

    def test_add_alarm_assigns_guid_when_id_is_missing(self):
        config = Config()
        for invalid_id in (None, "", 5):
            with self.subTest(id=invalid_id):
                alarm = make_alarm(id=invalid_id)
                config.add_alarm_definition(alarm)
                self.assertIsInstance(alarm.id, str)
                self.assertEqual(len(alarm.id), 32)

    def test_add_alarm_keeps_valid_id(self):
        config = Config()
        config.add_alarm_definition(make_alarm(id="keep"))
        self.assertEqual(config.alarm_definitions[0].id, "keep")

    def test_failed_alarm_id_is_replaced_on_add(self):
        config = Config()
        alarm = make_alarm(id=FAILED_ALARM_ID)
        config.add_alarm_definition(alarm)
        self.assertNotEqual(alarm.id, FAILED_ALARM_ID)

    def test_remove_alarm_definition(self):
        config = Config()
        config.add_alarm_definition(make_alarm(id="a"))
        config.add_alarm_definition(make_alarm(id="b"))
        config.remove_alarm_definition("a")
        self.assertEqual([a.id for a in config.alarm_definitions], ["b"])

    def test_remove_alarm_definition_with_none_or_unknown_id_is_noop(self):
        config = Config()
        config.add_alarm_definition(make_alarm(id="a"))
        config.remove_alarm_definition(None)
        config.remove_alarm_definition("zzz")
        self.assertEqual(len(config.alarm_definitions), 1)

    def test_update_alarm_definition_replaces_by_id(self):
        config = Config()
        config.add_alarm_definition(make_alarm(id="a", hour=6))
        config.update_alarm_definition(make_alarm(id="a", hour=9))
        self.assertEqual(len(config.alarm_definitions), 1)
        self.assertEqual(config.get_alarm_definition_by_id("a").hour, 9)

    def test_alarm_lookup(self):
        config = Config()
        self.assertIsNone(config.get_default_alarm_definition())
        self.assertIsNone(config.get_alarm_definition_by_id("nope"))
        config.add_alarm_definition(make_alarm(id="a"))
        config.add_alarm_definition(make_alarm(id="b"))
        self.assertEqual(config.get_default_alarm_definition().id, "a")
        self.assertEqual(config.get_alarm_definition_by_id("b").id, "b")

    def test_audio_stream_management(self):
        config = Config()
        self.assertIsNone(config.get_default_audio_stream())
        first, second = make_stream("One", id="1"), make_stream("Two", id="2")
        config.add_audio_stream(first)
        config.add_audio_stream(second)
        self.assertIs(config.get_default_audio_stream(), first)
        self.assertIs(config.get_audio_stream_by_id("2"), second)
        self.assertIsNone(config.get_audio_stream_by_id("3"))
        config.remove_audio_stream("1")
        self.assertIs(config.get_default_audio_stream(), second)

    def test_add_audio_stream_assigns_guid(self):
        config = Config()
        stream = make_stream(id=None)
        config.add_audio_stream(stream)
        self.assertEqual(len(stream.id), 32)

    def test_normalize_alarm_ids_migrates_legacy_and_duplicate_ids(self):
        config = Config()
        config.alarm_definitions = [
            make_alarm(id=1),
            make_alarm(id="dup"),
            make_alarm(id="dup"),
            make_alarm(id=FAILED_ALARM_ID),
            make_alarm(id="ok"),
        ]
        config.normalize_alarm_ids()
        ids = [a.id for a in config.alarm_definitions]
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(ids[1], "dup")
        self.assertEqual(ids[4], "ok")
        self.assertTrue(all(isinstance(i, str) and i != FAILED_ALARM_ID for i in ids))

    def test_normalize_audio_stream_ids(self):
        config = Config()
        config.audio_streams = [make_stream(id=3), make_stream(id="s"), make_stream(id="s")]
        config.normalize_audio_stream_ids()
        ids = [s.id for s in config.audio_streams]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids[1], "s")

    def test_offline_stream_uses_configured_alarm_file(self):
        config = Config()
        config.local_alarm_file = "custom.ogg"
        self.assertEqual(
            config.get_offline_stream().stream_url,
            os.path.join(alarms_dir, "custom.ogg"),
        )

    def test_powernap_alarm_is_scheduled_in_the_future(self):
        config = make_config()
        with frozen_now(local_datetime(2030, 1, 10, 12, 0)):
            config.add_alarm_definition_for_powernap()
        alarm = config.alarm_definitions[0]
        self.assertEqual(alarm.alarm_name, "Powernap")
        self.assertEqual((alarm.hour, alarm.min), (12, 19))
        self.assertEqual(alarm.onetime, datetime.date(2030, 1, 10))
        self.assertTrue(alarm.is_active)
        self.assertIsNone(alarm.visual_effect)
        self.assertIs(alarm.audio_effect.audio_stream, config.audio_streams[0])
        self.assertEqual(alarm.audio_effect.volume, config.default_volume)

    def test_powernap_across_midnight_ends_up_on_next_day(self):
        config = make_config()
        with frozen_now(local_datetime(2030, 1, 10, 23, 50)):
            config.add_alarm_definition_for_powernap()
        alarm = config.alarm_definitions[0]
        self.assertEqual((alarm.hour, alarm.min), (0, 9))
        self.assertEqual(alarm.onetime, datetime.date(2030, 1, 11))

    def test_serialize_does_not_include_event_bus_and_restores_it(self):
        bus = RecordingEventBus()
        config = make_config(bus)
        payload = config.serialize()
        self.assertIs(config.event_bus, bus)
        self.assertIsNone(json.loads(payload)["event_bus"])

    def test_serialize_deserialize_roundtrip(self):
        config = make_config(streams=[make_stream("Jazz", id="s1")])
        config.add_alarm_definition(make_alarm(id="a1", recurring=["MONDAY"]))
        config.predefined_alarm_labels = ["WRK"]
        config.location = LocationConfig(
            city="Berlin", region="Berlin", timezone="Europe/Berlin", latitude=52.5, longitude=13.4
        )
        bus = RecordingEventBus()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w") as f:
                f.write(config.serialize())
            restored = Config.deserialize(path, bus)

        self.assertIs(restored.event_bus, bus)
        self.assertEqual(restored.audio_streams[0].stream_name, "Jazz")
        self.assertEqual(restored.alarm_definitions[0].recurring, ["MONDAY"])
        self.assertEqual(restored.predefined_alarm_labels, ["WRK"])
        self.assertEqual(GeoLocation().location_info.name, "Berlin")

    def test_deserialize_fills_in_missing_keys_and_normalizes_ids(self):
        config = make_config()
        config.add_alarm_definition(make_alarm(id="a1"))
        data = json.loads(config.serialize())
        del data["alarm_duration_in_mins"]
        data["alarm_definitions"][0]["id"] = 7
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w") as f:
                json.dump(data, f)
            restored = Config.deserialize(path)

        self.assertEqual(restored.alarm_duration_in_mins, 60)
        self.assertIsInstance(restored.alarm_definitions[0].id, str)


class AlarmClockContextTest(unittest.TestCase):

    def test_context_holds_config_and_environment(self):
        config = Config()
        context = AlarmClockContext(config, is_online=True)
        self.assertIs(context.config, config)
        self.assertTrue(context.environment.is_online)
        self.assertIsNone(context.mode_coordinator)
        self.assertIsNone(context.active_alarm_definition)


class PlaybackContentTest(unittest.TestCase):

    def setUp(self):
        self.bus = RecordingEventBus()
        self.config = make_config(self.bus)
        self.context = AlarmClockContext(self.config)
        self.sound_device = mock.MagicMock()
        self.sound_device.get_system_volume.return_value = 0.2
        self.playback = PlaybackContent(self.context, self.sound_device, self.bus)
        self.sound_device.set_system_volume.reset_mock()

    def test_initial_state_applies_default_volume(self):
        sound_device = mock.MagicMock()
        PlaybackContent(self.context, sound_device, self.bus)
        sound_device.set_system_volume.assert_called_once_with(self.config.default_volume)
        self.assertEqual(self.playback.playback_mode, Mode.Boot)
        self.assertIsNone(self.playback.audio_stream)

    def test_volume_is_rounded_to_five_percent_steps(self):
        self.sound_device.get_system_volume.return_value = 0.37
        self.assertAlmostEqual(self.playback.volume, 0.35)

    def test_relative_volume_increase_and_decrease(self):
        self.bus.emit(VolumeChangeRequest(relative=1))
        self.sound_device.set_system_volume.assert_called_with(mock.ANY)
        self.assertAlmostEqual(self.sound_device.set_system_volume.call_args[0][0], 0.25)

        self.bus.emit(VolumeChangeRequest(relative=-1))
        self.assertAlmostEqual(self.sound_device.set_system_volume.call_args[0][0], 0.15)

    def test_volume_is_clamped(self):
        self.sound_device.get_system_volume.return_value = 1.0
        self.bus.emit(VolumeChangeRequest(relative=1))
        self.assertAlmostEqual(self.sound_device.set_system_volume.call_args[0][0], 1.0)

        self.sound_device.get_system_volume.return_value = 0.0
        self.bus.emit(VolumeChangeRequest(relative=-1))
        self.assertAlmostEqual(self.sound_device.set_system_volume.call_args[0][0], 0.0)

    def test_absolute_volume_request(self):
        self.bus.emit(VolumeChangeRequest(absolute=0.5))
        self.sound_device.set_system_volume.assert_called_once_with(0.5)
        self.assertEqual(len(self.bus.emitted_of(VolumeChangedEvent)), 1)

    def test_zero_relative_volume_request_changes_nothing(self):
        self.bus.emit(VolumeChangeRequest(relative=0))
        self.sound_device.set_system_volume.assert_not_called()
        self.assertEqual(self.bus.emitted_of(VolumeChangedEvent), [])

    def test_volume_changed_event_is_emitted(self):
        self.bus.emit(VolumeChangeRequest(relative=1))
        events = self.bus.emitted_of(VolumeChangedEvent)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].new_volume, 0.2)

    def test_playback_change_sets_mode_stream_and_volume(self):
        stream = make_stream("Jazz")
        self.bus.emit(PlaybackChangedEvent(Mode.Music, stream, absolute_volume=0.4))
        self.assertEqual(self.playback.playback_mode, Mode.Music)
        self.assertIs(self.playback.audio_stream, stream)
        self.sound_device.set_system_volume.assert_called_once_with(0.4)

    def test_idle_playback_change_does_not_touch_volume(self):
        self.bus.emit(PlaybackChangedEvent(Mode.Idle, absolute_volume=0.4))
        self.sound_device.set_system_volume.assert_not_called()

    def test_leaving_alarm_mode_emits_alarm_stopped(self):
        alarm = make_alarm()
        self.context.active_alarm_definition = alarm
        self.bus.emit(PlaybackChangedEvent(Mode.Alarm))
        self.assertEqual(self.bus.emitted_of(AlarmStoppedEvent), [])
        self.bus.emit(PlaybackChangedEvent(Mode.Idle))
        stopped = self.bus.emitted_of(AlarmStoppedEvent)
        self.assertEqual(len(stopped), 1)
        self.assertIs(stopped[0].alarm_definition, alarm)

    def test_staying_in_alarm_mode_does_not_emit_alarm_stopped(self):
        self.bus.emit(PlaybackChangedEvent(Mode.Alarm))
        self.bus.emit(PlaybackChangedEvent(Mode.Alarm, make_stream("Offline")))
        self.assertEqual(self.bus.emitted_of(AlarmStoppedEvent), [])

    def test_leaving_spotify_mode_emits_spotify_stopped(self):
        self.bus.emit(PlaybackChangedEvent(Mode.Spotify))
        self.assertEqual(self.bus.emitted_of(SpotifyStoppedEvent), [])
        self.bus.emit(PlaybackChangedEvent(Mode.Music))
        self.assertEqual(len(self.bus.emitted_of(SpotifyStoppedEvent)), 1)

    def test_first_audio_stream_is_always_accepted(self):
        spotify = SpotifyStream({"player_event": "playing", "name": "x"})
        self.playback.set_audio_stream(spotify)
        self.assertIs(self.playback.audio_stream, spotify)

    def test_spotify_stream_only_replaces_current_stream_on_track_change(self):
        radio = make_stream("Radio")
        self.playback.set_audio_stream(radio)

        self.playback.set_audio_stream(SpotifyStream({"player_event": "playing"}))
        self.assertIs(self.playback.audio_stream, radio)

        changed = SpotifyStream({"player_event": "track_changed", "name": "n"})
        self.playback.set_audio_stream(changed)
        self.assertIs(self.playback.audio_stream, changed)

    def test_regular_stream_replaces_current_stream(self):
        self.playback.set_audio_stream(make_stream("One"))
        second = make_stream("Two")
        self.playback.set_audio_stream(second)
        self.assertIs(self.playback.audio_stream, second)


class NextAlarmInfoTest(unittest.TestCase):

    def test_exposes_alarm_data(self):
        alarm = make_alarm(label="WRK")
        run_time = local_datetime(2030, 1, 1, 7, 30)
        info = NextAlarmInfo(run_time, alarm)
        self.assertEqual(info.next_run_time, run_time)
        self.assertEqual(info.alarm_name, "Test Alarm")
        self.assertEqual(info.alarm_label, "WRK")
        self.assertIs(info.alarm_definition, alarm)
        self.assertIs(info.visual_effect, alarm.visual_effect)
        self.assertEqual(str(info), f"Test Alarm at {run_time}")

    def test_links_itself_into_visual_effect(self):
        alarm = make_alarm()
        info = NextAlarmInfo(local_datetime(2030, 1, 1, 7, 30), alarm)
        self.assertIs(alarm.visual_effect.next_alarm_info, info)

    def test_without_alarm_definition(self):
        info = NextAlarmInfo()
        self.assertIsNone(info.next_run_time)
        self.assertIsNone(info.alarm_label)
        self.assertIsNone(info.visual_effect)
        self.assertIsNone(info.alarm_definition)

    def test_alarm_without_visual_effect(self):
        alarm = make_alarm()
        alarm.visual_effect = None
        info = NextAlarmInfo(local_datetime(2030, 1, 1, 7, 30), alarm)
        self.assertIsNone(info.visual_effect)

    def test_minutes_until_alarm_rounds_up(self):
        now = local_datetime(2030, 1, 1, 7, 0, 0)
        info = NextAlarmInfo(now + datetime.timedelta(minutes=5, seconds=1), make_alarm())
        with frozen_now(now):
            self.assertEqual(info.minutes_until_alarm(), 6)

    def test_minutes_until_alarm_is_exact_for_full_minutes(self):
        now = local_datetime(2030, 1, 1, 7, 0, 0)
        info = NextAlarmInfo(now + datetime.timedelta(minutes=5), make_alarm())
        with frozen_now(now):
            self.assertEqual(info.minutes_until_alarm(), 5)

    def test_minutes_until_alarm_without_run_time_is_huge(self):
        self.assertGreater(NextAlarmInfo(None, make_alarm()).minutes_until_alarm(), 10**6)


if __name__ == "__main__":
    unittest.main()
