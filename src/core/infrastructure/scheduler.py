from enum import Enum
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job
from apscheduler.schedulers.base import STATE_STOPPED

from core.domain.model import AlarmDefinition, Config, NextAlarmInfo
from core.domain.events import ConfigChangedEvent
from utils.extensions import get_job_arg
from utils.geolocation import GeoLocation

logger = logging.getLogger("tac.core.infrastructure.scheduler")


class SchedulerStores(Enum):
    alarm = "alarm"
    default = "default"


class SchedulerService:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        jobstores = {"alarm": {"type": "memory"}, "default": {"type": "memory"}}
        self.scheduler = BackgroundScheduler(jobstores=jobstores)
        self.scheduler.start()

    def shutdown(self):
        if self.scheduler.state == STATE_STOPPED:
            return
        self.scheduler.shutdown()

    def add_job(
        self,
        func: Callable,
        job_id: str,
        jobstore: str = "default",
        trigger: str = None,
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
        **trigger_args,
    ) -> Job:
        logger.debug(
            f"Adding job {job_id} to {jobstore} with trigger {trigger} and args {trigger_args}"
        )
        return self.scheduler.add_job(
            func=func,
            trigger=trigger,
            job_id=job_id,
            jobstore=jobstore,
            args=args,
            kwargs=kwargs,
            **trigger_args,
        )

    def add_cron_job(
        self,
        func: Callable,
        job_id: str,
        jobstore: str = "default",
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
        **cron_args,
    ) -> Job:
        trigger = CronTrigger(**cron_args)
        return self.scheduler.add_job(
            func=func,
            trigger=trigger,
            job_id=job_id,
            jobstore=jobstore,
            args=args,
            kwargs=kwargs,
        )

    def add_date_job(
        self,
        func: Callable,
        job_id: str,
        run_date: datetime,
        jobstore: str = "default",
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
    ) -> Job:
        trigger = DateTrigger(run_date=run_date)
        return self.scheduler.add_job(
            func=func,
            trigger=trigger,
            job_id=job_id,
            jobstore=jobstore,
            args=args,
            kwargs=kwargs,
        )

    def reschedule_job(
        self, job_id: str, jobstore: str = "default", trigger: str = None, **trigger_args
    ):
        self.scheduler.reschedule_job(
            job_id=job_id, jobstore=jobstore, trigger=trigger, **trigger_args
        )

    def reschedule_date_job(
        self, job_id: str, run_date: datetime, jobstore: str = "default"
    ):
        trigger = DateTrigger(run_date=run_date)
        self.scheduler.reschedule_job(job_id=job_id, jobstore=jobstore, trigger=trigger)

    def remove_job(self, job_id: str, jobstore: str = "default"):
        if self.get_job(job_id, jobstore):
            self.scheduler.remove_job(job_id=job_id, jobstore=jobstore)

    def remove_all_jobs(self, jobstore: str = "default"):
        self.scheduler.remove_all_jobs(jobstore=jobstore)

    def get_job(self, job_id: str, jobstore: str = "default") -> Optional[Job]:
        return self.scheduler.get_job(job_id=job_id, jobstore=jobstore)

    def get_jobs(self, jobstore: str = "default"):
        return self.scheduler.get_jobs(jobstore=jobstore)

    def shutdown(self):
        self.scheduler.shutdown()

    def stop_generic_trigger(
        self, job_id: str, jobstore=SchedulerStores.default.value
    ):
        if self.get_job(job_id=job_id, jobstore=jobstore) is not None:
            self.remove_job(job_id=job_id, jobstore=jobstore)

    def start_generic_trigger(
        self,
        job_id: str,
        duration: timedelta,
        func,
        jobstore=SchedulerStores.default.value,
    ):
        run_date = GeoLocation().now() + duration

        logger.debug("starting generic trigger %s for %s", job_id, duration)
        existing_job = self.get_job(job_id=job_id, jobstore=jobstore)
        if existing_job:
            self.reschedule_date_job(job_id=job_id, run_date=run_date, jobstore=jobstore)
        else:
            self.add_date_job(
                job_id=job_id, run_date=run_date, func=func, jobstore=jobstore
            )

    def add_or_replace_date_job(
        self,
        func: Callable,
        job_id: str,
        run_date: datetime,
        jobstore: str = SchedulerStores.default.value,
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
    )
        existing_job = self.get_job(job_id=job_id, jobstore=jobstore)
        if existing_job:
            self.remove_job(job_id=job_id, jobstore=jobstore)

        self.add_date_job(
            job_id=job_id, run_date=run_date, func=func, jobstore=jobstore, args, kwargs
        )

    def get_next_alarm_info(self) -> NextAlarmInfo:
        jobs = sorted(
            self.get_jobs(jobstore=SchedulerStores.alarm.value),
            key=lambda job: job.next_run_time,
        )
        next_job: Job = jobs[0] if len(jobs) > 0 else None

        alarm_def = get_job_arg(next_job, AlarmDefinition)
        if next_job is None or alarm_def is None:
            return NextAlarmInfo()
        return NextAlarmInfo(
            next_job.next_run_time,
            alarm_def,
        )

    def log_active_jobs(self, jobstore):
        job: Job
        for job in self.get_jobs(jobstore=jobstore):
            if hasattr(job, "next_run_time") and job.next_run_time is not None:
                logger.info(
                    "next runtime for job '%s': %s",
                    job.id,
                    job.next_run_time.strftime(f"%Y-%m-%d %H:%M:%S"),
                )

    def cleanup_alarms(self, config: Config):
        job: Job
        config_changed = False
        for job in self.get_jobs(jobstore=SchedulerStores.alarm.value):
            if job.next_run_time is None:
                config.remove_alarm_definition(int(job.id))
                config_changed = True
        if config_changed:
            self.event_bus.emit(ConfigChangedEvent(config))
        self.log_active_jobs(SchedulerStores.alarm.value)
