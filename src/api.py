import base64
import io
import logging
import os
import json
import subprocess
import traceback
import tornado
import tornado.web
from PIL.Image import Image
from controls import Controls
from display import ColorType, Display

from domain import (
    AlarmDefinition,
    AudioEffect,
    AudioStream,
    Config,
    LibreSpotifyEvent,
    PlaybackContent,
    StreamAudioEffect,
    VisualEffect,
    Weekday,
    try_update,
)
from gpi import get_room_brightness
from utils.os import reboot_system, shutdown_system

logger = logging.getLogger("tac.api")


def split_path_arguments(path) -> tuple[str, int, str]:
    path_args = path[0].split("/")
    return (
        path_args[0],
        int(path_args[1]) if len(path_args) > 1 else None,
        path_args[2] if len(path_args) > 2 else None,
    )


class LibreSpotifyEventHandler(tornado.web.RequestHandler):

    def initialize(self, playback_content: PlaybackContent) -> None:
        self.playback_content = playback_content

    def post(self):
        try:
            body = (
                "{}"
                if self.request.body is None or len(self.request.body) == 0
                else self.request.body
            )
            spotify_event_payload: dict[str, str] = tornado.escape.json_decode(body)

            spotify_event_dict = {
                key: value for key, value in spotify_event_payload.items()
            }

            spotify_event = LibreSpotifyEvent(spotify_event_dict)
            logger.info("received librespotify event %s", spotify_event)
            self.playback_content.set_spotify_event(spotify_event)
        except:
            logger.warning("%s", traceback.format_exc())
        self.finish()


class DisplayHandler(tornado.web.RequestHandler):

    def initialize(self, display: Display) -> None:
        self.display = display

    def get(self):
        buffered = io.BytesIO()
        img = self.display.current_display_image
        assert isinstance(img, Image)
        img.save(buffered, format="png")
        img.seek(0)
        img_str = base64.b64encode(buffered.getvalue())
        my_html = '<img src="data:image/png;base64, {}">'.format(
            img_str.decode("utf-8")
        )
        self.write(my_html)


class ConfigHandler(tornado.web.RequestHandler):

    root = os.path.join(os.path.dirname(__file__), "webroot")

    def initialize(self, config: Config, api) -> None:
        self.config = config
        self.api = api

    def get(self, *args, **kwargs):
        try:
            self.render(f"{self.root}/alarm.html", config=self.config, api=self.api)
        except:
            logger.warning("%s", traceback.format_exc())


class ActionApiHandler(tornado.web.RequestHandler):

    def initialize(self, controls: Controls) -> None:
        self.controls = controls

    def post(self, *args):
        try:
            (type, id, _1) = split_path_arguments(args)

            if type == "play":
                self.controls.play_stream_by_id(id)
            elif type == "stop":
                self.controls.set_to_idle_mode()
            elif type == "volume":
                if id == 1:
                    self.controls.increase_volume()
                else:
                    self.controls.decrease_volume()
            elif type == "update":
                os._exit(0)
            elif type == "reboot":
                reboot_system()
            elif type == "shutdown":
                shutdown_system()
            else:
                logger.warning("Unknown action: %s", type)

        except:
            logger.warning("%s", traceback.format_exc())


