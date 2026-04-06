import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.app_config import IST
from scripts.clock import FrozenClock
from scripts.state_utils import atomic_write_json, safe_load_json
import scripts.paper_trade_engine as sell_engine
import scripts.paper_trade_engine_buy as buy_engine
import scripts.paper_trade_engine_core as engine_core


class AtomicWriteJsonTests(unittest.TestCase):
    def test_atomic_write_json_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            payload = {"status": "OPEN", "value": 123}

            atomic_write_json(path, payload, indent=2)

            self.assertEqual(safe_load_json(path, {}), payload)


class _EngineTempDirMixin:
    def make_trade_file(self, tmp: str, filename: str) -> Path:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / filename

    def make_results_dir(self, tmp: str) -> Path:
        result_dir = Path(tmp) / "data" / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        return result_dir

    def make_clock(self, ts: str) -> FrozenClock:
        return FrozenClock(datetime.fromisoformat(ts).replace(tzinfo=IST))

    def make_history(self, close=22500.0):
        return [
            {
                "ts": f"2026-03-28 10:{i:02d}:00",
                "open": close - 20,
                "high": close + 10,
                "low": close - 30,
                "close": close + i,
            }
            for i in range(25)
        ]


class SellEngineRecoveryTests(unittest.TestCase, _EngineTempDirMixin):
    def test_sync_from_disk_recovers_open_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_pos_file = self.make_trade_file(tmp, "open_position.json")
            atomic_write_json(open_pos_file, {
                "status": "OPEN",
                "trade_id": "sell_1",
                "regime": "SELL_PE",
                "strike": 22500,
                "expiry": "2026-03-30",
                "entry_time": "2026-03-28 10:05:00",
                "legs": [
                    {
                        "security_id": 12345,
                        "entry_price": 101.5,
                        "lots": 1,
                        "type": "PE",
                    }
                ],
            }, indent=2)

            old_open_pos = sell_engine.OPEN_POS_FILE
            old_base_dir = sell_engine.BASE_DIR
            try:
                sell_engine.OPEN_POS_FILE = open_pos_file
                sell_engine.BASE_DIR = Path(tmp)

                engine = sell_engine.PaperTradeEngine(clock=self.make_clock("2026-03-28T10:06:00"))

                self.assertEqual(engine.state, "IN_POSITION")
                self.assertIsNotNone(engine.position)
                self.assertEqual(engine.position.trade_id, "sell_1")
                self.assertEqual(engine.position.pe_security_id, 12345)
                self.assertEqual(engine.active_regime, "SELL_PE")
            finally:
                sell_engine.OPEN_POS_FILE = old_open_pos
                sell_engine.BASE_DIR = old_base_dir

    def test_reset_for_new_day_clears_done_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_pos_file = self.make_trade_file(tmp, "open_position.json")

            old_open_pos = sell_engine.OPEN_POS_FILE
            old_base_dir = sell_engine.BASE_DIR
            try:
                sell_engine.OPEN_POS_FILE = open_pos_file
                sell_engine.BASE_DIR = Path(tmp)

                engine = sell_engine.PaperTradeEngine(clock=self.make_clock("2026-03-28T09:21:00"))
                engine.state = "DONE"
                engine.session_date = date(2026, 3, 27)
                engine.position = sell_engine.Position(
                    trade_id="old_trade",
                    regime="SELL_CE",
                    strike=22400,
                    expiry="2026-03-30",
                    ce_security_id=111,
                    pe_security_id=None,
                    entry_time=datetime(2026, 3, 27, 15, 0, tzinfo=IST),
                )

                engine.reset_for_new_day(
                    datetime(2026, 3, 28, 9, 21, tzinfo=IST)
                )

                self.assertEqual(engine.state, "FLAT")
                self.assertIsNone(engine.position)
                self.assertEqual(engine.session_date, date(2026, 3, 28))
            finally:
                sell_engine.OPEN_POS_FILE = old_open_pos
                sell_engine.BASE_DIR = old_base_dir


