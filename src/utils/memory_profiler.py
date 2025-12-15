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

    try:
        diffs = _tracker.diff()
        if not diffs:
            logger.info("No differences reported by SummaryTracker.")
            return

        # diffs is a list of tuples like (diff, name)
        # where diff is a tuple (size_diff, count_diff) and name is a str
        # We'll format this into aligned columns for logging.
        # Determine column widths
        name_width = max((len(name) for (_diff, name) in diffs), default=20)
        header = f"{'Name'.ljust(name_width)} | {'Size Δ (KiB)'.rjust(12)} | {'Count Δ'.rjust(8)}"
        logger.info(header)
        logger.info("-" * len(header))

        for size_count_diff, name in diffs:
            try:
                size_diff, count_diff = size_count_diff
            except Exception:
                # Fallback if structure differs
                logger.info(f"{name}")
                continue

            # size is in bytes; present as kibibytes with sign
            size_kib = size_diff / 1024.0
            size_str = f"{size_kib:+10.2f}"
            count_str = f"{count_diff:+8d}"
            logger.info(f"{name.ljust(name_width)} | {size_str} | {count_str}")

    except Exception as e:
        logger.exception("Failed to track memory diff")


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
        logger.info("Tracemalloc is not running. Call start_tracing() first.")
        return

    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")

    logger.info(f"\n[ Top {limit} Memory Allocations ]")
    for stat in top_stats[:limit]:
        logger.info(stat)


def print_full_report():
    """
    Runs all memory profiling methods to give a complete overview.
    """
    logger.info("\n" + "=" * 80)
    logger.info("MEMORY PROFILER FULL REPORT")
    logger.info("=" * 80 + "\n")

    logger.info("--- 1. Pympler Object Summary ---")
    print_memory_usage()
    logger.info("\n")

    logger.info("--- 2. Pympler Memory Diff (Baseline vs Now) ---")
    # Call twice to ensure we have a baseline if it's the first run
    log_memory_diff()
    logger.info("(If this is the first run, this was just the baseline setup)")
    logger.info("\n")

    logger.info("=" * 80)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print_full_report()
    print_memory_usage()
