import logging
import tracemalloc
from pympler import muppy, summary
from pympler.tracker import SummaryTracker

logger = logging.getLogger("tac.utils.memory_profiler")

_tracker = None


def log_memory_diff():
    """
    Logs the difference in memory usage since the last call.
    Useful for finding memory leaks.
    """
    global _tracker
    if _tracker is None:
        _tracker = SummaryTracker()
        logger.info("Initialized memory tracker. Baseline established.")
        return

    logger.info("Memory usage difference since last check:")
    # SummaryTracker.print_diff() prints to stdout. We want to capture it or just let it print if stdout is redirected.
    # Unfortunately print_diff doesn't return the string easily without redirecting stdout.
    # However, we can use diff() to get the raw data and format it ourselves if we want to log it properly.

    try:
        # This prints to stdout, which might be captured by systemd/docker logs
        _tracker.print_diff()
    except Exception as e:
        logger.error(f"Failed to track memory diff: {e}")


_snapshot = None


def log_tracemalloc_diff(limit=10):
    """
    Logs the difference in memory allocations using tracemalloc.
    Shows file and line number of increasing allocations.
    """
    global _snapshot

    if not tracemalloc.is_tracing():
        tracemalloc.start()
        logger.info("Started tracemalloc tracing")

    current_snapshot = tracemalloc.take_snapshot()

    if _snapshot is None:
        _snapshot = current_snapshot
        logger.info("Taken initial tracemalloc snapshot. Baseline established.")
        return

    logger.info("Top memory allocation differences:")
    top_stats = current_snapshot.compare_to(_snapshot, "lineno")

    for stat in top_stats[:limit]:
        logger.info(str(stat))

    # Update snapshot to current for incremental diffs
    # _snapshot = current_snapshot


def print_memory_usage(limit=50):
    """
    Prints a summary of memory usage by type using Pympler.
    """
    logger.info("Collecting memory usage statistics...")
    try:
        all_objects = muppy.get_objects()
        sum1 = summary.summarize(all_objects)

        # Print to stdout (useful when running manually or if stdout is captured)
        summary.print_(sum1, limit=limit)

        # Also log the top items to the logger so it appears in the application logs
        formatted_summary = summary.format_(sum1, limit=10)
        logger.info("Top 10 memory consumers:")
        for line in formatted_summary:
            logger.info(line.strip())

    except Exception as e:
        logger.error(f"Failed to profile memory: {e}")


def start_tracing():
    """Start tracing memory allocations"""
    tracemalloc.start()


def print_trace_snapshot(limit=10):
    """Print a snapshot of memory allocations"""
    if not tracemalloc.is_tracing():
        print("Tracemalloc is not running. Call start_tracing() first.")
        return

    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")

    print(f"\n[ Top {limit} Memory Allocations ]")
    for stat in top_stats[:limit]:
        print(stat)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print_memory_usage()
