import collections
import threading
import unittest
from unittest import mock

from utils import thread_profiler

PsThread = collections.namedtuple("PsThread", "id user_time system_time")
CpuTimes = collections.namedtuple("CpuTimes", "user system")
LOGGER = "tac.utils.thread_profiler"


def fake_thread(name, ident, native_id, daemon=False, alive=True):
    thread = mock.Mock(ident=ident, native_id=native_id, daemon=daemon)
    thread.name = name
    thread.is_alive.return_value = alive
    return thread


def fake_process(cpu_percent, cpu_times, ps_threads):
    process = mock.Mock()
    process.cpu_percent.return_value = cpu_percent
    process.cpu_times.return_value = cpu_times
    process.threads.return_value = ps_threads
    return process


class GetThreadUsageTest(unittest.TestCase):
    def usage(self, process, threads, interval=0.1):
        with mock.patch.object(
            thread_profiler.psutil, "Process", return_value=process
        ), mock.patch.object(
            thread_profiler.threading, "enumerate", return_value=threads
        ):
            return thread_profiler.get_thread_usage(interval)

    def test_cpu_is_distributed_proportionally_to_thread_time(self):
        process = fake_process(
            50.0,
            CpuTimes(3.0, 1.0),
            [PsThread(100, 1.0, 0.0), PsThread(200, 2.0, 1.0)],
        )
        stats = self.usage(
            process, [fake_thread("a", 1, 100), fake_thread("b", 2, 200, daemon=True)]
        )

        self.assertEqual(stats[0], ("a", 1, 100, False, True, 12.5))
        self.assertEqual(stats[1], ("b", 2, 200, True, True, 37.5))

    def test_interval_is_forwarded_to_psutil(self):
        process = fake_process(0.0, CpuTimes(1.0, 0.0), [])
        self.usage(process, [], interval=0.5)
        process.cpu_percent.assert_called_once_with(0.5)

    def test_results_are_sorted_by_name(self):
        process = fake_process(0.0, CpuTimes(1.0, 0.0), [])
        stats = self.usage(
            process,
            [fake_thread("zeta", 1, 1), fake_thread("alpha", 2, 2), fake_thread("mid", 3, 3)],
        )
        self.assertEqual([s[0] for s in stats], ["alpha", "mid", "zeta"])

    def test_thread_unknown_to_psutil_gets_zero_cpu(self):
        process = fake_process(80.0, CpuTimes(1.0, 0.0), [PsThread(1, 1.0, 0.0)])
        stats = self.usage(process, [fake_thread("t", 5, 999)])
        self.assertEqual(stats[0][5], 0.0)

    def test_zero_total_cpu_time_yields_zero_usage_without_division_error(self):
        process = fake_process(0.0, CpuTimes(0.0, 0.0), [PsThread(1, 0.0, 0.0)])
        stats = self.usage(process, [fake_thread("t", 5, 1)])
        self.assertEqual(stats[0][5], 0.0)

    def test_thread_without_native_id_reports_zero_cpu(self):
        thread = fake_thread("t", 5, None)
        process = fake_process(10.0, CpuTimes(1.0, 0.0), [PsThread(1, 1.0, 0.0)])
        self.assertEqual(self.usage(process, [thread])[0][5], 0.0)

    def test_dead_thread_is_reported_as_not_alive(self):
        process = fake_process(0.0, CpuTimes(1.0, 0.0), [])
        stats = self.usage(process, [fake_thread("t", 1, 1, alive=False)])
        self.assertFalse(stats[0][4])

    def test_no_threads_returns_empty_list(self):
        process = fake_process(0.0, CpuTimes(1.0, 0.0), [])
        self.assertEqual(self.usage(process, []), [])

    def test_real_process_includes_current_thread(self):
        stats = thread_profiler.get_thread_usage(interval=0)
        names = [entry[0] for entry in stats]
        self.assertIn(threading.current_thread().name, names)
        for entry in stats:
            self.assertEqual(len(entry), 6)
            self.assertGreaterEqual(entry[5], 0.0)


class PrintThreadUsageTest(unittest.TestCase):
    def test_logs_header_rows_and_total(self):
        rows = [("worker", 123, 456, True, True, 12.34)]
        with mock.patch.object(
            thread_profiler, "get_thread_usage", return_value=rows
        ), mock.patch.object(
            thread_profiler.threading, "enumerate", return_value=[object()] * 3
        ), self.assertLogs(LOGGER, "INFO") as logs:
            thread_profiler.print_thread_usage()

        output = "\n".join(logs.output)
        self.assertIn("Name", output)
        self.assertIn("worker", output)
        self.assertIn("12.3", output)
        self.assertRegex(output, r"Total Threads\s+\|\s+3")

    def test_logs_even_without_threads(self):
        with mock.patch.object(
            thread_profiler, "get_thread_usage", return_value=[]
        ), self.assertLogs(LOGGER, "INFO") as logs:
            thread_profiler.print_thread_usage()
        self.assertIn("Total Threads", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
