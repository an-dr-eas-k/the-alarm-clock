import logging
import traceback
from core.domain.events import (
    PlaybackChangedEvent,
    ConfigChangedEvent,
    SpeakerErrorEvent,
    SpotifyApiEvent,
    StreamChangeRequest,
    ToggleAudioRequest,
    VolumeChangedEvent,
    WifiStatusChangedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    AudioStream,
    OfflineStream,
    PlaybackContent,
    Mode,
    SpotifyStream,
)
from core.interface.display.display_content import DisplayContent
from core.infrastructure.brightness_sensor import IBrightnessSensor
from core.infrastructure.event_bus import EventBus
from core.infrastructure.scheduler import SchedulerService
from utils.os_interactions import OSInteraction

logger = logging.getLogger("tac.core.application.basic_audio_service")


class BasicAudioService:
    scheduler_service: SchedulerService
    alarm_clock_context: AlarmClockContext

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        display_content: DisplayContent,
        playback_content: PlaybackContent,
        brightness_sensor: IBrightnessSensor,
        event_bus: EventBus,
        scheduler_service: SchedulerService,
        os_interaction: OSInteraction,
    ) -> None:
        self.alarm_clock_context = alarm_clock_context
        self.display_content = display_content
        self.playback_content = playback_content
        self.brightness_sensor = brightness_sensor
        self.event_bus = event_bus
        self.scheduler_service = scheduler_service
        self.os_interaction = os_interaction
        self.event_bus.on(ToggleAudioRequest)(self._toggle_stream)
        self.event_bus.on(StreamChangeRequest)(self._change_stream)
        self.event_bus.on(WifiStatusChangedEvent)(self._wifi_status_changed)
        self.event_bus.on(ConfigChangedEvent)(self._config_changed)
        self.event_bus.on(SpeakerErrorEvent)(self._handle_speaker_error)
        self.event_bus.on(SpotifyApiEvent)(self._spotify_stream_change_request)

    def _toggle_stream(self, _: ToggleAudioRequest):

        if self.playback_content.playback_mode != Mode.Idle:
            self.event_bus.emit(PlaybackChangedEvent(Mode.Idle))
            return

        audio_stream = self.alarm_clock_context.config.get_default_audio_stream()
        if (
            True
            and self.playback_content.audio_stream
            and isinstance(self.playback_content.audio_stream, AudioStream)
            and not isinstance(self.playback_content.audio_stream, OfflineStream)
        ):
            audio_stream = self.playback_content.audio_stream

        self.event_bus.emit(PlaybackChangedEvent(Mode.Music, audio_stream))

    def _change_stream(self, _: StreamChangeRequest):
        if self.playback_content.playback_mode != Mode.Music:
            return

        streams = self.alarm_clock_context.config.audio_streams
        if not streams:
            return

        current = self.playback_content.audio_stream
        idx = next((i for i, s in enumerate(streams) if s.id == current.id), -1)
        next_stream = streams[(idx + 1) % len(streams)]
        logger.info(f"Switching stream to: {next_stream}")
        self.event_bus.emit(PlaybackChangedEvent(Mode.Music, next_stream))

    def _spotify_stream_change_request(self, spotify_event: SpotifyApiEvent):

        spotify_stream = SpotifyStream(spotify_event.__dict__)

        if (
            False
            or (
                spotify_event.is_playback_started()
                and self.playback_content.playback_mode != Mode.Spotify
            )
            or spotify_event.is_track_changed()
        ):
            self.event_bus.emit(PlaybackChangedEvent(Mode.Spotify, spotify_stream))

        if (
            True
            and spotify_event.is_playback_stopped()
            and self.playback_content.playback_mode != Mode.Idle
        ):
            self._set_to_idle_mode()

        if (
            True
            and spotify_event.is_volume_changed()
            and self.playback_content.playback_mode == Mode.Spotify
        ):
            self.event_bus.emit(VolumeChangedEvent())

    def _set_to_idle_mode(self):
        if self.playback_content.playback_mode == Mode.Idle:
            return

        self.event_bus.emit(PlaybackChangedEvent(Mode.Idle))

    def get_room_brightness(self):
        return self.brightness_sensor.get_room_brightness()

    def _ignore_offline_stream_events(self, event: SpeakerErrorEvent):
        if event is not None and isinstance(event.audio_stream, OfflineStream):
            return True
        return False

    def _handle_speaker_error(self, event: SpeakerErrorEvent = None):
        if self._ignore_offline_stream_events(event):
            return
        if self.playback_content.playback_mode == Mode.Alarm:
            logger.warning("alarm error occurred: continuing with offline stream")
            self.event_bus.emit(
                PlaybackChangedEvent(
                    Mode.Alarm, self.alarm_clock_context.config.get_offline_stream()
                )
            )
        else:
            logger.warning("music playback error occurred: switching to idle mode")
            self._set_to_idle_mode()

    def _wifi_status_changed(self, event: WifiStatusChangedEvent):
        if event.is_online:
            if self.playback_content.playback_mode == Mode.Alarm:
                self.event_bus.emit(
                    PlaybackChangedEvent(
                        Mode.Alarm,
                        self.alarm_clock_context.active_alarm_definition.audio_effect.audio_stream,
                    )
                )
        else:
            if self.playback_content.playback_mode == Mode.Alarm:
                self.event_bus.emit(
                    PlaybackChangedEvent(
                        Mode.Alarm, self.alarm_clock_context.config.get_offline_stream()
                    )
                )

            if not event.is_online and self.playback_content.playback_mode in [
                Mode.Music,
                Mode.Spotify,
            ]:
                self._set_to_idle_mode()
