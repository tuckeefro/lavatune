"""Check the measurement contract and retained evidence, not performance thresholds."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from benchmark_study import COMMIT, SCHEMA, SIZES, validate_rows


def design_rows():
    return [{"source_commit": COMMIT, "width": w, "height": h, "repeat": r,
             "method": method, "frames": 200,
             "execution_order": int(method == "analytic_contour") ^ (r % 2),
             "ms_per_frame": float(r + 1)}
            for w, h in SIZES for r in range(5)
            for method in ("scalar_field", "analytic_contour")]


def read_rows():
    with (ROOT / "evidence/main-study/benchmark-runs.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for field in ("width", "height", "repeat", "frames", "execution_order"):
            row[field] = int(row[field])
        row["ms_per_frame"] = float(row["ms_per_frame"])
    return rows


class DesignContractTests(unittest.TestCase):
    def test_complete_alternating_design_is_accepted(self):
        validate_rows(design_rows(), 200, 5)

    def test_duplicate_observation_is_rejected(self):
        rows = design_rows()
        with self.assertRaises(ValueError):
            validate_rows(rows + [rows[0]], 200, 5)

    def test_missing_pair_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_rows(design_rows()[:-1], 200, 5)

    def test_wrong_source_or_input_length_is_rejected(self):
        for field, value in (("source_commit", "wrong"), ("frames", 120)):
            with self.subTest(field=field):
                rows = design_rows()
                rows[0][field] = value
                with self.assertRaises(ValueError):
                    validate_rows(rows, 200, 5)

    def test_nonfinite_and_nonpositive_timings_are_rejected(self):
        for timing in (math.nan, math.inf, 0, -1):
            with self.subTest(timing=timing):
                rows = design_rows()
                rows[0]["ms_per_frame"] = timing
                with self.assertRaises(ValueError):
                    validate_rows(rows, 200, 5)

    def test_wrong_execution_order_is_rejected(self):
        rows = design_rows()
        rows[0]["execution_order"] = 1
        with self.assertRaises(ValueError):
            validate_rows(rows, 200, 5)

    def test_database_rejects_duplicate_keys(self):
        with sqlite3.connect(":memory:") as connection:
            connection.executescript(SCHEMA)
            row = design_rows()[0]
            sql = "INSERT INTO benchmark_runs VALUES (:source_commit,:width,:height,:repeat,:method,:frames,:execution_order,:ms_per_frame)"
            connection.execute(sql, row)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(sql, row)

    def test_database_rejects_invalid_method_and_dimensions(self):
        for field, value in (("method", "unknown"), ("width", 0), ("ms_per_frame", -1)):
            with self.subTest(field=field), sqlite3.connect(":memory:") as connection:
                connection.executescript(SCHEMA)
                row = design_rows()[0]
                row[field] = value
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO benchmark_runs VALUES (:source_commit,:width,:height,:repeat,:method,:frames,:execution_order,:ms_per_frame)", row)


class RetainedEvidenceTests(unittest.TestCase):
    def test_raw_csv_has_all_thirty_declared_observations(self):
        validate_rows(read_rows(), 200, 5)

    def test_summary_matches_raw_data_and_hash(self):
        rows = read_rows()
        report = json.loads((ROOT / "evidence/main-study/benchmark-summary.json").read_text())
        self.assertEqual(report["raw_csv_sha256"], hashlib.sha256((ROOT / "evidence/main-study/benchmark-runs.csv").read_bytes()).hexdigest())
        self.assertEqual(report["recorded_runs"], len(rows))
        for result in report["results"]:
            medians = {}
            for method, summary in result["methods"].items():
                values = [row["ms_per_frame"] for row in rows if (row["width"], row["height"], row["method"]) == (result["width"], result["height"], method)]
                medians[method] = statistics.median(values)
                self.assertEqual(summary["median_ms_per_frame"], medians[method])
                self.assertEqual(summary["min_ms_per_frame"], min(values))
                self.assertEqual(summary["max_ms_per_frame"], max(values))
            self.assertEqual(result["ratio_of_run_medians"], medians["scalar_field"] / medians["analytic_contour"])

    def test_database_roundtrip_matches_csv_and_means(self):
        columns = ("source_commit", "width", "height", "repeat", "method", "frames", "execution_order", "ms_per_frame")
        rows = read_rows()
        with sqlite3.connect(f"file:{ROOT / 'evidence/main-study/benchmark.sqlite'}?mode=ro", uri=True) as connection:
            self.assertEqual(sorted(connection.execute("SELECT * FROM benchmark_runs").fetchall()), sorted(tuple(row[field] for field in columns) for row in rows))
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            for w, h, method, repeats, mean, minimum, maximum in connection.execute("SELECT * FROM benchmark_means"):
                values = [row["ms_per_frame"] for row in rows if (row["width"], row["height"], row["method"]) == (w, h, method)]
                self.assertEqual(repeats, 5)
                self.assertAlmostEqual(mean, statistics.mean(values))
                self.assertEqual((minimum, maximum), (min(values), max(values)))


if __name__ == "__main__":
    unittest.main()
