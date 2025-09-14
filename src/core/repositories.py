from core.domain import AlarmDefinition, Config, AudioStream
class ConfigRepository:
    def save(self, config: Config):
        raise NotImplementedError

    def load(self) -> Config:
        raise NotImplementedError
