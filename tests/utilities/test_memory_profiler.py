import unittest
from unittest import mock

from utils import memory_profiler

LOGGER = "tac.utils.memory_profiler"


def stat(filename, lineno, size=0, size_diff=0, count=0, count_diff=0):
    frame = mock.Mock(filename=filename, lineno=lineno)
    return mock.Mock(
        traceback=[frame],
        size=size,
        size_diff=size_diff,
        count=count,
        count_diff=count_diff,
    )


class MemoryProfilerTestCase(unittest.TestCase):
    def setUp(self):
        for attribute in ("_tracker", "_snapshot"):
            patcher = mock.patch.object(memory_profiler, attribute, None)
            patcher.start()
            self.addCleanup(patcher.stop)


class LogMemoryDiffTest(MemoryProfilerTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(memory_profiler, "SummaryTracker")
        self.tracker_class = patcher.start()
        self.addCleanup(patcher.stop)
        self.tracker = self.tracker_class.return_value

    def test_first_call_only_establishes_baseline(self):
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_memory_diff()

        self.tracker_class.assert_called_once_with()
        self.tracker.diff.assert_not_called()
        self.assertIn("Baseline established", logs.output[0])

    def test_second_call_logs_diff_rows_sorted_by_size_descending(self):
        self.tracker.diff.return_value = [
            ["small", 1, 1024],
            ["big", 5, 10 * 1024],
            ["shrunk", -2, -2048],
        ]
        memory_profiler.log_memory_diff()
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_memory_diff()

        rows = [line for line in logs.output if "KiB" not in line and "|" in line]
        self.assertEqual([r.split("|")[0].split(":")[-1].strip() for r in rows],
                         ["big", "small", "shrunk"])
        output = "\n".join(logs.output)
        self.assertIn("+10.00", output)
        self.assertIn("-2.00", output)
        self.assertIn("+5", output)
        self.assertIn("-2", output)
        self.tracker_class.assert_called_once_with()

    def test_empty_diff_is_reported(self):
        self.tracker.diff.return_value = []
        memory_profiler.log_memory_diff()
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_memory_diff()
        self.assertIn("No differences", "\n".join(logs.output))

    def test_long_names_are_truncated(self):
        self.tracker.diff.return_value = [["x" * 60, 1, 1024]]
        memory_profiler.log_memory_diff()
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_memory_diff()
        output = "\n".join(logs.output)
        self.assertIn("x" * 37 + "...", output)
        self.assertNotIn("x" * 38, output)

    def test_alternative_row_structure_is_supported(self):
        self.tracker.diff.return_value = [((2048, 3), "alt")]
        memory_profiler.log_memory_diff()
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_memory_diff()
        output = "\n".join(logs.output)
        self.assertIn("alt", output)
        self.assertIn("+2.00", output)

    def test_unparsable_row_is_logged_as_not_available(self):
        self.tracker.diff.return_value = [["only-one"]]
        memory_profiler.log_memory_diff()
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_memory_diff()
        self.assertIn("N/A", "\n".join(logs.output))

    def test_tracker_failure_is_logged_not_raised(self):
        self.tracker.diff.side_effect = RuntimeError("broken")
        memory_profiler.log_memory_diff()
        with self.assertLogs(LOGGER, "ERROR") as logs:
            memory_profiler.log_memory_diff()
        self.assertIn("Failed to track memory diff", logs.output[0])


class LogTracemallocDiffTest(MemoryProfilerTestCase):
    def setUp(self):
        super().setUp()
        self.patches = {
            name: mock.patch.object(memory_profiler.tracemalloc, name)
            for name in ("is_tracing", "start", "take_snapshot")
        }
        self.mocks = {name: p.start() for name, p in self.patches.items()}
        for p in self.patches.values():
            self.addCleanup(p.stop)
        gc_patcher = mock.patch.object(memory_profiler.gc, "collect")
        self.collect = gc_patcher.start()
        self.addCleanup(gc_patcher.stop)

    def test_starts_tracing_when_not_running_and_takes_baseline(self):
        self.mocks["is_tracing"].return_value = False
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_tracemalloc_diff()

        self.mocks["start"].assert_called_once_with()
        self.collect.assert_called_once_with()
        self.assertIs(memory_profiler._snapshot, self.mocks["take_snapshot"].return_value)
        self.assertIn("Baseline established", logs.output[-1])

    def test_does_not_restart_tracing_when_already_running(self):
        self.mocks["is_tracing"].return_value = True
        with self.assertLogs(LOGGER, "INFO"):
            memory_profiler.log_tracemalloc_diff()
        self.mocks["start"].assert_not_called()

    def test_second_call_logs_top_differences_and_advances_snapshot(self):
        self.mocks["is_tracing"].return_value = True
        baseline, current = mock.Mock(name="baseline"), mock.Mock(name="current")
        self.mocks["take_snapshot"].side_effect = [baseline, current]
        current.compare_to.return_value = [
            stat("/a.py", 1, size_diff=1024, count_diff=1),
            stat("/b.py", 2, size_diff=4096, count_diff=7),
            stat("/c.py", 3, size_diff=-512, count_diff=-1),
        ]
        with self.assertLogs(LOGGER, "INFO"):
            memory_profiler.log_tracemalloc_diff()
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_tracemalloc_diff(limit=2)

        current.compare_to.assert_called_once_with(baseline, "lineno")
        rows = [l for l in logs.output if ".py:" in l]
        self.assertEqual(len(rows), 2)
        self.assertIn("/b.py:2", rows[0])
        self.assertIn("+4.00", rows[0])
        self.assertIn("/a.py:1", rows[1])
        self.assertIs(memory_profiler._snapshot, current)

    def test_long_location_is_shortened(self):
        self.mocks["is_tracing"].return_value = True
        current = mock.Mock()
        self.mocks["take_snapshot"].side_effect = [mock.Mock(), current]
        current.compare_to.return_value = [stat("/very/" * 20 + "file.py", 12, size_diff=1)]
        with self.assertLogs(LOGGER, "INFO"):
            memory_profiler.log_tracemalloc_diff()
        with self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.log_tracemalloc_diff()
        row = [l for l in logs.output if "file.py" in l][0]
        self.assertIn("|", row)
        self.assertIn("...", row.split("|")[0])
        self.assertTrue(row.split("|")[0].strip().endswith("file.py:12"))


class PrintMemoryUsageTest(unittest.TestCase):
    def patched(self, rows=None, error=None):
        summarize = mock.patch.object(
            memory_profiler.summary, "summarize", return_value=rows, side_effect=error
        )
        objects = mock.patch.object(memory_profiler.muppy, "get_objects", return_value=[])
        return summarize, objects

    def test_logs_types_sorted_by_size_and_limited(self):
        rows = [["small", 1, 1024], ["huge", 3, 5 * 1024], ["mid", 2, 2048]]
        summarize, objects = self.patched(rows)
        with summarize, objects, self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.print_memory_usage(limit=2)

        data = [l for l in logs.output if l.split(":", 2)[-1].lstrip().startswith(("huge", "mid", "small"))]
        self.assertEqual(len(data), 2)
        self.assertIn("huge", data[0])
        self.assertIn("5.00", data[0])
        self.assertIn("mid", data[1])

    def test_long_type_names_are_truncated(self):
        summarize, objects = self.patched([["t" * 50, 1, 1024]])
        with summarize, objects, self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.print_memory_usage()
        self.assertIn("t" * 37 + "...", "\n".join(logs.output))

    def test_failure_is_logged_as_error(self):
        summarize, objects = self.patched(error=RuntimeError("no heap"))
        with summarize, objects, self.assertLogs(LOGGER, "ERROR") as logs:
            memory_profiler.print_memory_usage()
        self.assertIn("no heap", logs.output[0])


class TracingTest(unittest.TestCase):
    def test_start_tracing_starts_tracemalloc(self):
        with mock.patch.object(memory_profiler.tracemalloc, "start") as start:
            memory_profiler.start_tracing()
        start.assert_called_once_with()

    def test_snapshot_without_tracing_logs_hint(self):
        with mock.patch.object(
            memory_profiler.tracemalloc, "is_tracing", return_value=False
        ), mock.patch.object(
            memory_profiler.tracemalloc, "take_snapshot"
        ) as take_snapshot, self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.print_trace_snapshot()
        take_snapshot.assert_not_called()
        self.assertIn("start_tracing", logs.output[0])

    def test_snapshot_logs_largest_allocations_first(self):
        snapshot = mock.Mock()
        snapshot.statistics.return_value = [
            stat("/small.py", 1, size=1024, count=1),
            stat("/large.py", 2, size=8192, count=4),
            stat("/medium.py", 3, size=2048, count=2),
        ]
        with mock.patch.object(
            memory_profiler.tracemalloc, "is_tracing", return_value=True
        ), mock.patch.object(
            memory_profiler.tracemalloc, "take_snapshot", return_value=snapshot
        ), self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.print_trace_snapshot(limit=2)

        snapshot.statistics.assert_called_once_with("lineno")
        rows = [l for l in logs.output if ".py:" in l]
        self.assertEqual(len(rows), 2)
        self.assertIn("/large.py:2", rows[0])
        self.assertIn("8.00", rows[0])
        self.assertIn("/medium.py:3", rows[1])


class PrintFullReportTest(unittest.TestCase):
    def test_runs_every_profiling_step(self):
        with mock.patch.object(memory_profiler, "print_memory_usage") as usage, \
                mock.patch.object(memory_profiler, "log_memory_diff") as diff, \
                mock.patch.object(memory_profiler, "log_tracemalloc_diff") as tm, \
                self.assertLogs(LOGGER, "INFO") as logs:
            memory_profiler.print_full_report()

        usage.assert_called_once_with()
        diff.assert_called_once_with()
        tm.assert_called_once_with(limit=50)
        self.assertIn("MEMORY PROFILER FULL REPORT", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
