import logging
import os
import traceback
import vlc
import time
import subprocess
import threading
from abc import ABC, abstractmethod

from core.domain.events import AudioEffectEvent
from core.domain.model import (
    AlarmClockContext,
    Mode,
    PlaybackContent,
    AudioEffect,
    AudioStream,
    Config,
    OfflineAudioEffect,
    StreamAudioEffect,
    TACEvent,
    TACEventSubscriber,
    SpotifyAudioEffect,
)
from core.infrastructure.event_bus import EventBus
from utils.network import is_internet_available
from resources.resources import alarms_dir, init_logging, default_volume

logger = logging.getLogger("tac.audio")

debug_callback: bool = True


class MediaPlayer:

    error_callback: callable

    def play(self):
        pass

    def stop(self):
        pass

    def set_error_callback(self, callback: callable):
        self.error_callback = callback


class SpotifyPlayer(MediaPlayer):

    def __init__(self, track_id: str):
        self.track_id = track_id


class IPlayerFactory(ABC):

    @abstractmethod
    def create_player(self, audio_effect: AudioEffect) -> MediaPlayer:
        pass

    @abstractmethod
    def create_fallback_player(self) -> MediaPlayer:
        pass


class MediaListPlayer(MediaPlayer):
    list_player: vlc.MediaListPlayer = None
    url: str

    def __init__(self, url: str):
        self.url = url
        self.list_player = None

    def callback_from_player(self, event: vlc.Event, *args):
        try:
            logger.debug(
                "callback called: %s, from %s, player state: %s",
                event.type,
                args[0],
                "unknown",
            )

            if event.type == vlc.EventType.MediaPlayerPlaying:
                pass

            if (
                True
                and event.type == vlc.EventType.MediaPlayerEncounteredError
                and super().error_callback is not None
            ):
                logger.info("vlc player error")
                threading.Thread(target=super().error_callback).start()
        except Exception as e:
            logger.error("callback error: %s", traceback.format_exc())

    def register_error_callback(
        self, event_manager: vlc.EventManager, called_from: str = None
    ):
        for event_type in vlc.EventType._enum_names_:
            event_manager.event_attach(
                vlc.EventType(event_type), self.callback_from_player, called_from
            )

    def play(self):
        if self.list_player is not None:
            return

        try:
            instance: vlc.Instance = vlc.Instance(
                ["--no-video", "--network-caching=3000", "--live-caching=3000"]
            )

            self.list_player: vlc.MediaListPlayer = instance.media_list_player_new()
            self.list_player.set_playback_mode(vlc.PlaybackMode.loop)
            media_player: vlc.MediaPlayer = self.list_player.get_media_player()
            media_player.event_manager().event_attach(
                vlc.EventType.MediaPlayerEncounteredError,
                self.callback_from_player,
                "media_player",
            )
            media_player.event_manager().event_attach(
                vlc.EventType.MediaPlayerPlaying,
                self.callback_from_player,
                "media_player",
            )

            media: vlc.Media = instance.media_new(self.url)

            media_list: vlc.MediaList = instance.media_list_new([])
            self.list_player.set_media_list(media_list)
            media_list.add_media(media)

            if debug_callback:
                for em_struct in [
                    dict(em=instance.vlm_get_event_manager(), name="instance"),
                    dict(em=self.list_player.event_manager(), name="list_player"),
                    dict(em=media_player.event_manager(), name="media_player"),
                    dict(em=media_list.event_manager(), name="media_list"),
                    dict(em=media.event_manager(), name="media"),
                ]:
                    self.register_error_callback(em_struct["em"], em_struct["name"])

            logger.info("starting audio %s", self.url)
            self.list_player.play()

        except Exception as e:
            logger.error("error: %s", traceback.format_exc())
            super().error_callback()

    def stop(self):
        if self.list_player is None:
            return

        self.list_player.stop()
        self.list_player = None
        logger.info(f"stopped audio")


