import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from scripts.app_config import IST


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(IST)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def today(self) -> date:
        return self.now().date()


class FrozenClock:
    def __init__(self, current: datetime):
        if current.tzinfo is None:
            current = current.replace(tzinfo=IST)
        self.current = current.astimezone(IST)

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)

    def today(self) -> date:
        return self.current.date()

    def set(self, current: datetime) -> None:
        if current.tzinfo is None:
            current = current.replace(tzinfo=IST)
        self.current = current.astimezone(IST)


_CLOCK = SystemClock()


def get_clock():
    return _CLOCK


def set_clock(clock) -> None:
    global _CLOCK
    _CLOCK = clock


@contextmanager
def use_clock(clock):
    previous = get_clock()
    set_clock(clock)
    try:
        yield clock
    finally:
        set_clock(previous)
