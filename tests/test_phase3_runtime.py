import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import nifty_evaluator
from scripts.clock import FrozenClock
from scripts.runtime_config import load_runtime_env, resolve_env_file


class RuntimeConfigTests(unittest.TestCase):
    def test_resolve_env_file_prefers_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "custom.env"
            env_file.write_text("DHAN_ACCESS_TOKEN=abc\n")

            old_env = os.environ.get("DHAN_ENV_FILE")
            try:
                os.environ["DHAN_ENV_FILE"] = str(env_file)
                self.assertEqual(resolve_env_file(), env_file)
            finally:
                if old_env is None:
                    os.environ.pop("DHAN_ENV_FILE", None)
                else:
                    os.environ["DHAN_ENV_FILE"] = old_env

    def test_load_runtime_env_loads_explicit_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "custom.env"
            env_file.write_text(
                "DHAN_ACCESS_TOKEN=test_token\nDHAN_CLIENT_ID=test_client\n"
            )

            old_env_file = os.environ.get("DHAN_ENV_FILE")
            old_token = os.environ.get("DHAN_ACCESS_TOKEN")
            old_client = os.environ.get("DHAN_CLIENT_ID")
            try:
                os.environ["DHAN_ENV_FILE"] = str(env_file)
                os.environ.pop("DHAN_ACCESS_TOKEN", None)
                os.environ.pop("DHAN_CLIENT_ID", None)

                loaded = load_runtime_env()

                self.assertEqual(loaded, env_file)
                self.assertEqual(os.environ["DHAN_ACCESS_TOKEN"], "test_token")
                self.assertEqual(os.environ["DHAN_CLIENT_ID"], "test_client")
            finally:
                if old_env_file is None:
                    os.environ.pop("DHAN_ENV_FILE", None)
                else:
                    os.environ["DHAN_ENV_FILE"] = old_env_file

                if old_token is None:
                    os.environ.pop("DHAN_ACCESS_TOKEN", None)
                else:
                    os.environ["DHAN_ACCESS_TOKEN"] = old_token

                if old_client is None:
                    os.environ.pop("DHAN_CLIENT_ID", None)
                else:
                    os.environ["DHAN_CLIENT_ID"] = old_client


class EvaluatorHelperTests(unittest.TestCase):
    def test_next_run_time_uses_configured_delay(self):
        now = datetime(2026, 3, 28, 10, 0, 2, tzinfo=nifty_evaluator.IST)

        run_at = nifty_evaluator.next_run_time(now)

        self.assertEqual(run_at, datetime(2026, 3, 28, 10, 0, 5, tzinfo=nifty_evaluator.IST))

    def test_sleep_until_uses_injected_clock(self):
        clock = FrozenClock(datetime(2026, 3, 28, 10, 0, 0, tzinfo=nifty_evaluator.IST))
        target = datetime(2026, 3, 28, 10, 0, 5, tzinfo=nifty_evaluator.IST)

        nifty_evaluator.sleep_until(target, clock=clock)

        self.assertEqual(clock.now(), target)

    def test_collect_open_position_security_ids_skips_invalid_legs(self):
        with tempfile.TemporaryDirectory() as tmp:
            position_file = Path(tmp) / "open_position.json"
            position_file.write_text(json.dumps({
                "status": "OPEN",
                "legs": [
                    {"security_id": 111},
                    {"security_id": "bad"},
                    {},
                    {"security_id": 222},
                ],
            }))

            ids = nifty_evaluator.collect_open_position_security_ids(
                position_file,
                "SELL",
            )

            self.assertEqual(ids, [111, 222])

    def test_collect_regime_security_ids_returns_empty_on_resolver_failure(self):
        original = nifty_evaluator.get_atm_straddle
        try:
            def boom(_spot):
                raise RuntimeError("resolver failed")

            nifty_evaluator.get_atm_straddle = boom

            ids = nifty_evaluator.collect_regime_security_ids(
                "SELL_PE",
                [{"close": 22500}],
            )

            self.assertEqual(ids, [])
        finally:
            nifty_evaluator.get_atm_straddle = original


if __name__ == "__main__":
    unittest.main()
