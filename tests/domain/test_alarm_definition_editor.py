import datetime
import unittest

from core.domain.alarm_definition_editor import (
    AlarmDefinitionProperties,
    AlarmEditingService,
    AlarmEditingSession,
    AlarmProperty,
    DayPickerSession,
    EditorAction,
)
from core.domain.model import (
    AlarmClockContext,
    AlarmRecurrence,
    StreamAudioEffect,
    VisualEffect,
)

from tests.support import frozen_now, local_datetime, make_alarm, make_config, make_stream


class DayPickerSessionTest(unittest.TestCase):

    def test_starts_empty_on_first_day(self):
        picker = DayPickerSession(None)
        self.assertEqual(picker.cursor, 0)
        self.assertEqual(picker.active_days, set())
        self.assertEqual(picker.get_selected_days(), [])

    def test_navigation_wraps_around_including_ok_slot(self):
        picker = DayPickerSession([])
        picker.navigate(-1)
        self.assertEqual(picker.cursor, DayPickerSession.OK_INDEX)
        self.assertTrue(picker.is_on_ok())
        picker.navigate(1)
        self.assertEqual(picker.cursor, 0)

    def test_toggle_adds_and_removes_day(self):
        picker = DayPickerSession([])
        picker.toggle_current()
        self.assertEqual(picker.get_selected_days(), ["MONDAY"])
        picker.toggle_current()
        self.assertEqual(picker.get_selected_days(), [])

    def test_toggle_on_ok_slot_does_nothing(self):
        picker = DayPickerSession(["MONDAY"])
        picker.navigate(-1)
        picker.toggle_current()
        self.assertEqual(picker.get_selected_days(), ["MONDAY"])

    def test_selected_days_are_in_canonical_order(self):
        picker = DayPickerSession(["SUNDAY", "TUESDAY", "MONDAY"])
        self.assertEqual(picker.get_selected_days(), ["MONDAY", "TUESDAY", "SUNDAY"])

    def test_does_not_mutate_the_given_list(self):
        days = ["MONDAY"]
        picker = DayPickerSession(days)
        picker.navigate(1)
        picker.toggle_current()
        self.assertEqual(days, ["MONDAY"])


class AlarmDefinitionPropertiesTest(unittest.TestCase):

    def setUp(self):
        self.properties = AlarmDefinitionProperties()

    def test_value_lists(self):
        get = self.properties.get_editable_property
        self.assertEqual(get(AlarmProperty.HOUR).value_list, list(range(24)))
        self.assertEqual(get(AlarmProperty.MIN).value_list, list(range(60)))
        self.assertEqual(get(AlarmProperty.IS_ACTIVE).value_list, [True, False])
        self.assertEqual(
            get(AlarmProperty.RECURRENCE).value_list,
            [AlarmRecurrence.ONETIME, AlarmRecurrence.RECURRING],
        )
        self.assertEqual(get(AlarmProperty.FADE_IN).value_list[:3], [0, 10, 20])
        self.assertEqual(get(AlarmProperty.FADE_IN).value_list[-1], 300)
        volumes = get(AlarmProperty.AUDIO_EFFECT_VOLUME).value_list
        self.assertEqual(len(volumes), 21)
        self.assertAlmostEqual(volumes[-1], 1.0)

    def test_onetime_values_start_with_none_followed_by_next_30_days(self):
        values = self.properties.get_editable_property(AlarmProperty.ONETIME).value_list
        self.assertIsNone(values[0])
        self.assertEqual(len(values), 31)
        self.assertEqual(values[1], datetime.date.today())

    def test_properties_to_edit_for_onetime_alarm(self):
        props = self.properties.get_properties_to_edit(make_alarm(onetime=datetime.date(2030, 1, 1)))
        self.assertIn(AlarmProperty.ONETIME, props)
        self.assertNotIn(AlarmProperty.RECURRING, props)

    def test_properties_to_edit_for_recurring_alarm(self):
        props = self.properties.get_properties_to_edit(make_alarm(recurring=["MONDAY"]))
        self.assertIn(AlarmProperty.RECURRING, props)
        self.assertNotIn(AlarmProperty.ONETIME, props)

    def test_properties_to_edit_order(self):
        props = self.properties.get_properties_to_edit(make_alarm(recurring=["MONDAY"]))
        self.assertEqual(
            props,
            [
                AlarmProperty.IS_ACTIVE,
                AlarmProperty.HOUR,
                AlarmProperty.MIN,
                AlarmProperty.RECURRENCE,
                AlarmProperty.RECURRING,
                AlarmProperty.AUDIO_EFFECT,
                AlarmProperty.AUDIO_EFFECT_VOLUME,
                AlarmProperty.FADE_IN,
                AlarmProperty.VISUAL_EFFECT,
                AlarmProperty.ALARM_LABEL,
            ],
        )

    def test_update_value_lists_from_config(self):
        config = make_config(streams=[make_stream("One", id="1"), make_stream("Two", id="2")])
        config.predefined_alarm_labels = ["WRK", "GYM"]
        self.properties.update_value_lists(config, volume=0.4)

        effects = self.properties.get_editable_property(AlarmProperty.AUDIO_EFFECT).value_list
        self.assertEqual([e.title() for e in effects], ["One", "Two"])
        self.assertTrue(all(e.volume == 0.4 for e in effects))
        labels = self.properties.get_editable_property(AlarmProperty.ALARM_LABEL).value_list
        self.assertEqual(labels, [None, "WRK", "GYM"])

    def test_update_value_lists_tolerates_missing_labels(self):
        config = make_config()
        config.predefined_alarm_labels = None
        self.properties.update_value_lists(config, volume=0.1)
        labels = self.properties.get_editable_property(AlarmProperty.ALARM_LABEL).value_list
        self.assertEqual(labels, [None])


