import logging.config
import os
import __main__ as main


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
    "OLD_TRACK_ID",
    "DURATION_MS",
    "POSITION_MS",
    "VOLUME",
    "SINK_STATUS",
]

config_file = os.path.join(app_dir, "config.json")
active_alarm_definition_file = f"/tmp/toc_active_alarm.json"
display_shot_file = os.path.join(app_dir, "..", "..", "display_test.png")

valid_mixer_device_simple_control_names = ["Digital", "Master"]

default_volume = 0.2


def init_logging():
    logging.config.fileConfig(os.path.join(resources_dir, "logging.conf"))