class BuyEngineRecoveryTests(unittest.TestCase, _EngineTempDirMixin):
    def test_sync_from_disk_recovers_open_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_pos_file = self.make_trade_file(tmp, "open_position_buy.json")
            atomic_write_json(open_pos_file, {
                "status": "OPEN",
                "trade_id": "buy_1",
                "regime": "SELL_CE",
                "strike": 22550,
                "expiry": "2026-03-30",
                "entry_time": "2026-03-28 10:06:00",
                "legs": [
                    {
                        "security_id": 54321,
                        "entry_price": 88.0,
                        "lots": 1,
                        "type": "PE",
                    }
                ],
            }, indent=2)

            old_open_pos = buy_engine.OPEN_POS_FILE
            old_base_dir = buy_engine.BASE_DIR
            try:
                buy_engine.OPEN_POS_FILE = open_pos_file
                buy_engine.BASE_DIR = Path(tmp)

                engine = buy_engine.PaperTradeEngine(clock=self.make_clock("2026-03-28T10:07:00"))

                self.assertEqual(engine.state, "IN_POSITION")
                self.assertIsNotNone(engine.position)
                self.assertEqual(engine.position.trade_id, "buy_1")
                self.assertEqual(engine.position.pe_security_id, 54321)
                self.assertEqual(engine.active_regime, "SELL_CE")
            finally:
                buy_engine.OPEN_POS_FILE = old_open_pos
                buy_engine.BASE_DIR = old_base_dir


class EngineMappingTests(unittest.TestCase):
    def test_sell_and_buy_engines_keep_different_leg_mapping(self):
        clock = FrozenClock(datetime(2026, 3, 28, 10, 0, tzinfo=IST))
        sell = sell_engine.PaperTradeEngine(clock=clock)
        buy = buy_engine.PaperTradeEngine(clock=clock)

        atm = {
            "ce_security_id": 111,
            "pe_security_id": 222,
        }

        self.assertEqual(sell.resolve_entry_ids("SELL_PE", atm), (None, 222))
        self.assertEqual(sell.resolve_entry_ids("SELL_CE", atm), (111, None))
        self.assertEqual(buy.resolve_entry_ids("SELL_PE", atm), (111, None))
        self.assertEqual(buy.resolve_entry_ids("SELL_CE", atm), (None, 222))


