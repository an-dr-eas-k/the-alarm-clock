import logging
import math
import threading
import alsaaudio
from resources import resources

logger = logging.getLogger("tac.sound_device")


class SoundDevice:

    def invoke_on_mixer(self, callback):
        mixer = self.get_mixer(control=self.control, device=self.device)
        if callback is not None:
            return_from_callback = callback(mixer)
        mixer.close()
        return return_from_callback

    def __init__(self, control="", device="default"):
        self.control = control
        self.device = device
        self.threadLock = threading.Lock()

    def get_system_volume(self) -> float:
        def callback(mixer) -> float:
            [min_volume_db, max_volume_db] = mixer.getrange(
                units=alsaaudio.VOLUME_UNITS_DB
            )

            human_volume = 0
            algorithm = "cubic"
            volume_db = self.combine_channel_values(
                mixer.getvolume(units=alsaaudio.VOLUME_UNITS_DB)
            )
            if min_volume_db < max_volume_db and volume_db < max_volume_db:
                human_volume = self.convert_to_human_volume(volume_db, max_volume_db)
            else:
                algorithm = "linear"
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
                f"human_volume is %s (%s-%s) on %s:%s (%s)"
                % (
                    human_volume,
                    min_volume_db,
                    max_volume_db,
                    mixer.cardname(),
                    mixer.mixer(),
                    algorithm,
                )
            )
            return human_volume

        return self.invoke_on_mixer(callback)

    def set_system_volume(self, new_human_volume: float):
        def callback(mixer) -> None:
            [min_volume_db, max_volume_db] = mixer.getrange(
                units=alsaaudio.VOLUME_UNITS_DB
            )
            algorithm = "cubic"
            a: float
            if min_volume_db < max_volume_db:
                volume_db = self.convert_from_human_volume(
                    new_human_volume, min_volume_db, max_volume_db
                )
                a = volume_db
                mixer.setvolume(int(volume_db), units=alsaaudio.VOLUME_UNITS_DB)
            else:
                algorithm = "linear"
                [min_volume_raw, max_volume_raw] = mixer.getrange(
                    units=alsaaudio.VOLUME_UNITS_RAW
                )
                volume_raw = self.convert_from_normalized_volume(
                    new_human_volume, min_volume_raw, max_volume_raw
                )
                a = volume_raw
                mixer.setvolume(int(volume_raw), units=alsaaudio.VOLUME_UNITS_RAW)

            logger.debug(
                "set %s:%s human_volume to %s (%s) [%s]",
                mixer.cardname(),
                mixer.mixer(),
                new_human_volume,
                algorithm,
                a,
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
            settings[control] = alsaaudio.Mixer(
                control=control, device=self.device
            ).getvolume()

        return settings

    def set_controls_settings(self, settings):
        for control in settings.keys():
            for channel in range(len(settings[control])):
                alsaaudio.Mixer(control=control, device=self.device).setvolume(
                    settings[control][channel], channel=channel
                )

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
        self.debug_info()

        self.threadLock.acquire(True)

        for mixer in valid_mixers:
            try:
                self.get_mixer(control=mixer, device=device)
                self.control = mixer
                break
            except alsaaudio.ALSAAudioError:
                pass

        self.threadLock.release()

        if self.control is None:
            raise Exception("no valid mixer found")