class ConfigApiHandler(tornado.web.RequestHandler):

    def initialize(self, config: Config) -> None:
        self.config = config

    def get(self):
        try:
            self.set_header("Content-Type", "application/json")
            self.write(self.config.serialize())
        except:
            logger.warning("%s", traceback.format_exc())

    def delete(self, *args):
        try:
            (type, id, _) = split_path_arguments(args)
            if type == "alarm":
                self.config.remove_alarm_definition(id)
            elif type == "stream":
                self.config.remove_audio_stream(id)
        except:
            logger.warning("%s", traceback.format_exc())

    def post(self, *args):
        try:
            (type, id, property) = split_path_arguments(args)
            simpleValue = tornado.escape.to_unicode(self.request.body)
            if try_update(self.config, type, simpleValue):
                return
            alarmDef = self.config.get_alarm_definition(id)
            if (
                True
                and alarmDef is not None
                and try_update(alarmDef, property, simpleValue)
            ):
                self.config.remove_alarm_definition(id)
                self.config.add_alarm_definition(alarmDef)
                return

            body = (
                "{}"
                if self.request.body is None or len(self.request.body) == 0
                else self.request.body
            )
            form_arguments = tornado.escape.json_decode(body)
            if type == "alarm":
                self.config.add_alarm_definition(
                    self.parse_alarm_definition(form_arguments)
                )
            elif type == "stream":
                self.config.add_audio_stream(
                    self.parse_stream_definition(form_arguments)
                )
            elif type == "start_powernap":
                self.config.add_alarm_definition_for_powernap()
        except:
            logger.warning("%s", traceback.format_exc())

    def parse_stream_definition(self, form_arguments) -> AlarmDefinition:
        stream_name = form_arguments["streamName"]
        stream_url = form_arguments["streamUrl"]
        return AudioStream(stream_name=stream_name, stream_url=stream_url)

    def parse_visual_effect(self, form_arguments) -> VisualEffect:
        use_visual_effect = (
            form_arguments.get("visualEffectActive") is not None
            and form_arguments["visualEffectActive"] == "on"
        )
        if use_visual_effect:
            return VisualEffect()
        return None

    def parse_audio_effect(self, form_arguments) -> AudioEffect:
        stream_id = int(form_arguments["streamId"])
        return StreamAudioEffect(
            stream_definition=self.config.get_audio_stream(stream_id),
            volume=float(form_arguments["volume"]),
        )

    def parse_alarm_definition(self, form_arguments) -> AlarmDefinition:
        ala = AlarmDefinition()
        ala.alarm_name = form_arguments["alarmName"]
        (ala.hour, ala.min) = map(int, form_arguments["time"].split(":"))
        ala.weekdays = None
        ala.date = None
        if form_arguments.get("weekdays") is not None:
            weekdays = form_arguments["weekdays"]
            if not isinstance(weekdays, list):
                weekdays = [weekdays]
            ala.weekdays = list(
                map(lambda weekday: Weekday[weekday.upper()].name, weekdays)
            )
        else:
            ala.set_future_date(ala.hour, ala.min)

        ala.audio_effect = self.parse_audio_effect(form_arguments)
        ala.visual_effect = self.parse_visual_effect(form_arguments)
        ala.is_active = (
            form_arguments.get("isActive") is not None
            and form_arguments["isActive"] == "on"
        )
        return ala


class Api:

    app: tornado.web.Application

    def __init__(self, controls: Controls, display: Display):
        self.controls = controls
        self.display = display
        handlers = [
            (r"/display", DisplayHandler, {"display": self.display}),
            (
                r"/api/config/?(.*)",
                ConfigApiHandler,
                {"config": self.controls.state.config},
            ),
            (r"/api/action/?(.*)", ActionApiHandler, {"controls": self.controls}),
            (
                r"/api/librespotify",
                LibreSpotifyEventHandler,
                {"playback_content": self.controls.playback_content},
            ),
            (
                r"/(.*)",
                ConfigHandler,
                {"config": self.controls.state.config, "api": self},
            ),
        ]

        self.app = tornado.web.Application(handlers)

    def get_git_log(self) -> str:

        branch = "Branch: " + subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        ).decode("utf-8")

        log = subprocess.check_output(["git", "log", "-1"]).decode("utf-8")
        return f"{branch}\n{log}"

    def get_state_as_json(self) -> str:
        return json.dumps(
            obj=dict(
                room_brightness=get_room_brightness(),
                display=dict(
                    foreground_color=self.display.formatter.foreground_color(
                        color_type=ColorType.IN16
                    ),
                    background_color=self.display.formatter.background_color(
                        color_type=ColorType.IN16
                    ),
                ),
                is_online=self.controls.state.is_online,
                is_daytime=self.controls.state.is_daytime,
                geo_location=self.controls.state.geo_location.location_info.__dict__,
                playback_content=dict(
                    audio_effect=self.controls.playback_content.audio_effect.__str__(),
                    volume=self.controls.playback_content.volume,
                    mode=self.controls.state.mode.name,
                ),
                uptime=subprocess.check_output(["uptime"]).strip().decode("utf-8"),
            ),
            indent=2,
        )

    def start(self, port):
        self.app.listen(port)


if __name__ == "__main__":
    Api(8080).app.run()
