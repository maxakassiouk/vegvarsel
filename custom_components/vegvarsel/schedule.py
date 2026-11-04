"""When a route is watched: its days, its watch windows and the time of the
evening preview. Pure Python on timezone-aware datetimes, so it is tested on
its own; the coordinator hands it Home Assistant's local "now".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

Interval = tuple[datetime, datetime]


def parse_hhmm(text: str) -> time:
    """"06:30" or "06:30:00" as a time."""
    parts = text.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"not a time: {text!r}")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    return time(hour, minute, second)


def parse_window(text: str) -> tuple[time, time]:
    """"06:30-08:00" as (start, end). An end before the start spans midnight."""
    try:
        start, end = text.replace("–", "-").split("-")
        parsed = parse_hhmm(start), parse_hhmm(end)
    except ValueError as err:
        raise ValueError(f"not a window (HH:MM-HH:MM): {text!r}") from err
    if parsed[0] == parsed[1]:
        raise ValueError(f"a window cannot start and end at the same time: {text!r}")
    return parsed


@dataclass(frozen=True)
class Schedule:
    """Days the route is driven, windows on those days, and an optional
    evening preview (on the evening before a driving day)."""

    days: frozenset[str] = frozenset(WEEKDAYS[:5])
    windows: tuple[tuple[time, time], ...] = field(default_factory=tuple)
    preview: time | None = None

    @classmethod
    def from_config(cls, days: list[str] | None, windows: list[str] | None, preview: str | None) -> Schedule:
        return cls(
            days=frozenset(days) if days else frozenset(WEEKDAYS),
            windows=tuple(parse_window(w) for w in (windows or []) if w.strip()),
            preview=parse_hhmm(preview) if preview else None,
        )

    @property
    def always(self) -> bool:
        """No windows set: the route is watched around the clock."""
        return not self.windows

    def drives_on(self, day: date) -> bool:
        return WEEKDAYS[day.weekday()] in self.days

    def windows_on(self, day: date, tz) -> list[Interval]:
        """The concrete windows that start on a given day (empty on a day
        the route is not driven)."""
        if not self.drives_on(day):
            return []
        out = []
        for start, end in self.windows:
            begin = datetime.combine(day, start, tz)
            finish = datetime.combine(day if end > start else day + timedelta(days=1), end, tz)
            out.append((begin, finish))
        return sorted(out)

    def current_window(self, now: datetime) -> Interval | None:
        """The window `now` lies in, if any. Looks at yesterday too, for a
        window that spans midnight."""
        if self.always:
            return None
        for day in (now.date() - timedelta(days=1), now.date()):
            for begin, finish in self.windows_on(day, now.tzinfo):
                if begin <= now < finish:
                    return (begin, finish)
        return None

    def in_window(self, now: datetime) -> bool:
        return self.always or self.current_window(now) is not None

    def next_window(self, now: datetime, horizon_days: int = 8) -> Interval | None:
        """The window `now` is in, or else the next one to start."""
        current = self.current_window(now)
        if current:
            return current
        for offset in range(horizon_days):
            for begin, finish in self.windows_on(now.date() + timedelta(days=offset), now.tzinfo):
                if begin > now:
                    return (begin, finish)
        return None

    def preview_windows(self, now: datetime) -> list[Interval]:
        """What an evening preview at `now` looks ahead to: tomorrow's
        windows - or all of tomorrow when the route has no windows. Empty
        when the route is not driven tomorrow."""
        tomorrow = now.date() + timedelta(days=1)
        if not self.drives_on(tomorrow):
            return []
        if self.always:
            begin = datetime.combine(tomorrow, time(0, 0), now.tzinfo)
            return [(begin, begin + timedelta(days=1))]
        return self.windows_on(tomorrow, now.tzinfo)

    def preview_due(self, last: datetime | None, now: datetime) -> datetime | None:
        """The preview moment passed between the previous check and this
        one (inclusive of `now`), if any - so it fires once, even when polls
        do not land on the exact minute. `last` None (first check after a
        start) never fires: a restart must not repeat a preview already sent."""
        if self.preview is None or last is None:
            return None
        moment = datetime.combine(now.date(), self.preview, now.tzinfo)
        if last < moment <= now:
            return moment
        return None

    def window_started(self, last: datetime | None, now: datetime) -> Interval | None:
        """A window that began between the previous check and now. Same
        restart rule as preview_due."""
        if self.always or last is None:
            return None
        for day in (now.date() - timedelta(days=1), now.date()):
            for begin, finish in self.windows_on(day, now.tzinfo):
                if last < begin <= now:
                    return (begin, finish)
        return None
