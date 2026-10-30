#!/usr/bin/env python3
"""Portable Python CPU workloads; Python 3.8+, standard library only."""

import argparse
import datetime
import gc
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import sysconfig
import time


SUITE_VERSION = 2
SCHEMA_VERSION = 2
DEFAULT_LIST_SIZE = 10_000_000
LIST_SEED = 42
LIST_MAX = 999999999999999999
LIST_TESTS = ("generate", "sort")
_barrier = None
_list_size = DEFAULT_LIST_SIZE


class BenchmarkProgress:
    """One-line progress in progressBarLLM.py style, owned by the parent."""

    def __init__(self, total, stream=None):
        self.total = total
        self.completed = 0
        self.stream = stream if stream is not None else sys.stdout
        self.started = time.perf_counter()
        self.detail = "запуск процессов"
        self.last_width = 0
        self.full, self.empty = "█", "░"
        try:
            (self.full + self.empty).encode(getattr(self.stream, "encoding", None) or "utf-8")
        except (UnicodeEncodeError, LookupError):
            self.full, self.empty = "#", "-"
        self.columns = shutil.get_terminal_size(fallback=(100, 24)).columns

    def render(self):
        percent = min(100.0, self.completed / self.total * 100)
        bar_length = min(40, max(10, self.columns - 55))
        filled = int(bar_length * percent / 100)
        bar = "[{}{}] {:6.2f}%".format(
            self.full * filled, self.empty * (bar_length - filled), percent)
        elapsed = time.perf_counter() - self.started
        line = "{}  {:6.1f}s  {}".format(bar, elapsed, self.detail)
        # Reserve the final terminal column to avoid wrapping on a full line.
        line = line[:max(1, self.columns - 1)]
        self.stream.write("\r" + line.ljust(self.last_width))
        self.stream.flush()
        self.last_width = len(line)

    def show(self, detail):
        self.detail = detail
        self.render()

    def advance(self):
        self.completed += 1
        self.render()

    def close(self):
        self.stream.write("\n")
        self.stream.flush()


def pi_integral():
    """Midpoint integration of 4 / (1 + x*x), always 10,000 steps."""
    total = 0.0
    for i in range(10_000):
        x = (i + 0.5) / 10_000
        total += 4.0 / (1.0 + x * x)
    return total / 10_000


def integer_mix():
    """Bounded 32-bit xorshift; Python integers never grow without limit."""
    x = 0x12345678
    for _ in range(20_000):
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
    return x


def prime_search():
    """Trial division on a fixed interval; integer division and branches."""
    count = 0
    for candidate in range(100_001, 102_000, 2):
        divisor = 3
        while divisor * divisor <= candidate:
            if candidate % divisor == 0:
                break
            divisor += 2
        else:
            count += 1
    return count


def math_mix():
    """Scalar C math calls plus Python floating point accumulation."""
    total = 0.0
    for i in range(1, 10_001):
        x = i / 1000.0
        total += math.sqrt(x) + math.sin(x) + math.log1p(x)
    return total


# Unit counts describe fixed workload steps, not CPU instructions or FLOPS.
WORKLOADS = {
    "pi": (pi_integral, 10_000, "шагов интегрирования"),
    "integer": (integer_mix, 20_000, "шагов xorshift"),
    "primes": (prime_search, 1_000, "проверенных кандидатов"),
    "math": (math_mix, 10_000, "шагов sqrt/sin/log1p"),
    "generate": (None, DEFAULT_LIST_SIZE, "сгенерированных чисел"),
    "sort": (None, DEFAULT_LIST_SIZE, "отсортированных чисел"),
}


def generate_list(size):
    """Original smg3bench workload, with a local reproducible PRNG."""
    rng = random.Random(LIST_SEED)
    data = []
    while len(data) < size:
        data.append(rng.randint(0, LIST_MAX))
    return data


def list_signature(data):
    return {"count": len(data), "sum": sum(data), "min": min(data), "max": max(data)}


def run_list_job(name):
    # These jobs run only in a one-process pool. Setup, verification and freeing
    # the large list must not accidentally become part of sort/generation time.
    data = generate_list(_list_size) if name == "sort" else None
    before = list_signature(data) if data is not None else None
    _barrier.wait(timeout=120)
    start = time.perf_counter()
    cpu_start = time.process_time()
    if name == "generate":
        data = generate_list(_list_size)
    else:
        data.sort()
    cpu_seconds = time.process_time() - cpu_start
    wall_seconds = time.perf_counter() - start
    signature = list_signature(data)
    if (signature["count"] != _list_size or signature["min"] < 0
            or signature["max"] > LIST_MAX):
        raise RuntimeError("Неверный результат генерации списка")
    if name == "sort":
        if signature != before or any(data[i - 1] > data[i] for i in range(1, len(data))):
            raise RuntimeError("Неверный результат сортировки списка")
    del data
    return {"pid": os.getpid(), "seconds": wall_seconds,
            "cpu_seconds": cpu_seconds, "result": signature}


