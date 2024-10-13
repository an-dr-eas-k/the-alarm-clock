from datetime import timedelta
from typing import Generic, Type, TypeVar
from apscheduler.job import Job

from utils.geolocation import GeoLocation


def get_timedelta_to_alarm(job: Job) -> timedelta:
    # positive if before alarm
    if not job or job.next_run_time is None:
        return timedelta.max
    diff = job.next_run_time - GeoLocation().now()
    return diff


T = TypeVar("T")


def get_job_arg(job: Job, argType: Type[T]) -> T:
    if job is None:
        return None
    return job.args[0]


def respect_ranges(value: float, min_value: int = 0, max_value: int = 15) -> int:
    return int(max(min_value, min(max_value, value)))


class Value(Generic[T]):
    value: T

    def __init__(self, value: T):
        self.value = value

    def __call__(self) -> T:
        return self.value
