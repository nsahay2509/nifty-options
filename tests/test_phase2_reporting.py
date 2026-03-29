import csv
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_trades import (
    extract_trades_from_events,
    export_trade_quality_summary,
    run_analysis,
    update_daily_summary,
    update_trade_summary,
    write_csv_rows,
)
from scripts.utils import ensure_complete_ltp_map


class EnsureCompleteLtpMapTests(unittest.TestCase):
    def test_fills_missing_ids_via_fallback_fetch(self):
        calls = []

        def fake_fetch(ids):
            calls.append(list(ids))
            return {ids[0]: 101.5}

        ltp_map, complete = ensure_complete_ltp_map(
            [111],
            ltp_map={},
            fetcher=fake_fetch,
            sleep_fn=lambda _: None,
        )

        self.assertTrue(complete)
        self.assertEqual(ltp_map[111], 101.5)
        self.assertEqual(calls, [[111]])

    def test_reports_incomplete_after_retry(self):
        calls = []

        def fake_fetch(ids):
            calls.append(list(ids))
            return {ids[0]: None}

        ltp_map, complete = ensure_complete_ltp_map(
            [222],
            ltp_map={},
            fetcher=fake_fetch,
            sleep_fn=lambda _: None,
        )

        self.assertFalse(complete)
        self.assertIsNone(ltp_map[222])
        self.assertEqual(calls, [[222], [222]])


class AnalyzeTradesTests(unittest.TestCase):
    def write_system_pnl(self, path: Path, rows):
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "trade_id",
                "state",
                "regime",
                "strike",
                "expiry",
                "realised",
                "unrealised",
                "total",
            ])
            writer.writerows(rows)

    def read_rows(self, path: Path):
        with path.open() as f:
            return list(csv.reader(f))

    def test_run_analysis_builds_trade_and_daily_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system_pnl_file = base / "system_pnl.csv"
            trade_summary_file = base / "trade_summary.csv"
            daily_summary_file = base / "daily_summary.csv"

            self.write_system_pnl(system_pnl_file, [
                ["2026-03-28 10:00:05", "t1", "ENTRY", "SELL_PE", "22500", "2026-03-30", "0.00", "0.00", "0.00"],
                ["2026-03-28 10:05:05", "", "EXIT", "", "", "", "150.00", "0.00", "150.00"],
                ["2026-03-28 11:00:05", "t2", "ENTRY", "SELL_CE", "22450", "2026-03-30", "150.00", "0.00", "150.00"],
                ["2026-03-28 11:04:05", "", "EXIT", "", "", "", "25.00", "0.00", "25.00"],
            ])

            trades = run_analysis(
                system_pnl_file,
                trade_summary_file,
                daily_summary_file,
            )

            self.assertEqual(len(trades), 2)

            trade_rows = self.read_rows(trade_summary_file)
            self.assertEqual(trade_rows[0], [
                "trade_id",
                "entry_time",
                "exit_time",
                "time_in_trade_min",
                "trade_type",
                "strike",
                "expiry",
                "trade_pnl",
            ])
            self.assertEqual(trade_rows[1][0], "t1")
            self.assertEqual(trade_rows[1][-1], "150.0")
            self.assertEqual(trade_rows[2][0], "t2")
            self.assertEqual(trade_rows[2][-1], "-125.0")

            daily_rows = self.read_rows(daily_summary_file)
            self.assertEqual(daily_rows[1], [
                "2026-03-28",
                "2",
                "1",
                "1",
                "25.0",
                "200",
                "-175.0",
            ])

    def test_combined_summary_can_be_generated_from_multiple_trade_sets(self):
        with tempfile.TemporaryDirectory() as tmp:
            trade_summary_file = Path(tmp) / "combined_trade_summary.csv"
            daily_summary_file = Path(tmp) / "combined_daily_summary.csv"

            combined_trades = [
                {
                    "trade_id": "sell_1",
                    "entry_time": "2026-03-28 10:00:05",
                    "exit_time": "2026-03-28 10:04:05",
                    "time_in_trade_min": 4,
                    "trade_type": "SELL_PE",
                    "strike": "22500",
                    "expiry": "2026-03-30",
                    "trade_pnl": 100.0,
                },
                {
                    "trade_id": "buy_1",
                    "entry_time": "2026-03-28 10:30:05",
                    "exit_time": "2026-03-28 10:40:05",
                    "time_in_trade_min": 10,
                    "trade_type": "SELL_CE",
                    "strike": "22550",
                    "expiry": "2026-03-30",
                    "trade_pnl": 50.0,
                },
            ]

            update_trade_summary(combined_trades, trade_summary_file)
            update_daily_summary(combined_trades, daily_summary_file)

            daily_rows = self.read_rows(daily_summary_file)
            self.assertEqual(daily_rows[1], [
                "2026-03-28",
                "2",
                "2",
                "0",
                "150.0",
                "200",
                "-50.0",
            ])

    def test_export_trade_quality_summary_writes_header_for_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "quality.csv"

            rows = export_trade_quality_summary(Path(tmp) / "missing.csv", target)

            self.assertEqual(rows, [])
            written = self.read_rows(target)
            self.assertEqual(written[0][0], "side")

    def test_write_csv_rows_writes_header_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            write_csv_rows(path, ["a", "b"], [{"a": "1", "b": "2"}])

            rows = self.read_rows(path)
            self.assertEqual(rows, [["a", "b"], ["1", "2"]])

    def test_extract_trades_from_events_uses_trade_event_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "trade_events.csv"
            with source.open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "side", "trade_id", "regime", "entry_signal", "entry_time", "exit_time",
                    "time_in_trade_min", "strike", "expiry", "entry_spot", "entry_direction_score",
                    "entry_bias", "exit_reason", "trade_pnl", "exit_spot", "exit_direction_score",
                    "exit_bias", "peak_pnl", "drawdown_from_peak", "cooldown_applied_min",
                    "diagnostic_context",
                ])
                writer.writerow([
                    "SELL", "t1", "SELL_PE", "SELL_PE", "2026-03-28 10:00:05", "2026-03-28 10:05:05",
                    "5", "22500", "2026-03-30", "22500.0", "0.45", "25.0", "TRAIL_PROFIT", "150.0",
                    "22520.0", "0.30", "20.0", "220.0", "70.0", "5", "ctx",
                ])

            trades = extract_trades_from_events(source)

            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["trade_id"], "t1")
            self.assertEqual(trades[0]["trade_type"], "SELL_PE")
            self.assertEqual(trades[0]["trade_pnl"], 150.0)


if __name__ == "__main__":
    unittest.main()
