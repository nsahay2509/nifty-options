import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.state_utils import atomic_write_json, safe_load_json
import scripts.paper_trade_engine as sell_engine
import scripts.paper_trade_engine_buy as buy_engine


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

                engine = sell_engine.PaperTradeEngine()

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

                engine = sell_engine.PaperTradeEngine()
                engine.state = "DONE"
                engine.session_date = date(2026, 3, 27)
                engine.position = sell_engine.Position(
                    trade_id="old_trade",
                    regime="SELL_CE",
                    strike=22400,
                    expiry="2026-03-30",
                    ce_security_id=111,
                    pe_security_id=None,
                    entry_time=datetime(2026, 3, 27, 15, 0, tzinfo=sell_engine.IST),
                )

                engine.reset_for_new_day(
                    datetime(2026, 3, 28, 9, 21, tzinfo=sell_engine.IST)
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

                engine = buy_engine.PaperTradeEngine()

                self.assertEqual(engine.state, "IN_POSITION")
                self.assertIsNotNone(engine.position)
                self.assertEqual(engine.position.trade_id, "buy_1")
                self.assertEqual(engine.position.pe_security_id, 54321)
                self.assertEqual(engine.active_regime, "SELL_CE")
            finally:
                buy_engine.OPEN_POS_FILE = old_open_pos
                buy_engine.BASE_DIR = old_base_dir


if __name__ == "__main__":
    unittest.main()