class AlarmEditingSessionTest(unittest.TestCase):

    def setUp(self):
        self.stream = make_stream("One", id="1")
        self.config = make_config(streams=[self.stream, make_stream("Two", id="2")])
        self.alarm = make_alarm(id="a1", hour=7, minute=30, onetime=datetime.date(2030, 1, 1))
        self.session = AlarmEditingSession(self.alarm, self.config)

    def goto(self, prop):
        for _ in range(20):
            if self.session.current_property == prop:
                return
            self.session.navigate_property(1)
        self.fail(f"property {prop} not reachable")

    def test_works_on_a_copy_of_the_alarm(self):
        self.assertIsNot(self.session.draft_alarm, self.alarm)
        self.goto(AlarmProperty.HOUR)
        self.session.change_property_value(11)
        self.assertEqual(self.session.draft_alarm.hour, 11)
        self.assertEqual(self.alarm.hour, 7)

    def test_starts_on_is_active_property(self):
        self.assertEqual(self.session.current_property, AlarmProperty.IS_ACTIVE)
        self.assertFalse(self.session.is_on_action)

    def test_property_navigation_wraps_and_ends_with_actions(self):
        self.session.navigate_property(-1)
        self.assertEqual(self.session.current_property, EditorAction.CANCEL)
        self.assertTrue(self.session.is_on_action)
        self.session.navigate_property(-1)
        self.assertEqual(self.session.current_property, EditorAction.COMMIT)
        self.session.navigate_property(2)
        self.assertEqual(self.session.current_property, AlarmProperty.IS_ACTIVE)

    def test_actions_have_no_values_and_cannot_be_changed(self):
        self.session.navigate_property(-1)
        self.assertEqual(self.session.get_property_values(), [])
        self.assertIsNone(self.session.get_current_value())
        self.session.change_property_value(5)
        self.session.navigate_value(1)
        self.assertFalse(self.session.should_enter_value_edit_mode())
        self.assertTrue(self.session.draft_alarm.is_active)

    def test_navigate_value_cycles_through_value_list(self):
        self.goto(AlarmProperty.HOUR)
        self.session.navigate_value(1)
        self.assertEqual(self.session.draft_alarm.hour, 8)
        self.session.navigate_value(-1)
        self.session.navigate_value(-1)
        self.assertEqual(self.session.draft_alarm.hour, 6)

    def test_navigate_value_wraps_around(self):
        self.goto(AlarmProperty.HOUR)
        self.session.change_property_value(23)
        self.session.navigate_value(1)
        self.assertEqual(self.session.draft_alarm.hour, 0)

    def test_navigate_value_starts_at_first_when_current_not_in_list(self):
        self.goto(AlarmProperty.FADE_IN)
        self.session.change_property_value(7)
        self.session.navigate_value(1)
        self.assertEqual(self.session.draft_alarm.fadein_in_secs, 10)

    def test_changing_recurrence_rebuilds_property_list(self):
        self.goto(AlarmProperty.RECURRENCE)
        self.session.change_property_value(AlarmRecurrence.RECURRING)
        self.assertEqual(self.session.draft_alarm.recurrence, AlarmRecurrence.RECURRING)
        self.session.navigate_property(1)
        self.assertEqual(self.session.current_property, AlarmProperty.RECURRING)

    def test_toggle_properties_do_not_enter_value_edit_mode(self):
        self.assertFalse(self.session.should_enter_value_edit_mode())
        self.goto(AlarmProperty.HOUR)
        self.assertTrue(self.session.should_enter_value_edit_mode())

    def test_day_picker_lifecycle(self):
        self.session.draft_alarm.recurrence = AlarmRecurrence.RECURRING
        self.session.start_day_picker()
        picker = self.session.day_picker_session
        self.assertEqual(picker.get_selected_days(), ["MONDAY"])
        picker.navigate(2)
        picker.toggle_current()
        self.session.confirm_day_picker()
        self.assertIsNone(self.session.day_picker_session)
        self.assertEqual(self.session.draft_alarm.recurring, ["MONDAY", "WEDNESDAY"])

    def test_cancel_day_picker_keeps_draft_untouched(self):
        self.session.draft_alarm.recurrence = AlarmRecurrence.RECURRING
        self.session.start_day_picker()
        self.session.day_picker_session.toggle_current()
        self.session.cancel_day_picker()
        self.assertIsNone(self.session.day_picker_session)
        self.assertEqual(self.session.draft_alarm.recurring, ["MONDAY"])

    def test_confirm_without_day_picker_is_noop(self):
        self.session.confirm_day_picker()
        self.assertIsNone(self.session.draft_alarm.recurring)

    def test_commit_returns_draft(self):
        self.assertIs(self.session.commit(), self.session.draft_alarm)


