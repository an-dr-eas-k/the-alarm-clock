import psutil
import threading


def get_thread_usage(interval=0.1):
    """
    Returns a list of (name, ident, native_id, is_daemon, is_alive, cpu_percent) tuples,
    sorted by name.
    """
    p = psutil.Process()
    total_percent = p.cpu_percent(interval)
    total_time = sum(p.cpu_times())

    psutil_threads = p.threads()
    thread_cpu_map = {}

    if total_time > 0:
        for t in psutil_threads:
            usage = total_percent * ((t.system_time + t.user_time) / total_time)
            thread_cpu_map[t.id] = usage

    threads = threading.enumerate()
    stats = []

    for t in threads:
        native_id = getattr(t, "native_id", None)
        cpu = thread_cpu_map.get(native_id, 0.0)
        stats.append(
            (
                t.name,
                t.ident,
                getattr(t, "native_id", "N/A"),
                t.daemon,
                t.is_alive(),
                cpu,
            )
        )

    stats.sort(key=lambda x: x[0])
    return stats


def print_thread_usage():
    print(
        f"{'Name':<40} | {'Ident':>15} | {'Native ID':>10} | {'Daemon':>6} | {'Alive':>6} | {'CPU %':>6}"
    )
    print("-" * 100)
    for name, ident, native_id, daemon, alive, cpu in get_thread_usage():
        print(
            f"{name:<40} | {ident:>15} | {str(native_id):>10} | {str(daemon):>6} | {str(alive):>6} | {cpu:>6.1f}"
        )
    print("-" * 100)
    print(f"{'Total Threads':<40} | {len(threading.enumerate()):>15}")


if __name__ == "__main__":
    print_thread_usage()
