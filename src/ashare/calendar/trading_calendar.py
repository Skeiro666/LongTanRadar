"""A-share trading calendar — pluggable; default = weekdays + optional holiday file.

Does not hardcode China holidays. Provide data/calendar/holidays.yaml or
holidays.json to exclude non-trading weekdays.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo


class TradingCalendar(Protocol):
    def is_trading_day(self, d: date) -> bool: ...

    def is_market_open(self, when: datetime) -> bool: ...

    def next_trading_day(self, d: date) -> date: ...

    def previous_trading_day(self, d: date) -> date: ...


_SESSION_AM = (time(9, 30), time(11, 30))
_SESSION_PM = (time(13, 0), time(15, 0))


class WeekdayTradingCalendar:
    """Mon–Fri minus optional closed dates; forced_open for make-up days."""

    def __init__(
        self,
        *,
        timezone: str = "Asia/Shanghai",
        closed_dates: set[date] | None = None,
        forced_open_dates: set[date] | None = None,
    ) -> None:
        self.tz = ZoneInfo(timezone)
        self.closed = set(closed_dates or set())
        self.forced_open = set(forced_open_dates or set())

    def is_trading_day(self, d: date) -> bool:
        if d in self.forced_open:
            return True
        if d.weekday() >= 5:
            return False
        if d in self.closed:
            return False
        return True

    def is_market_open(self, when: datetime) -> bool:
        local = when.astimezone(self.tz) if when.tzinfo else when.replace(tzinfo=self.tz)
        if not self.is_trading_day(local.date()):
            return False
        t = local.time()
        return (_SESSION_AM[0] <= t <= _SESSION_AM[1]) or (_SESSION_PM[0] <= t <= _SESSION_PM[1])

    def next_trading_day(self, d: date) -> date:
        cur = d + timedelta(days=1)
        for _ in range(400):
            if self.is_trading_day(cur):
                return cur
            cur += timedelta(days=1)
        raise RuntimeError("next_trading_day not found within 400 days")

    def previous_trading_day(self, d: date) -> date:
        cur = d - timedelta(days=1)
        for _ in range(400):
            if self.is_trading_day(cur):
                return cur
            cur -= timedelta(days=1)
        raise RuntimeError("previous_trading_day not found within 400 days")

    def trading_days_between(self, start: date, end: date) -> list[date]:
        out: list[date] = []
        cur = start
        while cur <= end:
            if self.is_trading_day(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out


def _parse_d(x: Any) -> date | None:
    try:
        return date.fromisoformat(str(x)[:10])
    except Exception:  # noqa: BLE001
        return None


def _load_closed_dates(root: Path) -> set[date]:
    import json

    jpath = root / "data" / "calendar" / "holidays.json"
    ypath = root / "data" / "calendar" / "holidays.yaml"
    days: list[Any] = []
    if jpath.exists():
        try:
            raw = json.loads(jpath.read_text(encoding="utf-8"))
            days = raw if isinstance(raw, list) else list(raw.get("closed") or [])
        except Exception:  # noqa: BLE001
            days = []
    elif ypath.exists():
        try:
            import yaml

            raw = yaml.safe_load(ypath.read_text(encoding="utf-8")) or {}
            days = raw if isinstance(raw, list) else list(raw.get("closed") or raw.get("holidays") or [])
        except Exception:  # noqa: BLE001
            days = []
    return {_parse_d(x) for x in days if _parse_d(x)}


def load_trading_calendar(cfg: dict[str, Any] | None = None) -> WeekdayTradingCalendar:
    cfg = cfg or {}
    root = Path(cfg.get("_root") or Path.cwd())
    sch = dict(cfg.get("scheduler") or {})
    tz = str(sch.get("timezone") or "Asia/Shanghai")
    return WeekdayTradingCalendar(timezone=tz, closed_dates=_load_closed_dates(root))