def check_result(name, value):
    if name == "pi":
        valid = math.isclose(value, math.pi, rel_tol=0.0, abs_tol=1e-8)
    elif name == "integer":
        valid = value == EXPECTED_INTEGER
    elif name == "primes":
        valid = value == EXPECTED_PRIMES
    else:
        valid = math.isclose(value, EXPECTED_MATH, rel_tol=1e-10)
    if not valid:
        raise RuntimeError("Неверный результат {}: {!r}".format(name, value))


# Fixed reference values; also verified by test_cpu_bench.py.
EXPECTED_INTEGER = 221017786
EXPECTED_PRIMES = 174
EXPECTED_MATH = 39300.27188378177


def init_worker(barrier, ready, list_size=DEFAULT_LIST_SIZE):
    global _barrier, _list_size
    _barrier = barrier
    _list_size = list_size
    gc.disable()
    ready.put(os.getpid())


def run_job(job):
    name, loops = job
    if name in LIST_TESTS:
        if loops != 1:
            raise ValueError("Тест списка выполняет ровно один блок за замер")
        return run_list_job(name)
    function = WORKLOADS[name][0]
    # Every job must reach this barrier: each pool process gets exactly one job.
    # Parent timing includes dispatch/return overhead, but excludes pool startup.
    _barrier.wait(timeout=120)
    start = time.perf_counter()
    cpu_start = time.process_time()
    for _ in range(loops):
        result = function()
    cpu_seconds = time.process_time() - cpu_start
    wall_seconds = time.perf_counter() - start
    check_result(name, result)
    return {"pid": os.getpid(), "seconds": wall_seconds,
            "cpu_seconds": cpu_seconds, "result": result}


def run_sample(pool, name, loops, workers, list_size=DEFAULT_LIST_SIZE, on_wait=None):
    if name in LIST_TESTS and workers != 1:
        raise ValueError("Тесты больших списков поддерживают только один процесс")
    start = time.perf_counter()
    work = [(name, loops)] * workers
    if on_wait is None:
        jobs = pool.map(run_job, work, chunksize=1)
    else:
        pending = pool.map_async(run_job, work, chunksize=1)
        while True:
            try:
                jobs = pending.get(timeout=0.1)
                break
            except mp.TimeoutError:
                on_wait()
    end_to_end = time.perf_counter() - start
    # Core tests include dispatch overhead; list tests exclude untimed setup,
    # result verification and deallocation, measured in their worker instead.
    seconds = jobs[0]["seconds"] if name in LIST_TESTS else end_to_end
    units = list_size if name in LIST_TESTS else loops * workers * WORKLOADS[name][1]
    return {"seconds": seconds, "units": units,
            "end_to_end_seconds": end_to_end,
            "units_per_second": units / seconds,
            "worker_cpu_seconds": sum(job["cpu_seconds"] for job in jobs),
            "workers": jobs}


def calibrate(pool, name, workers, target, on_wait=None):
    loops = 1
    for _ in range(12):
        sample = run_sample(pool, name, loops, workers, on_wait=on_wait)
        elapsed = sample["seconds"]
        if elapsed >= target * 0.9:
            return loops
        multiplier = min(8.0, max(1.2, target / max(elapsed, 1e-9)))
        loops = max(loops + 1, math.ceil(loops * multiplier))
    raise RuntimeError("Не удалось откалибровать тест " + name)


def summarize(samples):
    times = [sample["seconds"] for sample in samples]
    rates = [sample["units_per_second"] for sample in samples]
    mean = statistics.mean(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0.0
    return {"median_seconds": statistics.median(times),
            "mean_seconds": mean, "min_seconds": min(times),
            "max_seconds": max(times), "stdev_seconds": stdev,
            "cv_percent": stdev / mean * 100.0,
            "median_units_per_second": statistics.median(rates)}


def cpu_model():
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        if sys.platform == "darwin":
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                timeout=3, universal_newlines=True, stderr=subprocess.DEVNULL).strip()
        if sys.platform.startswith("linux"):
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown")


