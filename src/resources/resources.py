import json
import logging.config
import os

the_alarm_clock_protocol = "https"
the_alarm_clock_hostname = "localhost"
the_alarm_clock_port = 443

resources_dir = os.path.dirname(os.path.realpath(__file__))
app_dir = os.path.normpath(os.path.join(resources_dir, ".."))
media_dir = os.path.join(resources_dir, "media")

fonts_dir = f"{media_dir}/fonts"
icons_dir = f"{media_dir}/icons"
weather_icons_dir = f"{icons_dir}/weather"
sounds_dir = f"{media_dir}/sounds"
alarms_dir = f"{sounds_dir}/alarms"

librespotify_env_vars = [
    "PLAYER_EVENT",
    "TRACK_ID",
    "NAME",
    "ARTISTS",
    "ALBUM",
    "ALBUM_ARTISTS",
    "COVERS",
    "OLD_TRACK_ID",
    "DURATION_MS",
    "POSITION_MS",
    "VOLUME",
    "SINK_STATUS",
]

config_file = os.path.join(app_dir, "config.json")
webroot_file = os.path.join(app_dir, "core", "interface", "web", "template.html")
active_alarm_definition_file = f"/tmp/toc_active_alarm.json"
display_shot_file = os.path.join(app_dir, "..", "..", "display_test.png")
ssl_dir = os.path.join(app_dir, "../rpi/tls")

valid_mixer_device_simple_control_names = ["Digital", "Master"]

default_volume = 0.2


def init_logging():
    logging.config.dictConfig(
        json.load(open(os.path.join(resources_dir, "logging.json")))
    )
