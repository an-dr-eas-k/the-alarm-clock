import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.job import Job

logger = logging.getLogger("tac.scheduler")


class SchedulerService:
    def __init__(self, jobstores: Dict[str, Any]):
        self.scheduler = BackgroundScheduler(jobstores=jobstores)
        self.scheduler.start()

    def add_job(
        self,
        func: Callable,
        id: str,
        jobstore: str = "default",
        trigger: str = None,
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
        **trigger_args,
    ) -> Job:
        """
        Add a job to the scheduler.
        trigger: 'cron', 'date', 'interval'
        """
        logger.debug(
            f"Adding job {id} to {jobstore} with trigger {trigger} and args {trigger_args}"
        )
        return self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=id,
            jobstore=jobstore,
            args=args,
            kwargs=kwargs,
            **trigger_args,
        )

    def add_cron_job(
        self,
        func: Callable,
        id: str,
        jobstore: str = "default",
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
        **cron_args,
    ) -> Job:
        trigger = CronTrigger(**cron_args)
        return self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=id,
            jobstore=jobstore,
            args=args,
            kwargs=kwargs,
        )

    def add_date_job(
        self,
        func: Callable,
        id: str,
        run_date: datetime,
        jobstore: str = "default",
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
    ) -> Job:
        trigger = DateTrigger(run_date=run_date)
        return self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=id,
            jobstore=jobstore,
            args=args,
            kwargs=kwargs,
        )

    def reschedule_job(
        self, id: str, jobstore: str = "default", trigger: str = None, **trigger_args
    ):
        self.scheduler.reschedule_job(
            job_id=id, jobstore=jobstore, trigger=trigger, **trigger_args
        )

    def reschedule_date_job(
        self, id: str, run_date: datetime, jobstore: str = "default"
    ):
        trigger = DateTrigger(run_date=run_date)
        self.scheduler.reschedule_job(job_id=id, jobstore=jobstore, trigger=trigger)

    def remove_job(self, id: str, jobstore: str = "default"):
        if self.get_job(id, jobstore):
            self.scheduler.remove_job(job_id=id, jobstore=jobstore)

    def remove_all_jobs(self, jobstore: str = "default"):
        self.scheduler.remove_all_jobs(jobstore=jobstore)

    def get_job(self, id: str, jobstore: str = "default") -> Optional[Job]:
        return self.scheduler.get_job(job_id=id, jobstore=jobstore)

    def get_jobs(self, jobstore: str = "default"):
        return self.scheduler.get_jobs(jobstore=jobstore)

    def shutdown(self):
        self.scheduler.shutdown()
