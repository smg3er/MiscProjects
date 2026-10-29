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
import statistics
import subprocess
import sys
import sysconfig
import time


SUITE_VERSION = 1
SCHEMA_VERSION = 1
_barrier = None


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
}


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


def init_worker(barrier, ready):
    global _barrier
    _barrier = barrier
    gc.disable()
    ready.put(os.getpid())


def run_job(job):
    name, loops = job
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


def run_sample(pool, name, loops, workers):
    start = time.perf_counter()
    jobs = pool.map(run_job, [(name, loops)] * workers, chunksize=1)
    seconds = time.perf_counter() - start
    units = loops * workers * WORKLOADS[name][1]
    return {"seconds": seconds, "units": units,
            "units_per_second": units / seconds,
            "worker_cpu_seconds": sum(job["cpu_seconds"] for job in jobs),
            "workers": jobs}


def calibrate(pool, name, workers, target):
    loops = 1
    for _ in range(12):
        sample = run_sample(pool, name, loops, workers)
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


def available_cpus():
    if hasattr(os, "process_cpu_count"):
        return os.process_cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


def metadata(label):
    jit = getattr(sys, "_jit", None)
    return {"label": label or platform.node(), "cpu": cpu_model(),
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
    print("\n{}: {} процесс(ов). Калибровка и прогрев...".format(mode, workers), flush=True)
    ready = context.Queue()
    barrier = context.Barrier(workers)
    try:
        with context.Pool(workers, initializer=init_worker,
                          initargs=(barrier, ready)) as pool:
            for _ in range(workers):
                ready.get(timeout=120)
            settings = {}
            for name in names:
                loops = calibrate(pool, name, workers, args.seconds)
                for _ in range(args.warmups):
                    run_sample(pool, name, loops, workers)
                settings[name] = {"loops_per_worker": loops, "samples": []}
                print("  {}: {} блоков/процесс".format(name, loops), flush=True)
            for repeat in range(args.repeats):
                offset = repeat % len(names)
                for name in names[offset:] + names[:offset]:
                    entry = settings[name]
                    sample = run_sample(pool, name, entry["loops_per_worker"], workers)
                    entry["samples"].append(sample)
                    print("  {:2d}/{:2d} {:7s}: {:.3f} с | {:,.0f} шагов/с".format(
                        repeat + 1, args.repeats, name, sample["seconds"],
                        sample["units_per_second"]), flush=True)
    finally:
        ready.close()
        ready.join_thread()
    for name, entry in settings.items():
        entry["summary"] = summarize(entry["samples"])
    return {"workers": workers, "workloads": settings}


def print_summary(report):
    print("\nИтоги: больше шагов/с — лучше; CV — разброс длительности.")
    print("{:<8} {:>8} {:>15} {:>10} {:>10} {:>10} {:>7}".format(
        "Тест", "Проц.", "Медиана шаг/с", "Мед., с", "Сред., с", "Мин., с", "CV, %"))
    for mode in report["modes"].values():
        for name, entry in mode["workloads"].items():
            s = entry["summary"]
            print("{:<8} {:>8} {:>15,.0f} {:>10.3f} {:>10.3f} {:>10.3f} {:>7.2f}".format(
                name, mode["workers"], s["median_units_per_second"],
                s["median_seconds"], s["mean_seconds"], s["min_seconds"], s["cv_percent"]))
            print("         std={:.4f} с; max={:.3f} с; {}".format(
                s["stdev_seconds"], s["max_seconds"], WORKLOADS[name][2]))
            if s["cv_percent"] > 5:
                print("         Заметный разброс (>5%): повторите при меньшей фоновой нагрузке.")
    if "single" in report["modes"] and "multi" in report["modes"]:
        print("\nУскорение multi / single по медиане производительности:")
        for name in report["modes"]["single"]["workloads"]:
            single = report["modes"]["single"]["workloads"][name]["summary"]["median_units_per_second"]
            multi = report["modes"]["multi"]["workloads"][name]["summary"]["median_units_per_second"]
            print("  {}: {:.2f}x".format(name, multi / single))


def compare(paths):
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    first = reports[0]
    for report in reports:
        if (report.get("schema_version"), report.get("suite_version")) != (SCHEMA_VERSION, SUITE_VERSION):
            raise ValueError("Несовместимая версия отчёта или набора тестов")
        if report["script_sha256"] != first["script_sha256"]:
            raise ValueError("Скрипты различаются: используйте один cpu_bench.py на всех машинах")
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
    parser.add_argument("--repeats", type=positive_int, default=10)
    parser.add_argument("--seconds", type=positive_float, default=1.0,
                        help="Целевая длительность одного замера, по умолчанию 1 с")
    parser.add_argument("--warmups", type=positive_int, default=1)
    parser.add_argument("--mode", choices=("single", "multi", "both"), default="both")
    parser.add_argument("--workers", type=positive_int, default=available_cpus(),
                        help="Число процессов для multi; по умолчанию все доступные CPU")
    parser.add_argument("--tests", nargs="+", choices=tuple(WORKLOADS), default=list(WORKLOADS))
    parser.add_argument("--label", default="", help="Название машины, например Ryzen7900X")
    parser.add_argument("--output", type=Path, help="Путь к JSON; по умолчанию bench_results/<машина>_<время>.json")
    parser.add_argument("--compare", nargs="+", type=Path, help="Сравнить сохранённые JSON без запуска тестов; первый — база")
    args = parser.parse_args()
    if args.compare:
        compare(args.compare)
        return
    names = list(dict.fromkeys(args.tests))
    machine = metadata(args.label)
    timestamp = datetime.datetime.now(datetime.timezone.utc)
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in machine["label"]) or "machine"
    output = args.output or Path("bench_results") / (safe_label + "_" + timestamp.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    if output.exists():
        parser.error("Файл уже существует: {}. Укажите новый --output.".format(output))
    report = {"schema_version": SCHEMA_VERSION, "suite_version": SUITE_VERSION,
              "script_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
              "started_at_utc": timestamp.isoformat(), "machine": machine,
              "settings": {"repeats": args.repeats, "target_seconds": args.seconds,
                           "warmups": args.warmups, "tests": names,
                           "start_method": "spawn", "rotation": "cyclic"}, "modes": {}}
    print("{} | {}".format(machine["label"], machine["cpu"]))
    print("{} {} | {} | {}-bit".format(machine["implementation"], machine["python_version"],
                                         machine["os"], machine["pointer_bits"]))
    print("{} замеров; цель {:.2f} с/замер; single=1 процесс, multi={} процессов.".format(
        args.repeats, args.seconds, args.workers))
    print("Измеряется производительность Python на этой машине. Шаги разных тестов не складываются.")
    context = mp.get_context("spawn")
    modes = [("single", 1), ("multi", args.workers)] if args.mode == "both" else [
        (args.mode, 1 if args.mode == "single" else args.workers)]
    for mode, workers in modes:
        report["modes"][mode] = benchmark_mode(context, mode, workers, names, args)
    report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print_summary(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never silently overwrite a previous run.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print("\nJSON сохранён: {}".format(output.resolve()))


if __name__ == "__main__":
    mp.freeze_support()
    main()