class PlayerFactory(IPlayerFactory):

    def __init__(self, config: Config):
        self.config = config

    def create_player(self, audio_effect: AudioEffect) -> MediaPlayer:
        if isinstance(audio_effect, StreamAudioEffect):
            return MediaListPlayer(audio_effect.stream_definition.stream_url)
        elif isinstance(audio_effect, SpotifyAudioEffect):
            return SpotifyPlayer(audio_effect.track_id)
        elif isinstance(audio_effect, OfflineAudioEffect):
            return MediaListPlayer(audio_effect.stream_definition.stream_url)
        else:
            raise ValueError(
                f"Unknown audio effect type: {type(audio_effect).__name__}"
            )

    def create_fallback_player(self) -> MediaPlayer:
        return MediaListPlayer(
            self.config.get_offline_alarm_effect().stream_definition.stream_url
        )


class Speaker:
    media_player: MediaPlayer = None
    fallback_player_proc: subprocess.Popen = None

    def __init__(
        self,
        playback_content: PlaybackContent,
        config: Config,
        player_factory: IPlayerFactory,
        event_bus: EventBus,
    ) -> None:
        self.threadLock = threading.Lock()
        self.playback_content = playback_content
        self.config = config
        self.player_factory = player_factory
        self.event_bus = event_bus
        self.event_bus.on(AudioEffectEvent)(self._adjust_effect)

    def _adjust_effect(self, event: AudioEffectEvent):
        if event.audio_effect is not None:
            self.adjust_streaming(None)
            self.adjust_streaming(event.audio_effect)

    def adjust_streaming(self, audio_effect: AudioEffect):
        self.threadLock.acquire(True)

        if audio_effect is not None:
            self.start_streaming(audio_effect)
        else:
            self.stop_streaming()

        self.threadLock.release()

    def get_fallback_player(self) -> MediaPlayer:
        return self.player_factory.create_fallback_player()

    def get_player(self, audio_effect: AudioEffect) -> MediaPlayer:
        player: MediaPlayer = None
        if (
            not is_internet_available()
            and self.playback_content.alarm_clock_context.playback_mode == Mode.Alarm
        ):
            player = self.get_fallback_player()

        if player is None:
            player = self.player_factory.create_player(audio_effect)

        player.set_error_callback(self.handle_player_error)
        return player

    def handle_player_error(self):
        logger.info("handling player error")
        if self.playback_content.alarm_clock_context.playback_mode != Mode.Alarm:
            return

        if isinstance(self.playback_content.audio_effect, OfflineAudioEffect):
            self.start_streaming_alternative()
            return

        self.event_bus.emit(AudioEffectEvent(self.config.get_offline_audio_effect()))

    def start_streaming(self, audio_effect: AudioEffect):
        try:
            self.stop_streaming()
            self.media_player = self.get_player(audio_effect)
            self.media_player.play()
        except Exception as e:
            logger.error("error: %s", traceback.format_exc())
            self.handle_player_error()

    def start_streaming_alternative(self):
        self.adjust_streaming(None)
        logger.info("starting alternative fallback player")
        self.fallback_player_proc = subprocess.Popen(
            ["ogg123", "-r", os.path.join(alarms_dir, "fallback", "Timer.ogg")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_streaming(self):
        if self.fallback_player_proc is not None:
            self.fallback_player_proc.kill()
            logger.info("killed fallback player")
        self.fallback_player_proc = None

        if self.media_player is not None:
            self.media_player.stop()
        self.media_player = None


def main():
    c = Config()
    c.offline_alarm = AudioStream(
        stream_name="Offline Alarm", stream_url="Enchantment.ogg"
    )
    pc = PlaybackContent(AlarmClockContext(c))
    pc.audio_effect = StreamAudioEffect(
        volume=default_volume,
        stream_definition=AudioStream(
            stream_name="test", stream_url="https://streams.br.de/bayern2sued_2.m3u"
        ),
    )
    s = Speaker(pc, c)
    s.adjust_streaming(pc.audio_effect)
    time.sleep(20)
    s.adjust_streaming(None)


def main_mlp():
    def ecb(event: vlc.Event, *args):
        try:
            print(f"callback called: {event.type}, {args}")
            foo: vlc.MediaListPlayer = args[1]
            print(foo.get_state())
        except Exception as e:
            print(f"callback error: {e}")

    mlp = MediaListPlayer("foo", ecb)
    mlp.play()


if __name__ == "__main__":
    init_logging()
    main()
