import datetime
import unittest
from unittest import mock

from utils.extensions import Value, get_job_arg, get_timedelta_to_alarm, respect_ranges
from tests.support import frozen_now, local_datetime


class GetTimedeltaToAlarmTest(unittest.TestCase):
    def test_none_job_returns_max_timedelta(self):
        self.assertEqual(get_timedelta_to_alarm(None), datetime.timedelta.max)

    def test_job_without_next_run_time_returns_max_timedelta(self):
        job = mock.Mock(next_run_time=None)
        self.assertEqual(get_timedelta_to_alarm(job), datetime.timedelta.max)

    def test_positive_when_alarm_is_in_the_future(self):
        now = local_datetime(2024, 5, 1, 7, 0)
        job = mock.Mock(next_run_time=now + datetime.timedelta(minutes=30))
        with frozen_now(now):
            self.assertEqual(
                get_timedelta_to_alarm(job), datetime.timedelta(minutes=30)
            )

    def test_negative_when_alarm_is_in_the_past(self):
        now = local_datetime(2024, 5, 1, 7, 0)
        job = mock.Mock(next_run_time=now - datetime.timedelta(seconds=5))
        with frozen_now(now):
            self.assertEqual(get_timedelta_to_alarm(job), datetime.timedelta(seconds=-5))

    def test_zero_when_alarm_is_exactly_now(self):
        now = local_datetime(2024, 5, 1, 7, 0)
        job = mock.Mock(next_run_time=now)
        with frozen_now(now):
            self.assertEqual(get_timedelta_to_alarm(job), datetime.timedelta(0))


class GetJobArgTest(unittest.TestCase):
    def test_none_job_returns_none(self):
        self.assertIsNone(get_job_arg(None, str))

    def test_returns_first_job_argument(self):
        job = mock.Mock(args=("alarm-1", "other"))
        self.assertEqual(get_job_arg(job, str), "alarm-1")

    def test_job_without_args_raises_index_error(self):
        job = mock.Mock(args=())
        with self.assertRaises(IndexError):
            get_job_arg(job, str)


class RespectRangesTest(unittest.TestCase):
    def test_value_inside_range_is_unchanged(self):
        self.assertEqual(respect_ranges(7), 7)

    def test_value_below_min_is_clamped(self):
        self.assertEqual(respect_ranges(-3), 0)

    def test_value_above_max_is_clamped(self):
        self.assertEqual(respect_ranges(99), 15)

    def test_boundaries_are_inclusive(self):
        self.assertEqual(respect_ranges(0), 0)
        self.assertEqual(respect_ranges(15), 15)

    def test_custom_range(self):
        self.assertEqual(respect_ranges(5, 10, 20), 10)
        self.assertEqual(respect_ranges(25, 10, 20), 20)
        self.assertEqual(respect_ranges(12, 10, 20), 12)

    def test_float_is_truncated_to_int(self):
        result = respect_ranges(7.9)
        self.assertEqual(result, 7)
        self.assertIsInstance(result, int)

    def test_float_above_max_returns_int(self):
        self.assertIsInstance(respect_ranges(100.5), int)


class ValueTest(unittest.TestCase):
    def test_call_returns_wrapped_value(self):
        self.assertEqual(Value(42)(), 42)

    def test_value_attribute_is_mutable_and_reflected_in_call(self):
        wrapper = Value("a")
        wrapper.value = "b"
        self.assertEqual(wrapper(), "b")

    def test_wraps_none(self):
        self.assertIsNone(Value(None)())

    def test_returns_same_object_identity(self):
        payload = [1, 2]
        self.assertIs(Value(payload)(), payload)


if __name__ == "__main__":
    unittest.main()
