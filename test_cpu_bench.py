"""Correctness, statistics and real multiprocessing CLI coverage."""

import contextlib
import copy
import ctypes
import io
import json
import math
import os
import random
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cpu_bench as bench


class BenchmarkTests(unittest.TestCase):
    def test_memory_detection_and_automatic_limits(self):
        self.assertEqual(bench.parse_linux_memory(
            "MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\nMemFree: 1024 kB\n"),
            (8 * 1024**3, 4 * 1024**3))
        self.assertEqual(bench.parse_linux_memory("MemTotal: 4096 kB\nMemFree: 256 kB\n"),
                         (4096 * 1024, 256 * 1024))
        self.assertEqual(bench.parse_macos_available(
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free: 100.\nPages active: 999.\nPages inactive: 200.\n"), 300 * 16384)
        with mock.patch.object(bench.sys, "platform", "linux"), mock.patch.object(
                bench.Path, "read_text", return_value="MemTotal: 4096 kB\nMemAvailable: 1024 kB\n"):
            self.assertEqual(bench.memory_info()["available_bytes"], 1024**2)
        with mock.patch.object(bench.sys, "platform", "darwin"), mock.patch.object(
                bench.subprocess, "check_output", side_effect=[str(8 * 1024**3),
                "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 10.\nPages inactive: 20.\n"]):
            self.assertEqual(bench.memory_info()["available_bytes"], 30 * 4096)
        def fill_windows_status(pointer):
            pointer._obj.total = 16 * 1024**3
            pointer._obj.available = 8 * 1024**3
            return 1
        windows_api = mock.Mock(side_effect=fill_windows_status)
        windows_dll = mock.Mock()
        windows_dll.GlobalMemoryStatusEx = windows_api
        with mock.patch.object(bench.sys, "platform", "win32"), mock.patch.object(
                ctypes, "WinDLL", return_value=windows_dll, create=True):
            self.assertEqual(bench.memory_info(), {"total_bytes": 16 * 1024**3,
                "available_bytes": 8 * 1024**3, "source": "GlobalMemoryStatusEx"})
        with mock.patch.object(bench.sys, "platform", "darwin"), mock.patch.object(
                bench.subprocess, "check_output", side_effect=OSError), mock.patch.object(
                bench.os, "sysconf", side_effect=OSError):
            self.assertEqual(bench.memory_info()["total_bytes"], None)
        for total, available, expected in (
                (16 * 1024**3, 8 * 1024**3, 10_000_000),
                (4 * 1024**3, 1024**3, 1_000_000),
                (1024**3, 256 * 1024**2, 100_000),
                (1024**3, 0, 10_000),
                (None, None, 100_000)):
            memory = {"total_bytes": total, "available_bytes": available}
            self.assertEqual(bench.automatic_list_size(memory), expected)
        self.assertEqual(bench.automatic_workers(24, {"available_bytes": 4 * 1024**3}), 24)
        self.assertEqual(bench.automatic_workers(24, {"available_bytes": 256 * 1024**2}), 1)
        self.assertEqual(bench.automatic_workers(4, {"available_bytes": None}), 4)

    def test_no_argument_run_autodetects_and_overwrites(self):
        memory = {"total_bytes": 8 * 1024**3, "available_bytes": 4 * 1024**3, "source": "test"}
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with mock.patch.object(bench.sys, "argv", ["cpu_bench.py"]), \
                        mock.patch.object(bench, "cpu_model", return_value="Example CPU"), \
                        mock.patch.object(bench, "available_cpus", return_value=4), \
                        mock.patch.object(bench, "memory_info", return_value=memory), \
                        mock.patch.object(bench, "benchmark_mode", side_effect=lambda context, mode, workers, names, args:
                                          {"workers": workers, "workloads": {}}) as runner, \
                        contextlib.redirect_stdout(io.StringIO()):
                    bench.main()
                    output = Path("bench_results/Example_CPU.json")
                    report = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(report["machine"]["memory"], memory)
                    self.assertEqual(report["settings"]["list_size"], 10_000_000)
                    self.assertTrue(report["settings"]["list_size_auto"])
                    self.assertTrue(report["settings"]["workers_auto"])
                    self.assertEqual(report["settings"]["repeats"], 5)
                    self.assertEqual(runner.call_args_list[0].args[2], 1)
                    self.assertEqual(runner.call_args_list[1].args[2], 4)
                    self.assertEqual(len(runner.call_args_list[0].args[3]), 6)
                    self.assertEqual(len(runner.call_args_list[1].args[3]), 4)
                    output.write_text("old result", encoding="utf-8")
                    bench.main()
                    self.assertEqual(len(list(Path("bench_results").glob("*.json"))), 1)
                    self.assertEqual(json.loads(output.read_text())["machine"]["cpu"], "Example CPU")
            finally:
                os.chdir(original_cwd)

    def test_kernel_reference_results(self):
        # Independent modulo-based 32-bit reference for the bitwise recurrence.
        x = 0x12345678
        for _ in range(20_000):
            x = (x ^ (x * 8192)) % 2**32
            x ^= x // 131072
            x = (x ^ (x * 32)) % 2**32
        self.assertEqual(bench.integer_mix(), x)
        reference_primes = sum(
            all(n % d for d in range(2, math.isqrt(n) + 1))
            for n in range(100_000, 102_000))
        self.assertEqual(bench.prime_search(), reference_primes)
        self.assertAlmostEqual(bench.pi_integral(), math.pi, places=8)
        for name, (function, _, _) in bench.WORKLOADS.items():
            if name in bench.LIST_TESTS:
                continue
            bench.check_result(name, function())
            with self.assertRaises(RuntimeError):
                bench.check_result(name, -1)

    def test_reproducible_list_jobs_and_sort_validation(self):
        rng = random.Random(bench.LIST_SEED)
        reference = [rng.randint(0, bench.LIST_MAX) for _ in range(256)]
        self.assertEqual(bench.generate_list(256), reference)
        expected = {"count": 256, "sum": sum(reference),
                    "min": min(reference), "max": max(reference)}
        with mock.patch.object(bench, "_list_size", 256), mock.patch.object(bench, "_barrier"):
            for name in bench.LIST_TESTS:
                result = bench.run_list_job(name)
                self.assertEqual(result["result"], expected)
                self.assertGreater(result["seconds"], 0)

        class BrokenSort(list):
            def sort(self):
                pass

        with mock.patch.object(bench, "_list_size", 3), mock.patch.object(bench, "_barrier"):
            with mock.patch.object(bench, "generate_list", return_value=BrokenSort([3, 1, 2])):
                with self.assertRaisesRegex(RuntimeError, "сортировки"):
                    bench.run_list_job("sort")

    def test_statistics_and_single_sample(self):
        samples = [{"seconds": float(t), "units_per_second": 200.0 / t} for t in (1, 2, 3)]
        summary = bench.summarize(samples)
        self.assertEqual(summary["median_seconds"], 2.0)
        self.assertEqual(summary["mean_seconds"], 2.0)
        self.assertEqual(summary["stdev_seconds"], 1.0)
        self.assertEqual(summary["cv_percent"], 50.0)
        self.assertEqual(summary["median_units_per_second"], 100.0)
        self.assertEqual(bench.summarize(samples[:1])["stdev_seconds"], 0.0)

    def test_full_cli_spawn_and_comparison(self):
        script = str(Path(bench.__file__).resolve())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.json"
            command = [sys.executable, script, "--workers", "2", "--repeats", "2",
                       "--seconds", "0.02", "--list-size", "2000",
                       "--label", "smoke", "--output", str(output)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            for mode, workers in (("single", 1), ("multi", 2)):
                if mode == "multi":
                    self.assertTrue(set(bench.LIST_TESTS).isdisjoint(report["modes"][mode]["workloads"]))
                for name, entry in report["modes"][mode]["workloads"].items():
                    self.assertEqual(len(entry["samples"]), 2)
                    for sample in entry["samples"]:
                        self.assertEqual(len({w["pid"] for w in sample["workers"]}), workers)
                        units = 2000 if name in bench.LIST_TESTS else workers * entry["loops_per_worker"] * bench.WORKLOADS[name][1]
                        self.assertEqual(sample["units"], units)
                        self.assertAlmostEqual(sample["units_per_second"], sample["units"] / sample["seconds"])
                        if name in bench.LIST_TESTS:
                            self.assertEqual(sample["seconds"], sample["workers"][0]["seconds"])
                            self.assertEqual(entry["parameters"]["list_size"], 2000)
                            self.assertEqual(entry["timing_scope"], "worker_operation")
            comparison = subprocess.run([sys.executable, script, "--compare", str(output), str(output)],
                                        capture_output=True, text=True, timeout=10)
            self.assertEqual(comparison.returncode, 0, comparison.stderr)
            self.assertEqual(comparison.stdout.count("1.00x |"), 20)
            rerun_command = command + ["--label", "overwrite-check"]
            duplicate = subprocess.run(rerun_command, capture_output=True, text=True, timeout=60)
            self.assertEqual(duplicate.returncode, 0, duplicate.stdout + duplicate.stderr)
            overwritten = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(overwritten["machine"]["label"], "overwrite-check")
            changed = copy.deepcopy(report)
            changed["script_sha256"] = "different"
            other = Path(directory) / "other.json"
            other.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Скрипты различаются"):
                with contextlib.redirect_stdout(io.StringIO()):
                    bench.compare([output, other])
            changed = copy.deepcopy(report)
            changed["modes"]["single"]["workloads"]["sort"]["parameters"]["list_size"] = 3000
            other.write_text(json.dumps(changed), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                bench.compare([output, other])
            self.assertIn("несопоставимый размер", captured.getvalue())
            self.assertIn("multi / pi", captured.getvalue())
            invalid = subprocess.run([sys.executable, script, "--mode", "multi", "--tests", "sort"],
                                     capture_output=True, text=True, timeout=10)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("только в single", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
