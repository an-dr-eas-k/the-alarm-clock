from collections import namedtuple
import logging
import math
import threading
from typing import Tuple
import alsaaudio
from resources import resources

logger = logging.getLogger("tac.sound_device")


Algorithm = namedtuple(
    "Algorithm", ["name", "volume_db", "min_volume_db", "max_volume_db"]
)


class SoundDevice:

    def invoke_on_mixer(self, callback):
        if not self.control:
            logger.warning("no mixer control available, skipping mixer operation")
            return None

        try:
            mixer = self.get_mixer(control=self.control, device=self.device)
        except alsaaudio.ALSAAudioError:
            logger.warning(
                "failed to open mixer %s:%s", self.device, self.control, exc_info=True
            )
            return None

        try:
            return callback(mixer) if callback is not None else None
        finally:
            mixer.close()

    def __init__(self, control=None, device="default"):
        self.control = control
        self.device = device
        self.threadLock = threading.Lock()

    def get_algorithm(self, mixer) -> Algorithm:
        [min_volume_db, max_volume_db] = mixer.getrange(units=alsaaudio.VOLUME_UNITS_DB)

        volume_db = self.combine_channel_values(
            mixer.getvolume(units=alsaaudio.VOLUME_UNITS_DB)
        )
        if min_volume_db < max_volume_db and volume_db < max_volume_db:
            return Algorithm("cubic", volume_db, min_volume_db, max_volume_db)
        else:
            return Algorithm("linear", volume_db, min_volume_db, max_volume_db)

    def get_system_volume(self) -> float:
        def callback(mixer) -> float:

            human_volume = 0.0
            algorithm = self.get_algorithm(mixer)
            if algorithm.name == "cubic":
                human_volume = self.convert_to_human_volume(
                    algorithm.volume_db, algorithm.max_volume_db
                )
            else:
                [min_volume_raw, max_volume_raw] = mixer.getrange(
                    units=alsaaudio.VOLUME_UNITS_RAW
                )
                volume_raw = self.combine_channel_values(
                    mixer.getvolume(units=alsaaudio.VOLUME_UNITS_RAW)
                )
                human_volume = self.convert_to_normalized_volume(
                    volume_raw, min_volume_raw, max_volume_raw
                )

            logger.debug(
                "human_volume is %.2f on %s:%s (%s)",
                human_volume,
                mixer.cardname(),
                mixer.mixer(),
                algorithm.name,
            )
            return human_volume

        volume = self.invoke_on_mixer(callback)
        return volume if volume is not None else 0.0

    def set_system_volume(self, new_human_volume: float):
        def callback(mixer) -> None:

            algorithm = self.get_algorithm(mixer)
            if algorithm.name == "cubic":
                volume_db = self.convert_from_human_volume(
                    new_human_volume, algorithm.min_volume_db, algorithm.max_volume_db
                )
                mixer.setvolume(int(volume_db), units=alsaaudio.VOLUME_UNITS_DB)
            else:
                [min_volume_raw, max_volume_raw] = mixer.getrange(
                    units=alsaaudio.VOLUME_UNITS_RAW
                )
                volume_raw = self.convert_from_normalized_volume(
                    new_human_volume, min_volume_raw, max_volume_raw
                )
                mixer.setvolume(int(volume_raw), units=alsaaudio.VOLUME_UNITS_RAW)

            logger.debug(
                "set %s:%s human_volume to %.2f (%s)",
                mixer.cardname(),
                mixer.mixer(),
                new_human_volume,
                algorithm.name,
            )

        self.invoke_on_mixer(callback)

    def combine_channel_values(self, values):
        return sum(values) / len(values) if len(values) > 0 else 0

    def convert_to_human_volume(self, volume: float, max_volume: float) -> float:
        return (
            10 ** ((volume - max_volume) / 6000.0)
            if (volume <= max_volume)
            else max_volume
        )

    def convert_to_normalized_volume(
        self, volume_raw: float, min_volume_raw: float, max_volume_raw: float
    ) -> float:
        return (volume_raw - min_volume_raw) / (max_volume_raw - min_volume_raw)

    def convert_from_human_volume(
        self, human_volume: float, min_volume: float, max_volume: float
    ) -> float:
        volume_db = min_volume

        try:
            volume_db = 6000.0 * math.log10(human_volume) + max_volume
        except:
            pass

        if volume_db <= min_volume:
            return min_volume
        if volume_db >= max_volume:
            return max_volume

        return volume_db

    def convert_from_normalized_volume(
        self, human_volume: float, min_volume: float, max_volume: float
    ) -> float:
        volume_raw = human_volume * (max_volume - min_volume) + min_volume

        if volume_raw <= min_volume:
            return min_volume
        if volume_raw >= max_volume:
            return max_volume

        return volume_raw

    def get_mixer(self, control, device) -> alsaaudio.Mixer:
        return alsaaudio.Mixer(control=control, device=device)

    def get_controls_settings(self):
        settings = {}
        for control in alsaaudio.mixers(device=self.device):
            mixer = self.get_mixer(control=control, device=self.device)
            settings[control] = mixer.getvolume()
            mixer.close()

        return settings

    def set_controls_settings(self, settings):
        for control in settings.keys():
            mixer = self.get_mixer(control=control, device=self.device)
            for channel in range(len(settings[control])):
                mixer.setvolume(settings[control][channel], channel=channel)
            mixer.close()

    def debug_info(self):
        logger.info("installed cards: %s", ", ".join(alsaaudio.cards()))
        for pcm in alsaaudio.pcms():
            try:
                logger.info(
                    "pcm %s mixers: %s", pcm, ", ".join(alsaaudio.mixers(device=pcm))
                )
            except:
                logger.debug("pcm %s mixers: %s", pcm, "none")


class TACSoundDevice(SoundDevice):

    def __init__(self):
        super().__init__()
        self.init_mixer(resources.valid_mixer_device_simple_control_names)

    def init_mixer(self, valid_mixers: list[str], device: str = "default"):
        self.device = device
        self.control = None
        self.debug_info()

        self.threadLock.acquire(True)
        try:
            for mixer in valid_mixers:
                try:
                    self.get_mixer(control=mixer, device=device).close()
                    self.control = mixer
                    break
                except alsaaudio.ALSAAudioError:
                    pass
        finally:
            self.threadLock.release()

        if self.control is None:
            # no sound-card present (e.g. dev machine or headless Pi) - keep the
            # device usable in a no-op state instead of crashing app startup
            logger.warning(
                "no valid mixer found on device '%s' (tried: %s), sound control disabled",
                device,
                ", ".join(valid_mixers),
            )
