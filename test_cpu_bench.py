"""Correctness, statistics and real multiprocessing CLI coverage."""

import contextlib
import copy
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cpu_bench as bench


class BenchmarkTests(unittest.TestCase):
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
            bench.check_result(name, function())
            with self.assertRaises(RuntimeError):
                bench.check_result(name, -1)

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
                       "--seconds", "0.02", "--label", "smoke", "--output", str(output)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            for mode, workers in (("single", 1), ("multi", 2)):
                for name, entry in report["modes"][mode]["workloads"].items():
                    self.assertEqual(len(entry["samples"]), 2)
                    for sample in entry["samples"]:
                        self.assertEqual(len({w["pid"] for w in sample["workers"]}), workers)
                        self.assertEqual(sample["units"], workers * entry["loops_per_worker"] * bench.WORKLOADS[name][1])
                        self.assertAlmostEqual(sample["units_per_second"], sample["units"] / sample["seconds"])
            comparison = subprocess.run([sys.executable, script, "--compare", str(output), str(output)],
                                        capture_output=True, text=True, timeout=10)
            self.assertEqual(comparison.returncode, 0, comparison.stderr)
            self.assertEqual(comparison.stdout.count("1.00x |"), 16)
            duplicate = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("Файл уже существует", duplicate.stderr)
            changed = copy.deepcopy(report)
            changed["script_sha256"] = "different"
            other = Path(directory) / "other.json"
            other.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Скрипты различаются"):
                with contextlib.redirect_stdout(io.StringIO()):
                    bench.compare([output, other])


if __name__ == "__main__":
    unittest.main()
