from dataclasses import dataclass, field
from typing import List, Optional, Any

from core.domain.model import AlarmClockContext, StreamAudioEffect, VisualEffect
from utils.geolocation import GeoLocation


@dataclass
class EditingSession:
    alarm_index: int
    property_name: Optional[str] = None
    is_new: bool = False
    alarm_definition: Any = None  # AlarmDefinitionToEdit like object

    def properties(self) -> List[str]:
        if not self.alarm_definition:
            return []
        return self.alarm_definition.get_properties_to_edit()

    def current_value(self) -> Any:
        if not self.alarm_definition or not self.property_name:
            return None
        return getattr(self.alarm_definition, self.property_name)


class AlarmEditor:
    """Domain service handling alarm selection and editing independent of UI/hardware."""

    def __init__(self, context: AlarmClockContext):
        self._context = context
        self._session: Optional[EditingSession] = None
        self._alarm_index: int = 0

    # Selection / viewing
    def select_next_alarm(self) -> int:
        if self._alarm_index < len(self._context.config.alarm_definitions):
            self._alarm_index += 1
        else:
            self._alarm_index = 0
        return self._alarm_index

    def select_previous_alarm(self) -> int:
        if self._alarm_index > 0:
            self._alarm_index -= 1
        else:
            self._alarm_index = len(self._context.config.alarm_definitions)
        return self._alarm_index

    def current_alarm_index(self) -> int:
        return self._alarm_index

    def build_alarm_for_index(self, index: int):
        from core.interface.display.editor.alarm_definition_editor import (
            AlarmDefinitionToEdit,
        )

        if index < len(self._context.config.alarm_definitions):
            return AlarmDefinitionToEdit(self._context.config.alarm_definitions[index])
        # create new
        now = GeoLocation().now()
        ad = AlarmDefinitionToEdit()
        ad.id = None
        ad.alarm_name = "New Alarm"
        ad.hour = now.hour
        ad.min = now.minute
        ad.is_active = True
        ad.recurring = None
        ad.onetime = now.date()
        if len(self._context.config.audio_streams) > 0:
            ad.audio_effect = StreamAudioEffect(
                stream_definition=self._context.config.audio_streams[0],
                volume=self._context.config.default_volume,
            )
        ad.visual_effect = VisualEffect()
        return ad

    # Editing lifecycle
    def start_edit(self):
        alarm_def = self.build_alarm_for_index(self._alarm_index)
        is_new = alarm_def.id is None
        self._session = EditingSession(
            alarm_index=self._alarm_index,
            is_new=is_new,
            alarm_definition=alarm_def,
        )
        # focus first property
        props = self._session.properties()
        if props:
            self._session.property_name = props[0]
        return self._session

    def ensure_session(self):
        if not self._session:
            raise RuntimeError("No active editing session")
        return self._session

    def focus_next_property(self):
        s = self.ensure_session()
        props = s.properties()
        if not props:
            return None
        idx = props.index(s.property_name)
        s.property_name = props[(idx + 1) % len(props)]
        return s.property_name

    def focus_previous_property(self):
        s = self.ensure_session()
        props = s.properties()
        if not props:
            return None
        idx = props.index(s.property_name)
        s.property_name = props[(idx - 1) % len(props)]
        return s.property_name

    def focus_next_value(self):
        s = self.ensure_session()
        ep = s.alarm_definition.get_editable_property(s.property_name)
        values = ep.value_list
        current = getattr(s.alarm_definition, s.property_name)
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        new_val = values[(idx + 1) % len(values)]
        setattr(s.alarm_definition, s.property_name, new_val)
        return new_val

    def focus_previous_value(self):
        s = self.ensure_session()
        ep = s.alarm_definition.get_editable_property(s.property_name)
        values = ep.value_list
        current = getattr(s.alarm_definition, s.property_name)
        idx = values.index(current) if current in values else 0
        new_val = values[idx - 1 if idx - 1 >= 0 else len(values) - 1]
        setattr(s.alarm_definition, s.property_name, new_val)
        return new_val

    def commit(self):
        s = self.ensure_session()
        ad = s.alarm_definition
        if ad.id is None:
            ad.alarm_name = "Alarm at " + ad.to_time_string()
            self._context.config.add_alarm_definition(ad)
            # update index to point to newly added alarm (at end)
            self._alarm_index = len(self._context.config.alarm_definitions) - 1
        else:
            self._context.config.update_alarm_definition(ad)
        self._session = None
        return ad

    def cancel(self):
        self.ensure_session()
        self._session = None

    def session(self) -> Optional[EditingSession]:
        return self._session