class TradeQualityRuleTests(unittest.TestCase, _EngineTempDirMixin):
    def test_entry_requires_fresh_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_pos_file = self.make_trade_file(tmp, "open_position.json")
            self.make_results_dir(tmp)

            old_open_pos = sell_engine.OPEN_POS_FILE
            old_base_dir = sell_engine.BASE_DIR
            old_resolver = engine_core.get_atm_straddle
            try:
                sell_engine.OPEN_POS_FILE = open_pos_file
                sell_engine.BASE_DIR = Path(tmp)
                engine_core.get_atm_straddle = lambda spot: {
                    "strike": 22500,
                    "expiry": "2026-03-30",
                    "ce_security_id": 111,
                    "pe_security_id": 222,
                }

                engine = sell_engine.PaperTradeEngine(clock=self.make_clock("2026-03-28T10:05:00"))
                engine.tick(
                    signal=None,
                    regime="SELL_PE",
                    history=self.make_history(),
                    ltp_map={111: 100.0, 222: 100.0},
                )

                self.assertEqual(engine.state, "FLAT")
                self.assertIsNone(engine.position)
            finally:
                sell_engine.OPEN_POS_FILE = old_open_pos
                sell_engine.BASE_DIR = old_base_dir
                engine_core.get_atm_straddle = old_resolver

    def test_min_hold_blocks_soft_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_pos_file = self.make_trade_file(tmp, "open_position.json")
            self.make_results_dir(tmp)
            now = datetime(2026, 3, 28, 10, 2, tzinfo=IST)

            atomic_write_json(open_pos_file, {
                "status": "OPEN",
                "trade_id": "hold_1",
                "regime": "SELL_PE",
                "strike": 22500,
                "expiry": "2026-03-30",
                "entry_time": "2026-03-28 10:00:00",
                "side": "SELL",
                "entry_signal": "SELL_PE",
                "entry_spot": 22500.0,
                "entry_direction_score": 0.40,
                "entry_bias": 25.0,
                "legs": [
                    {
                        "security_id": 222,
                        "entry_price": 100.0,
                        "lots": 1,
                        "type": "PE",
                    }
                ],
            }, indent=2)

            old_open_pos = sell_engine.OPEN_POS_FILE
            old_base_dir = sell_engine.BASE_DIR
            try:
                sell_engine.OPEN_POS_FILE = open_pos_file
                sell_engine.BASE_DIR = Path(tmp)

                engine = sell_engine.PaperTradeEngine(clock=FrozenClock(now))

                weak_history = [
                    {
                        "ts": f"2026-03-28 10:{i:02d}:00",
                        "open": 22500.0,
                        "high": 22501.0,
                        "low": 22499.5,
                        "close": 22500.1,
                    }
                    for i in range(25)
                ]

                engine.tick(
                    signal="SELL_CE",
                    regime="SELL_CE",
                    history=weak_history,
                    ltp_map={222: 100.0},
                )

                self.assertEqual(engine.state, "IN_POSITION")
                self.assertIsNotNone(engine.position)
            finally:
                sell_engine.OPEN_POS_FILE = old_open_pos
                sell_engine.BASE_DIR = old_base_dir

    def test_same_side_reentry_is_blocked_without_improvement(self):
        engine = sell_engine.PaperTradeEngine(
            clock=FrozenClock(datetime(2026, 3, 28, 10, 5, tzinfo=IST))
        )
        engine.last_exit_regime = "SELL_PE"
        engine.last_exit_time = datetime(2026, 3, 28, 10, 0, tzinfo=IST)
        engine.last_exit_direction_score = 0.45

        allowed = engine.can_take_same_side_reentry(
            datetime(2026, 3, 28, 10, 5, tzinfo=IST),
            "SELL_PE",
            0.46,
        )

        self.assertFalse(allowed)

    def test_exit_writes_trade_event_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            open_pos_file = self.make_trade_file(tmp, "open_position.json")
            results_dir = self.make_results_dir(tmp)

            atomic_write_json(open_pos_file, {
                "status": "OPEN",
                "trade_id": "event_1",
                "regime": "SELL_CE",
                "strike": 22500,
                "expiry": "2026-03-30",
                "entry_time": "2026-03-28 10:00:00",
                "side": "SELL",
                "entry_signal": "SELL_CE",
                "entry_spot": 22500.0,
                "entry_direction_score": 0.50,
                "entry_bias": -30.0,
                "legs": [
                    {
                        "security_id": 111,
                        "entry_price": 100.0,
                        "lots": 1,
                        "type": "CE",
                    }
                ],
            }, indent=2)

            old_open_pos = sell_engine.OPEN_POS_FILE
            old_base_dir = sell_engine.BASE_DIR
            try:
                sell_engine.OPEN_POS_FILE = open_pos_file
                sell_engine.BASE_DIR = Path(tmp)

                engine = sell_engine.PaperTradeEngine(clock=self.make_clock("2026-03-28T10:05:00"))
                engine.exit_position(
                    datetime(2026, 3, 28, 10, 6, tzinfo=IST),
                    reason="TEST_EXIT",
                    ltp_map={111: 90.0},
                )

                trade_events = results_dir / "trade_events_sell.csv"
                self.assertTrue(trade_events.exists())
                rows = trade_events.read_text().strip().splitlines()
                self.assertEqual(len(rows), 2)
                self.assertIn("TEST_EXIT", rows[1])
                self.assertIn("SELL", rows[1])
            finally:
                sell_engine.OPEN_POS_FILE = old_open_pos
                sell_engine.BASE_DIR = old_base_dir

    def test_after_force_exit_time_engine_moves_to_done(self):
        engine = sell_engine.PaperTradeEngine(
            clock=FrozenClock(datetime(2026, 3, 28, 15, 26, tzinfo=IST))
        )

        engine.tick(
            signal=None,
            regime="WAIT",
            history=self.make_history(),
            ltp_map={},
        )

        self.assertEqual(engine.state, "DONE")

    def test_before_scan_time_engine_stays_flat(self):
        engine = sell_engine.PaperTradeEngine(
            clock=FrozenClock(datetime(2026, 3, 28, 9, 19, tzinfo=IST))
        )

        engine.tick(
            signal="SELL_PE",
            regime="SELL_PE",
            history=self.make_history(),
            ltp_map={111: 100.0, 222: 100.0},
        )

        self.assertEqual(engine.state, "FLAT")
        self.assertIsNone(engine.position)


if __name__ == "__main__":
    unittest.main()