class AlarmEditingServiceTest(unittest.TestCase):

    def setUp(self):
        self.config = make_config()
        self.context = AlarmClockContext(self.config)
        self.service = AlarmEditingService(self.context)

    def add_alarm(self, **kwargs):
        alarm = make_alarm(onetime=datetime.date(2030, 1, 1), **kwargs)
        self.config.add_alarm_definition(alarm)
        return alarm

    def test_new_alarm_template_when_no_alarms_exist(self):
        with frozen_now(local_datetime(2030, 1, 10, 14, 45)):
            alarm = self.service.current_alarm
        self.assertIsNone(alarm.id)
        self.assertEqual(alarm.alarm_name, "New Alarm")
        self.assertEqual((alarm.hour, alarm.min), (14, 45))
        self.assertTrue(alarm.is_active)
        self.assertEqual(alarm.onetime, datetime.date(2030, 1, 10))
        self.assertIsNone(alarm.recurring)
        self.assertIsInstance(alarm.visual_effect, VisualEffect)
        self.assertIs(alarm.audio_effect.audio_stream, self.config.audio_streams[0])
        self.assertEqual(alarm.audio_effect.volume, self.config.default_volume)

    def test_new_alarm_template_without_audio_streams_has_no_audio_effect(self):
        self.config.audio_streams = []
        alarm = self.service.current_alarm
        self.assertFalse(hasattr(alarm, "audio_effect") and alarm.audio_effect)

    def test_alarm_navigation_includes_slot_for_new_alarm(self):
        first, second = self.add_alarm(id="a"), self.add_alarm(id="b")
        self.assertIs(self.service.current_alarm, first)
        self.service.navigate_alarms(1)
        self.assertIs(self.service.current_alarm, second)
        self.service.navigate_alarms(1)
        self.assertIsNone(self.service.current_alarm.id)
        self.service.navigate_alarms(1)
        self.assertEqual(self.service.current_alarm_index, 0)
        self.service.navigate_alarms(-1)
        self.assertEqual(self.service.current_alarm_index, 2)

    def test_not_editing_by_default(self):
        self.assertIsNone(self.service.editing_session)
        self.assertIsNone(self.service.property_to_edit)
        self.assertFalse(self.service.is_in_edit_mode([AlarmProperty.HOUR]))
        self.assertIsNone(self.service.commit_changes())
        self.assertFalse(self.service.start_property_value_editing())

    def test_alarm_in_editing_is_current_alarm_until_session_starts(self):
        alarm = self.add_alarm(id="a")
        self.assertIs(self.service.alarm_definition_in_editing, alarm)
        self.service.start_editing()
        self.assertIs(
            self.service.alarm_definition_in_editing, self.service.editing_session.draft_alarm
        )
        self.assertIsNot(self.service.alarm_definition_in_editing, alarm)

    def test_navigating_properties_and_values_requires_a_session(self):
        self.add_alarm(id="a")
        self.service.navigate_properties(1)
        self.service.navigate_value_list(1)
        self.assertIsNone(self.service.property_to_edit)

    def test_property_navigation_and_edit_mode_detection(self):
        self.add_alarm(id="a")
        self.service.start_editing()
        self.assertEqual(self.service.property_to_edit, AlarmProperty.IS_ACTIVE)
        self.assertTrue(self.service.is_in_edit_mode([AlarmProperty.IS_ACTIVE]))
        self.assertFalse(self.service.is_in_edit_mode([AlarmProperty.HOUR]))
        self.service.navigate_properties(1)
        self.assertEqual(self.service.property_to_edit, AlarmProperty.HOUR)

    def test_start_property_value_editing_toggles_binary_properties(self):
        self.add_alarm(id="a")
        self.service.start_editing()
        self.assertFalse(self.service.start_property_value_editing())
        self.assertFalse(self.service.editing_session.draft_alarm.is_active)

    def test_start_property_value_editing_requests_edit_mode_for_lists(self):
        self.add_alarm(id="a")
        self.service.start_editing()
        self.service.navigate_properties(1)
        self.assertTrue(self.service.start_property_value_editing())

    def test_commit_existing_alarm_updates_config(self):
        self.add_alarm(id="a", hour=6)
        self.service.start_editing()
        self.service.navigate_properties(1)
        self.service.navigate_value_list(1)
        committed = self.service.commit_changes()
        self.assertEqual(committed.hour, 7)
        self.assertEqual(len(self.config.alarm_definitions), 1)
        self.assertEqual(self.config.get_alarm_definition_by_id("a").hour, 7)
        self.assertIsNone(self.service.editing_session)

    def test_commit_new_alarm_adds_it_with_generated_name_and_id(self):
        with frozen_now(local_datetime(2030, 1, 10, 9, 5)):
            self.service.start_editing()
            committed = self.service.commit_changes()
        self.assertEqual(committed.alarm_name, "Alarm at 09:05")
        self.assertIsNotNone(committed.id)
        self.assertEqual(self.config.alarm_definitions, [committed])

    def test_cancel_discards_session_and_keeps_config(self):
        alarm = self.add_alarm(id="a", hour=6)
        self.service.start_editing()
        self.service.navigate_properties(1)
        self.service.navigate_value_list(1)
        self.service.cancel_changes()
        self.assertIsNone(self.service.editing_session)
        self.assertEqual(self.config.alarm_definitions, [alarm])
        self.assertEqual(alarm.hour, 6)

    def test_cancel_without_session_is_noop(self):
        self.service.cancel_changes()
        self.assertIsNone(self.service.editing_session)


if __name__ == "__main__":
    unittest.main()
