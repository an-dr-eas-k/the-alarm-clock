import logging
import traceback
import vlc
import time
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

from core.domain.events import (
    PlaybackChangedEvent,
    SpeakerErrorEvent,
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

logger = logging.getLogger("tac.core.infrastructure.audio")


class MediaPlayer:

    error_callback: callable = None

    def play(self):
        pass

    def stop(self):
        pass

    def set_error_callback(self, callback: callable):
        self.error_callback = callback


class MediaListPlayer(MediaPlayer):
    def __init__(
        self,
        audio_stream: AudioStream,
        instance: vlc.Instance,
        executor: ThreadPoolExecutor,
    ):
        self.audio_stream = audio_stream
        self.instance = instance
        self.executor = executor
        self.list_player = None
        self.media = None
        self.media_list = None
        self._stop_monitoring = threading.Event()
        self._monitoring_future = None

    def _monitor_playback(self):
        while not self._stop_monitoring.is_set():
            try:
                if self.list_player is not None:
                    state = self.list_player.get_state()
                    if state == vlc.State.Error:
                        stream_name = (
                            self.audio_stream.stream_name
                            if self.audio_stream is not None
                            else "None"
                        )
                        logger.warning(
                            "Monitor detected error state for stream: %s", stream_name
                        )
                        if self.error_callback:
                            self.error_callback(self.audio_stream, state)
                        break
            except Exception:
                logger.error("Error in playback monitor: %s", traceback.format_exc())

            self._stop_monitoring.wait(1.0)

    def play(self):
        if self.list_player is not None:
            return

        if self.audio_stream is None:
            logger.warning("no audio stream provided")
            return

        stream_url = self.audio_stream.stream_url

        try:
            self.list_player = self.instance.media_list_player_new()
            self.list_player.set_playback_mode(vlc.PlaybackMode.loop)

            self.media = self.instance.media_new(stream_url)
            self.media_list = self.instance.media_list_new([])
            self.list_player.set_media_list(self.media_list)
            self.media_list.add_media(self.media)

            self._stop_monitoring.clear()
            self._monitoring_future = self.executor.submit(self._monitor_playback)

            logger.info("starting audio %s", stream_url)
            self.list_player.play()
        except Exception:
            logger.error("Error starting playback: %s", traceback.format_exc())
            self.stop()

    def stop(self):
        if self._monitoring_future:
            self._stop_monitoring.set()
            self._monitoring_future = None

        if self.list_player:
            try:
                self.list_player.stop()
            except Exception:
                pass

            if self.media_list:
                self.media_list.release()
                self.media_list = None
            if self.media:
                self.media.release()
                self.media = None

            self.list_player.release()
            self.list_player = None

        logger.info(f"stopped audio")


class Speaker:
    media_player: MediaPlayer = None
    fallback_player_proc: subprocess.Popen = None

    def __init__(
        self,
        event_bus: EventBus,
        vlc_instance: vlc.Instance,
        executor: ThreadPoolExecutor,
    ) -> None:
        self.threadLock = threading.Lock()
        self.event_bus = event_bus
        self.event_bus.on(PlaybackChangedEvent)(self._playback_changed)
        self.vlc_instance = vlc_instance
        self.executor = executor

    def _playback_changed(self, event: PlaybackChangedEvent):
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
        player: MediaPlayer = MediaListPlayer(
            audio_stream, self.vlc_instance, self.executor
        )
        player.set_error_callback(self.handle_player_error)
        return player

    def handle_player_error(
        self, audio_stream: AudioStream, player_state: vlc.State, *_
    ):
        self.event_bus.emit(SpeakerErrorEvent(audio_stream))

    def start_streaming(self, audio_stream: AudioStream):
        try:
            self.stop_streaming()
            self.media_player = self.get_player(audio_stream)
            self.media_player.play()
        except Exception as e:
            logger.error("error: %s", traceback.format_exc())
            self.handle_player_error(audio_stream)

    def stop_streaming(self):
        if self.media_player is not None:
            self.media_player.stop()
        self.media_player = None


def main():
    eb = EventBus()
    instance = vlc.Instance(
        ["--no-video", "--network-caching=3000", "--live-caching=3000", "--aout=alsa"]
    )
    s = Speaker(eb, instance)
    stream = AudioStream(
        stream_name="test", stream_url="https://streams.br.de/bayern2sued_2.m3u"
    )
    s.adjust_streaming(stream)
    time.sleep(20)
    s.adjust_streaming(None)


def main_mlp():
    instance = vlc.Instance(["--aout=alsa"])
    stream = AudioStream(
        stream_name="test", stream_url="https://streams.br.de/bayern2sued_2.m3u"
    )
    mlp = MediaListPlayer(stream, instance)
    mlp.play()
    time.sleep(10)
    mlp.stop()


if __name__ == "__main__":
    init_logging()
    main()
