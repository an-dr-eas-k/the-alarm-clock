import logging
import traceback
import vlc
import time
import subprocess
import threading

from core.domain.events import (
    AudioStreamChangedEvent,
    SpeakerErrorEvent,
    SpeakerPlayingEvent,
)
from core.domain.model import (
    AlarmClockContext,
    PlaybackContent,
    AudioStream,
    Config,
    SpotifyStream,
    StreamAudioEffect,
)
from core.infrastructure.event_bus import EventBus
from resources.resources import init_logging, default_volume

logger = logging.getLogger("tac.audio")


class MediaPlayer:

    callbacks: dict = {}

    def play(self):
        pass

    def stop(self):
        pass

    def add_callback(self, event_type: vlc.EventType, callback: callable):
        self.callbacks[event_type] = callback


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
                (
                    "existing"  # dont call functions on the list_player when it is stopped like self.list_player.get_state()
                    if self.list_player is not None
                    else "destroyed"
                ),
            )
        except Exception as e:
            logger.error("callback error: %s", traceback.format_exc())

    def register_debug_callbacks(self):
        return
        for event_type in vlc.EventType._enum_names_:
            foo = vlc.EventType(event_type)
            self.add_callback(foo, self.callback_from_player)

    def play(self):
        if self.list_player is not None:
            return

        instance: vlc.Instance = vlc.Instance(
            ["--no-video", "--network-caching=3000", "--live-caching=3000"]
        )

        self.list_player: vlc.MediaListPlayer = instance.media_list_player_new()
        self.list_player.set_playback_mode(vlc.PlaybackMode.loop)
        media_player: vlc.MediaPlayer = self.list_player.get_media_player()

        media: vlc.Media = instance.media_new(self.url)

        media_list: vlc.MediaList = instance.media_list_new([])
        self.list_player.set_media_list(media_list)
        media_list.add_media(media)

        if logger.level == logging.DEBUG:
            self.register_debug_callbacks()

        self.add_callbacks(instance, media_player, media_list, media)

        logger.info("starting audio %s", self.url)
        self.list_player.play()

    def add_callbacks(
        self,
        instance: vlc.Instance,
        media_player: vlc.MediaPlayer,
        media_list: vlc.MediaList,
        media: vlc.Media,
    ):
        for event_type, callback in self.callbacks.items():
            for event_manager_struct in (
                dict(em=instance.vlm_get_event_manager(), called_from="instance"),
                dict(em=media_player.event_manager(), called_from="media_player"),
                dict(em=self.list_player.event_manager(), called_from="list_player"),
                dict(em=media_list.event_manager(), called_from="media_list"),
                dict(em=media.event_manager(), called_from="media"),
            ):
                if event_manager_struct["em"] is not None and isinstance(
                    event_manager_struct["em"], vlc.EventManager
                ):
                    event_manager_struct["em"].event_attach(
                        event_type,
                        lambda x: threading.Thread(
                            target=callback,
                            args=(x, event_manager_struct["called_from"]),
                        ).start(),
                    )

    def stop(self):
        if self.list_player is None:
            return

        self.list_player.stop()
        self.list_player = None
        logger.info(f"stopped audio")


class Speaker:
    media_player: MediaPlayer = None
    fallback_player_proc: subprocess.Popen = None

    def __init__(
        self,
        event_bus: EventBus,
    ) -> None:
        self.threadLock = threading.Lock()
        self.event_bus = event_bus
        self.event_bus.on(AudioStreamChangedEvent)(self._audio_stream_changed)

    def _audio_stream_changed(self, event: AudioStreamChangedEvent):
        if isinstance(event.audio_stream, SpotifyStream):
            self.adjust_streaming(None)
            return

        self.adjust_streaming(event.audio_stream)

    def adjust_streaming(self, audio_stream: AudioStream):
        self.threadLock.acquire(True)

        if audio_stream is not None:
            self.start_streaming(audio_stream)
        else:
            self.stop_streaming()

        self.threadLock.release()

    def get_player(self, audio_stream: AudioStream) -> MediaPlayer:
        player: MediaPlayer = MediaListPlayer(audio_stream.stream_url)
        player.add_callback(
            vlc.EventType.MediaPlayerEncounteredError, self.handle_player_error
        )
        return player

    def handle_player_error(self, *args):
        logger.info("handling player error: %s", args)
        self.adjust_streaming(None)
        self.event_bus.emit(SpeakerErrorEvent())

    def handle_player_playing(self):
        logger.info("handling player playing")
        self.event_bus.emit(SpeakerPlayingEvent())

    def start_streaming(self, audio_stream: AudioStream):
        try:
            self.stop_streaming()
            self.media_player = self.get_player(audio_stream)
            self.media_player.play()
        except Exception as e:
            logger.error("error: %s", traceback.format_exc())
            self.handle_player_error()

    def stop_streaming(self):
        if self.media_player is not None:
            self.media_player.stop()
        self.media_player = None


def main():
    c = Config()
    c.offline_alarm = AudioStream(
        stream_name="Offline Alarm", stream_url="Enchantment.ogg"
    )
    pc = PlaybackContent(AlarmClockContext(c))
    pc.audio_stream = StreamAudioEffect(
        volume=default_volume,
        audio_stream=AudioStream(
            stream_name="test", stream_url="https://streams.br.de/bayern2sued_2.m3u"
        ),
    )
    s = Speaker(pc, c)
    s.adjust_streaming(pc.audio_stream)
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