def parse_linux_memory(text):
    fields = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key in ("MemTotal", "MemAvailable", "MemFree"):
            fields[key] = int(value.split()[0]) * 1024
    return fields.get("MemTotal"), fields.get("MemAvailable", fields.get("MemFree"))


def parse_macos_available(text):
    page_size = int(re.search(r"page size of (\d+) bytes", text).group(1))
    pages = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key in ("Pages free", "Pages inactive"):
            pages[key] = int(value.strip().rstrip("."))
    if not pages:
        raise ValueError("vm_stat did not return memory counters")
    return sum(pages.values()) * page_size


def memory_info():
    """Physical RAM snapshot; available memory is an OS-specific estimate."""
    total, available, source = None, None, "unavailable"
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                    (name, ctypes.c_uint64) for name in (
                        "total", "available", "total_pagefile", "available_pagefile",
                        "total_virtual", "available_virtual", "extended")]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            function = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
            function.argtypes = [ctypes.POINTER(MemoryStatus)]
            function.restype = ctypes.c_int
            if not function(ctypes.byref(status)):
                raise OSError("GlobalMemoryStatusEx failed")
            total, available, source = status.total, status.available, "GlobalMemoryStatusEx"
        elif sys.platform.startswith("linux"):
            total, available = parse_linux_memory(Path("/proc/meminfo").read_text())
            source = "/proc/meminfo"
        elif sys.platform == "darwin":
            total = int(subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], timeout=3,
                universal_newlines=True, stderr=subprocess.DEVNULL).strip())
            source = "sysctl hw.memsize"
            available = parse_macos_available(subprocess.check_output(
                ["vm_stat"], timeout=3, universal_newlines=True, stderr=subprocess.DEVNULL))
            source += " + vm_stat (free+inactive estimate)"
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        pass
    # Some restricted Unix environments deny sysctl but expose sysconf.
    if total is None and hasattr(os, "sysconf"):
        try:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            source = "sysconf"
        except (OSError, ValueError):
            pass
    total = total if total is not None and total > 0 else None
    available = max(0, min(available, total)) if available is not None and total else available
    return {"total_bytes": total, "available_bytes": available, "source": source}


