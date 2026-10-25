"""Demo clock: real UTC time plus an adjustable offset so judges can "time-travel"
to see reminders, overdue states and escalations fire without waiting days."""
from datetime import datetime, timedelta, date

_offset = timedelta(0)


def now() -> datetime:
    return datetime.utcnow().replace(microsecond=0) + _offset


def today() -> date:
    return now().date()


def advance(days: int) -> None:
    global _offset
    _offset += timedelta(days=int(days))


def reset() -> None:
    global _offset
    _offset = timedelta(0)


def offset_days() -> int:
    return _offset.days
