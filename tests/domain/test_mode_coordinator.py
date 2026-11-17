import datetime
import unittest

from core.domain.alarm_definition_editor import AlarmProperty, EditorAction
from core.domain.events import ConfigChangedEvent
from core.domain.mode_coordinator import AlarmClockModeCoordinator, ModeName
from core.domain.model import AlarmClockContext, AlarmRecurrence

from tests.support import RecordingEventBus, make_alarm, make_config


class ModeCoordinatorTest(unittest.TestCase):

    def setUp(self):
        self.bus = RecordingEventBus()
        self.config = make_config(self.bus)
        self.config.add_alarm_definition(
            make_alarm(id="a1", hour=6, onetime=datetime.date(2030, 1, 1))
        )
        self.context = AlarmClockContext(self.config)
        self.coordinator = AlarmClockModeCoordinator(self.bus, self.context)

    @property
    def mode(self):
        return self.coordinator.current_mode_name

    def to_alarm_edit(self):
        self.coordinator.handle_mode_button()
        self.coordinator.handle_invoke_button()

    def goto_property(self, prop):
        session = self.coordinator.editing_service.editing_session
        for _ in range(20):
            if session.current_property == prop:
                return
            self.coordinator.navigate_properties(1)
        self.fail(f"{prop} not reachable")

    def test_starts_in_default_mode_without_editing_service(self):
        self.assertEqual(self.mode, ModeName.DEFAULT)
        self.assertIsNone(self.coordinator.editing_service)

    def test_mode_button_enters_alarm_view_from_default(self):
        self.coordinator.handle_mode_button()
        self.assertEqual(self.mode, ModeName.ALARM_VIEW)
        self.assertIsNotNone(self.coordinator.editing_service)

    def test_invoke_in_default_mode_does_nothing(self):
        self.assertIsNone(self.coordinator.handle_invoke_button())
        self.assertEqual(self.mode, ModeName.DEFAULT)

    def test_invoke_in_alarm_view_starts_editing(self):
        self.to_alarm_edit()
        self.assertEqual(self.mode, ModeName.ALARM_EDIT)
        self.assertIsNotNone(self.coordinator.editing_service.editing_session)

    def test_mode_button_returns_to_default_from_other_modes(self):
        for steps in (0, 1):
            with self.subTest(steps=steps):
                self.coordinator.return_to_default_mode()
                self.coordinator.handle_mode_button()
                if steps:
                    self.coordinator.handle_invoke_button()
                self.coordinator.handle_mode_button()
                self.assertEqual(self.mode, ModeName.DEFAULT)
                self.assertIsNone(self.coordinator.editing_service)

    def test_enter_edit_mode_without_service_is_rejected(self):
        self.coordinator.enter_alarm_edit_mode()
        self.assertEqual(self.mode, ModeName.DEFAULT)

    def test_navigation_is_ignored_in_wrong_modes(self):
        self.coordinator.navigate_alarms(1)
        self.coordinator.navigate_properties(1)
        self.coordinator.navigate_property_values(1)
        self.coordinator.navigate_day_picker(1)
        self.coordinator.handle_mode_button()
        self.coordinator.navigate_properties(1)
        self.coordinator.navigate_property_values(1)
        self.assertEqual(self.coordinator.editing_service.current_alarm_index, 0)

    def test_navigate_alarms_in_alarm_view(self):
        self.coordinator.handle_mode_button()
        self.coordinator.navigate_alarms(1)
        self.assertEqual(self.coordinator.editing_service.current_alarm_index, 1)

    def test_navigate_properties_in_alarm_edit(self):
        self.to_alarm_edit()
        self.coordinator.navigate_properties(1)
        self.assertEqual(self.coordinator.editing_service.property_to_edit, AlarmProperty.HOUR)

    def test_property_edit_roundtrip_changes_value(self):
        self.to_alarm_edit()
        self.goto_property(AlarmProperty.HOUR)
        self.coordinator.handle_invoke_button()
        self.assertEqual(self.mode, ModeName.PROPERTY_EDIT)
        self.coordinator.navigate_property_values(1)
        self.coordinator.handle_invoke_button()
        self.assertEqual(self.mode, ModeName.ALARM_EDIT)
        self.assertEqual(self.coordinator.editing_service.alarm_definition_in_editing.hour, 7)

    def test_binary_property_is_toggled_without_entering_property_edit(self):
        self.to_alarm_edit()
        self.coordinator.handle_invoke_button()
        self.assertEqual(self.mode, ModeName.ALARM_EDIT)
        self.assertFalse(self.coordinator.editing_service.alarm_definition_in_editing.is_active)

    def test_commit_saves_alarm_and_emits_config_changed(self):
        self.to_alarm_edit()
        self.goto_property(AlarmProperty.HOUR)
        self.coordinator.navigate_property_values(1)
        self.coordinator.handle_invoke_button()
        self.coordinator.handle_invoke_button()
        self.goto_property(EditorAction.COMMIT)
        self.coordinator.handle_invoke_button()

        self.assertEqual(self.mode, ModeName.ALARM_VIEW)
        events = self.bus.emitted_of(ConfigChangedEvent)
        self.assertEqual(len(events), 1)
        self.assertIs(events[0].config, self.config)
        self.assertEqual(len(self.config.alarm_definitions), 1)

    def test_cancel_discards_changes_without_event(self):
        self.to_alarm_edit()
        self.coordinator.handle_invoke_button()
        self.goto_property(EditorAction.CANCEL)
        self.coordinator.handle_invoke_button()

        self.assertEqual(self.mode, ModeName.ALARM_VIEW)
        self.assertEqual(self.bus.emitted_of(ConfigChangedEvent), [])
        self.assertTrue(self.config.alarm_definitions[0].is_active)

    def make_recurring_and_open_day_picker(self):
        self.to_alarm_edit()
        self.goto_property(AlarmProperty.RECURRENCE)
        self.coordinator.editing_service.editing_session.change_property_value(
            AlarmRecurrence.RECURRING
        )
        self.goto_property(AlarmProperty.RECURRING)
        self.coordinator.handle_invoke_button()

    def test_recurring_property_opens_day_picker(self):
        self.make_recurring_and_open_day_picker()
        self.assertEqual(self.mode, ModeName.DAY_PICKER)
        self.assertIsNotNone(self.coordinator.editing_service.editing_session.day_picker_session)

    def test_day_picker_toggle_and_confirm(self):
        self.make_recurring_and_open_day_picker()
        self.coordinator.navigate_day_picker(1)
        self.coordinator.handle_invoke_button()
        self.coordinator.navigate_day_picker(-1)
        self.coordinator.navigate_day_picker(-1)
        self.assertTrue(
            self.coordinator.editing_service.editing_session.day_picker_session.is_on_ok()
        )
        self.coordinator.handle_invoke_button()

        self.assertEqual(self.mode, ModeName.ALARM_EDIT)
        draft = self.coordinator.editing_service.alarm_definition_in_editing
        self.assertEqual(draft.recurring, ["MONDAY", "TUESDAY"])

    def test_mode_button_cancels_day_picker(self):
        self.make_recurring_and_open_day_picker()
        self.coordinator.handle_invoke_button()
        self.coordinator.handle_mode_button()
        self.assertEqual(self.mode, ModeName.ALARM_EDIT)
        draft = self.coordinator.editing_service.alarm_definition_in_editing
        self.assertEqual(draft.recurring, ["MONDAY"])

    def test_mode_name_hash_uses_value(self):
        self.assertEqual(ModeName.DEFAULT.hash(), hash("default"))


if __name__ == "__main__":
    unittest.main()