def automatic_list_size(memory):
    # Conservative estimates include integer objects, pointers and sort scratch.
    limits = []
    if memory["total_bytes"] is not None:
        limits.append(memory["total_bytes"] // 8)
    if memory["available_bytes"] is not None:
        limits.append(memory["available_bytes"] // 4)
    if not limits:
        return 100_000
    budget = max(0, min(limits) - 32 * 1024**2)
    for size in (DEFAULT_LIST_SIZE, 1_000_000, 100_000, 10_000):
        if size * 64 <= budget:
            return size
    return 10_000


def automatic_workers(cpu_count, memory):
    available = memory["available_bytes"]
    if available is None:
        return cpu_count
    memory_limit = max(1, (available // 2 - 64 * 1024**2) // (64 * 1024**2))
    return min(cpu_count, memory_limit)


def default_output(label):
    stem = re.sub(r"[^\w-]+", "_", label).strip("_")[:100] or "machine"
    return Path("bench_results") / (stem + ".json")


def available_cpus():
    if hasattr(os, "process_cpu_count"):
        return os.process_cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


def metadata(label):
    jit = getattr(sys, "_jit", None)
    cpu = cpu_model()
    return {"label": label or cpu, "cpu": cpu, "hostname": platform.node(),
            "memory": memory_info(),
            "os": platform.platform(), "architecture": platform.machine(),
            "pointer_bits": 64 if sys.maxsize > 2**32 else 32,
            "logical_cpus": os.cpu_count(), "available_cpus": available_cpus(),
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "python_full": sys.version, "python_compiler": platform.python_compiler(),
            "python_build": platform.python_build(),
            "python_config_args": sysconfig.get_config_var("CONFIG_ARGS"),
            "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: None)(),
            "jit_enabled": jit.is_enabled() if jit is not None else None,
            "clock_resolution_seconds": time.get_clock_info("perf_counter").resolution,
            "gc_during_workload": False}


def benchmark_mode(context, mode, workers, names, args):
    print("\n{}: {} процесс(ов).".format(mode, workers), flush=True)
    progress = BenchmarkProgress(len(names) * (1 + args.repeats))
    progress.render()
    ready = context.Queue()
    barrier = context.Barrier(workers)
    try:
        with context.Pool(workers, initializer=init_worker,
                          initargs=(barrier, ready, args.list_size)) as pool:
            for _ in range(workers):
                ready.get(timeout=120)
            settings = {}
            for name in names:
                progress.show("прогрев: " + name)
                loops = 1 if name in LIST_TESTS else calibrate(
                    pool, name, workers, args.seconds, on_wait=progress.render)
                for _ in range(args.warmups):
                    run_sample(pool, name, loops, workers, args.list_size, on_wait=progress.render)
                settings[name] = {"loops_per_worker": loops, "samples": [],
                                  "parameters": {"list_size": args.list_size, "seed": LIST_SEED,
                                                 "max_value": LIST_MAX} if name in LIST_TESTS else {},
                                  "timing_scope": "worker_operation" if name in LIST_TESTS else "pool_wall"}
                progress.advance()
            for repeat in range(args.repeats):
                offset = repeat % len(names)
                for name in names[offset:] + names[:offset]:
                    entry = settings[name]
                    progress.show("замер {}/{}: {}".format(repeat + 1, args.repeats, name))
                    sample = run_sample(pool, name, entry["loops_per_worker"], workers,
                                        args.list_size, on_wait=progress.render)
                    entry["samples"].append(sample)
                    progress.advance()
            progress.show("готово")
    finally:
        progress.close()
        ready.close()
        ready.join_thread()
    for name, entry in settings.items():
        entry["summary"] = summarize(entry["samples"])
    return {"workers": workers, "workloads": settings}


def print_summary(report):
    headers = ("Тест", "Проц.", "Медиана шаг/с", "Мед., с", "Сред., с",
               "Мин., с", "Макс., с", "Std, с", "CV, %", "Ускор.")
    rows = []
    single_workloads = report["modes"].get("single", {}).get("workloads", {})
    for mode_name, mode in report["modes"].items():
        for name, entry in mode["workloads"].items():
            s = entry["summary"]
            speedup = "-"
            if mode_name == "multi" and name in single_workloads:
                single = single_workloads[name]["summary"]["median_units_per_second"]
                speedup = "{:.2f}x".format(s["median_units_per_second"] / single)
            cv = "{:.2f}{}".format(s["cv_percent"], "*" if s["cv_percent"] > 5 else "")
            rows.append((name, str(mode["workers"]), "{:,.0f}".format(s["median_units_per_second"]),
                         "{:.3f}".format(s["median_seconds"]), "{:.3f}".format(s["mean_seconds"]),
                         "{:.3f}".format(s["min_seconds"]), "{:.3f}".format(s["max_seconds"]),
                         "{:.4f}".format(s["stdev_seconds"]), cv, speedup))
    widths = [max(len(row[index]) for row in [headers] + rows) for index in range(len(headers))]
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def table_row(row):
        return "| " + " | ".join(value.ljust(width) if index == 0 else value.rjust(width)
                                  for index, (value, width) in enumerate(zip(row, widths))) + " |"

    print("\nИтоги:")
    print(border)
    print(table_row(headers))
    print(border)
    for row in rows:
        print(table_row(row))
    print(border)


def compare(paths):
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    first = reports[0]
    for report in reports:
        if (report.get("schema_version"), report.get("suite_version")) != (SCHEMA_VERSION, SUITE_VERSION):
            raise ValueError("Несовместимая версия отчёта или набора тестов")
        if report["script_sha256"] != first["script_sha256"]:
            raise ValueError("Скрипты различаются: используйте один cpu_bench.py на всех машинах")
        for mode_name, base_mode in first["modes"].items():
            for name, base in base_mode["workloads"].items():
                entry = report["modes"].get(mode_name, {}).get("workloads", {}).get(name)
                if entry is not None and (entry["parameters"] != base["parameters"]
                                          or entry["timing_scope"] != base["timing_scope"]):
                    if name in LIST_TESTS:
                        continue
                    raise ValueError("Несопоставимые параметры теста {} / {}; проверьте --list-size".format(mode_name, name))
    print("Первый файл — база: 1.00x. Больше — быстрее.")
    for index, report in enumerate(reports):
        m = report["machine"]
        print("[{}] {} | {} | {} {} | {}".format(
            index + 1, m["label"], m["cpu"], m["implementation"], m["python_version"], m["os"]))
        relevant = ("python_version", "implementation", "pointer_bits", "gil_enabled", "jit_enabled")
        if any(m[key] != first["machine"][key] for key in relevant):
            print("    Внимание: версия/режим Python отличается от базы.")
    print("Сборки Python и ОС тоже влияют на результаты; детали сохранены в JSON.")
    for mode_name, base_mode in first["modes"].items():
        for name, base in base_mode["workloads"].items():
            base_rate = base["summary"]["median_units_per_second"]
            print("\n{} / {}:".format(mode_name, name))
            for index, report in enumerate(reports):
                mode = report["modes"].get(mode_name, {})
                entry = mode.get("workloads", {}).get(name)
                if entry is None:
                    print("  [{}] нет измерения".format(index + 1))
                    continue
                if entry["parameters"] != base["parameters"] or entry["timing_scope"] != base["timing_scope"]:
                    print("  [{}] несопоставимый размер/параметры списка: {} против {}; отношение скоростей пропущено".format(
                        index + 1, entry["parameters"].get("list_size"), base["parameters"].get("list_size")))
                    continue
                s = entry["summary"]
                print("  [{}] {:,.0f} шагов/с | {:.2f}x | {} проц. | CV {:.2f}%".format(
                    index + 1, s["median_units_per_second"],
                    s["median_units_per_second"] / base_rate, mode["workers"], s["cv_percent"]))


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Нужно положительное целое число")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Нужно положительное конечное число")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=positive_int, default=5,
                        help="Число измерений каждого теста, по умолчанию 5")
    parser.add_argument("--seconds", type=positive_float, default=1.0,
                        help="Целевая длительность одного замера, по умолчанию 1 с")
    parser.add_argument("--warmups", type=positive_int, default=1)
    parser.add_argument("--mode", choices=("single", "multi", "both"), default="both")
    parser.add_argument("--workers", type=positive_int,
                        help="Число процессов для multi; по умолчанию авто по CPU и доступной RAM")
    parser.add_argument("--tests", nargs="+", choices=tuple(WORKLOADS), default=list(WORKLOADS))
    parser.add_argument("--list-size", type=positive_int,
                        help="Чисел в generate/sort; по умолчанию авто по RAM, до 10 000 000; только single")
    parser.add_argument("--label", default="", help="Название машины, например Ryzen7900X")
    parser.add_argument("--output", type=Path, help="Путь к JSON; по умолчанию bench_results/<процессор>.json, с перезаписью")
    parser.add_argument("--compare", nargs="+", type=Path, help="Сравнить сохранённые JSON без запуска тестов; первый — база")
    args = parser.parse_args()
    if args.compare:
        compare(args.compare)
        return
    names = list(dict.fromkeys(args.tests))
    multi_names = [name for name in names if name not in LIST_TESTS]
    if args.mode == "multi" and not multi_names:
        parser.error("generate/sort выполняются только в single; используйте --mode single")
    machine = metadata(args.label)
    list_size_auto = args.list_size is None
    workers_auto = args.workers is None
    if list_size_auto:
        args.list_size = automatic_list_size(machine["memory"])
    if workers_auto:
        args.workers = automatic_workers(machine["available_cpus"], machine["memory"])
    timestamp = datetime.datetime.now(datetime.timezone.utc)
    output = args.output or default_output(machine["label"])
    report = {"schema_version": SCHEMA_VERSION, "suite_version": SUITE_VERSION,
              "script_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
              "started_at_utc": timestamp.isoformat(), "machine": machine,
              "settings": {"repeats": args.repeats, "target_seconds": args.seconds,
                           "warmups": args.warmups, "tests": names,
                           "list_size": args.list_size, "list_seed": LIST_SEED,
                           "list_size_auto": list_size_auto, "workers_auto": workers_auto,
                           "start_method": "spawn", "rotation": "cyclic"}, "modes": {}}
    print("{} | {}".format(machine["label"], machine["cpu"]))
    print("{} {} | {} | {}-bit".format(machine["implementation"], machine["python_version"],
                                         machine["os"], machine["pointer_bits"]))
    memory = machine["memory"]
    total_text = "{:.2f} GiB".format(memory["total_bytes"] / 1024**3) if memory["total_bytes"] else "не определена"
    available_text = "{:.2f} GiB".format(memory["available_bytes"] / 1024**3) if memory["available_bytes"] is not None else "не определена"
    print("RAM: {}; доступно (оценка): {}; логических CPU: {}.".format(
        total_text, available_text, machine["available_cpus"]))
    context = mp.get_context("spawn")
    modes = [("single", 1), ("multi", args.workers)] if args.mode == "both" else [
        (args.mode, 1 if args.mode == "single" else args.workers)]
    for mode, workers in modes:
        selected = names if mode == "single" else multi_names
        if selected:
            report["modes"][mode] = benchmark_mode(context, mode, workers, selected, args)
    report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print_summary(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    mp.freeze_support()
    main()
