from core.domain.model import AlarmClockState, Mode, TACEvent, TACEventSubscriber
from gpiozero import DigitalOutputDevice
import logging

logger = logging.getLogger("tac.gpo")

audio_mute_pin_id = 22


# currently unused because kernel handles audio unmute
class GeneralPurposeOutput(TACEventSubscriber):

    audio_unmute_pin: DigitalOutputDevice

    def __init__(self):
        try:
            self.audio_unmute_pin = DigitalOutputDevice(audio_mute_pin_id)
        except:
            logger.warning("audio unmute pin not available")
            self.audio_unmute_pin = None

    def handle(self, observation: TACEvent):
        super().handle(observation)
        if isinstance(observation.subscriber, AlarmClockState):
            self.update_from_state(observation, observation.subscriber)

    def update_from_state(self, observation: TACEvent, state: AlarmClockState):
        if self.audio_unmute_pin is None:
            return
        if observation.property_name == "mode":
            if state.mode in [Mode.Alarm, Mode.Music, Mode.Spotify]:
                logger.info("unmuting audio on pin %s", audio_mute_pin_id)
                self.audio_unmute_pin.on()
            else:
                self.audio_unmute_pin.off()
