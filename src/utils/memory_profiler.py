import sys
import gc
import tracemalloc
from collections import defaultdict

def get_memory_usage(limit=50):
    """
    Returns a list of (type_name, count, total_size) tuples,
    sorted by total_size descending.
    """
    objects = gc.get_objects()
    type_stats = defaultdict(lambda: {"count": 0, "size": 0})
    
    for obj in objects:
        try:
            obj_type = type(obj)
            size = sys.getsizeof(obj)
            # sys.getsizeof is shallow. For containers, it doesn't include contents.
            # But it's a good first approximation without external deps.
            
            type_stats[obj_type]["count"] += 1
            type_stats[obj_type]["size"] += size
        except Exception:
            continue
            
    stats = []
    for obj_type, data in type_stats.items():
        # Clean up type name
        name = str(obj_type)
        if hasattr(obj_type, '__name__'):
            name = f"{obj_type.__module__}.{obj_type.__name__}"
            
        stats.append((name, data["count"], data["size"]))
        
    stats.sort(key=lambda x: x[2], reverse=True)
    return stats[:limit]

def get_total_memory_usage():
    """Returns total memory usage of all objects in bytes (shallow)"""
    objects = gc.get_objects()
    total = 0
    for obj in objects:
        try:
            total += sys.getsizeof(obj)
        except Exception:
            pass
    return total

def print_memory_usage(limit=50):
    print(f"{'Type':<60} | {'Count':>10} | {'Size (bytes)':>15}")
    print("-" * 90)
    for name, count, size in get_memory_usage(limit):
        print(f"{name:<60} | {count:>10} | {size:>15}")
    print("-" * 90)
    print(f"{'Total (shallow)':<60} | {'':>10} | {get_total_memory_usage():>15}")

def start_tracing():
    """Start tracing memory allocations"""
    tracemalloc.start()

def print_trace_snapshot(limit=10):
    """Print a snapshot of memory allocations"""
    if not tracemalloc.is_tracing():
        print("Tracemalloc is not running. Call start_tracing() first.")
        return

    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')

    print(f"\n[ Top {limit} Memory Allocations ]")
    for stat in top_stats[:limit]:
        print(stat)

if __name__ == "__main__":
    print_memory_usage()
