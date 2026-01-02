import logging
import tracemalloc
import gc
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

        # Sort by size (descending)
        def get_size(row):
            try:
                if len(row) == 3:
                    return row[2]
                return row[0][0]
            except:
                return 0

        diffs.sort(key=get_size, reverse=True)

        # diffs is a list of [size_diff, count_diff, name] (usually)

        logger.info(f"{'Name':<40} | {'Size Δ (KiB)':>15} | {'Count Δ':>10}")
        logger.info("-" * 71)

        for row in diffs:
            try:
                if len(row) == 3:
                    # Pympler summary format is [class, count, size]
                    name, count_diff, size_diff = row
                else:
                    # Fallback for ((size, count), name) structure
                    size_count_diff, name = row
                    size_diff, count_diff = size_count_diff
            except Exception:
                # Fallback if structure differs
                logger.info(f"{str(row):<40} | {'N/A':>15} | {'N/A':>10}")
                continue

            # size is in bytes; present as kibibytes with sign
            size_kib = size_diff / 1024.0

            # Truncate name if too long
            display_name = str(name)
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."

            logger.info(f"{display_name:<40} | {size_kib:+15.2f} | {count_diff:+10d}")

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

    # Force garbage collection to get a cleaner snapshot
    gc.collect()
    current_snapshot = tracemalloc.take_snapshot()

    if _snapshot is None:
        _snapshot = current_snapshot
        logger.info("Taken initial tracemalloc snapshot. Baseline established.")
        return

    logger.info("Top memory allocation differences:")
    top_stats = current_snapshot.compare_to(_snapshot, "lineno")

    # Sort by size difference descending
    top_stats.sort(key=lambda x: x.size_diff, reverse=True)

    logger.info(f"{'Location':<50} | {'Size Δ (KiB)':>15} | {'Count Δ':>10}")
    logger.info("-" * 81)

    for stat in top_stats[:limit]:
        frame = stat.traceback[0]
        location = f"{frame.filename}:{frame.lineno}"
        if len(location) > 50:
            location = "..." + location[-47:]

        size_kib = stat.size_diff / 1024.0

        logger.info(f"{location:<50} | {size_kib:+15.2f} | {stat.count_diff:+10d}")

    # Update snapshot to current for incremental diffs
    _snapshot = current_snapshot


def print_memory_usage(limit=50):
    """
    Prints a summary of memory usage by type using Pympler.
    """
    logger.info("Collecting memory usage statistics...")
    try:
        all_objects = muppy.get_objects()
        sum1 = summary.summarize(all_objects)

        # Sort by size descending
        sum1.sort(key=lambda x: x[2], reverse=True)

        logger.info("Top memory consumers:")
        logger.info(f"{'Type':<40} | {'Count':>10} | {'Size (KiB)':>15}")
        logger.info("-" * 71)

        for row in sum1[:limit]:
            type_desc, count, size = row

            name = str(type_desc)
            if len(name) > 40:
                name = name[:37] + "..."

            size_kib = size / 1024.0

            logger.info(f"{name:<40} | {count:>10d} | {size_kib:>15.2f}")

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

    # Sort by size descending
    top_stats.sort(key=lambda x: x.size, reverse=True)

    logger.info(f"\n[ Top {limit} Memory Allocations ]")

    logger.info(f"{'Location':<50} | {'Size (KiB)':>15} | {'Count':>10}")
    logger.info("-" * 81)

    for stat in top_stats[:limit]:
        frame = stat.traceback[0]
        location = f"{frame.filename}:{frame.lineno}"
        if len(location) > 50:
            location = "..." + location[-47:]

        size_kib = stat.size / 1024.0

        logger.info(f"{location:<50} | {size_kib:>15.2f} | {stat.count:>10d}")


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

    logger.info("--- 3. Tracemalloc Diff (Source of Leaks) ---")
    log_tracemalloc_diff(limit=50)
    logger.info("(If this is the first run, this was just the baseline setup)")
    logger.info("\n")

    logger.info("=" * 80)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print_full_report()
    print_full_report()
    # print_memory_usage()
