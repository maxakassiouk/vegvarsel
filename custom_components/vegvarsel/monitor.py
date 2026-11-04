"""One route's watch: which incidents matter for the trip at hand, and which
events that warrants. Pure Python; the coordinator runs one per route on
every poll and turns the events into Home Assistant events.

"The trip at hand" is the watch window `now` is in, or else the next one to
start - so before you leave in the morning the route already reports what
lies over your drive, and in the evening what lies over tomorrow's. A route
without windows is watched around the clock and only cares about what applies
right now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo

from .datex import HORIZON, NORWAY, Incident
from .geo import RouteLine
from .schedule import Interval, Schedule

# Kinds a "next planned closure" looks for.
CLOSURE_KINDS = frozenset({"closed", "convoy"})


@dataclass
class RouteConfig:
    id: str
    name: str
    line: RouteLine
    corridor_m: float
    schedule: Schedule


@dataclass
class Match:
    """An incident on the route."""

    incident: Incident
    along_m: float
    applies_now: bool
    start: datetime | None  # when it next applies; if it applies now, when that began (None: unknown)
    end: datetime | None  # when the stretch it applies in ends; None = open-ended

    @property
    def key(self) -> str:
        """What is told apart: the situation. Statens vegvesen describes one
        situation in several records - the roadworks, the closure they cause,
        the speed limit - and one situation is one alert."""
        return self.incident.situation_id or self.incident.id


@dataclass
class RouteEvent:
    type: str  # new | updated | cleared | digest
    matches: list[Match]
    reason: str | None = None  # digest only: window_start | evening_preview
    window: Interval | None = None


@dataclass
class RouteState:
    matches: list[Match] = field(default_factory=list)  # on the route, over the trip at hand
    on_route: list[Match] = field(default_factory=list)  # on the route at any time within the horizon
    in_window: bool = False
    focus: Interval | None = None
    next_closure: Match | None = None

    @property
    def problem(self) -> bool:
        return bool(self.matches)

    @property
    def worst(self) -> Match | None:
        return max(self.matches, key=lambda m: m.incident.rank, default=None)


class RouteMonitor:
    def __init__(self, config: RouteConfig, tz: tzinfo = NORWAY) -> None:
        self.config = config
        self._tz = tz
        # incident id -> (version, along) for what has been placed on the line
        self._placed: dict[str, tuple[str, float | None]] = {}
        # incident id -> rank, for what was relevant on the previous check
        self._known: dict[str, int] | None = None
        self._previous: list[Match] = []
        self._last: datetime | None = None
        self.state = RouteState()

    # --- placing --------------------------------------------------------------

    def _along(self, incident: Incident) -> float | None:
        cached = self._placed.get(incident.id)
        if cached and cached[0] == incident.version:
            return cached[1]
        line, corridor = self.config.line, self.config.corridor_m
        along = None
        # Boxes first: most of a national feed is nowhere near the route, and
        # its stretches are then never turned into points at all.
        margin = corridor + 200
        near = [s for s in incident.lines if line.overlaps(s.bbox, margin)]
        if near:
            along = line.match(near, corridor)
        self._placed[incident.id] = (incident.version, along)
        return along

    def _matches(self, incidents: list[Incident], now: datetime) -> list[Match]:
        out = []
        horizon = now + HORIZON
        for incident in incidents:
            along = self._along(incident)
            if along is None:
                continue
            start = incident.validity.next_start(now, self._tz)
            if start is None or start >= horizon:
                continue
            applies_now = start <= now
            end = incident.validity.current_end(start, self._tz)
            if applies_now:
                # when the stretch going on now began, if known
                start = incident.validity.stretch_start(now, self._tz) or incident.validity.start
            out.append(Match(incident, along, applies_now, start, end))
        out.sort(key=lambda m: m.along_m)
        return out

    # --- the check ------------------------------------------------------------

    def focus(self, now: datetime) -> Interval:
        """The stretch of time the route cares about right now."""
        schedule = self.config.schedule
        if schedule.always:
            return (now, now + timedelta(seconds=1))
        window = schedule.next_window(now)
        if window is None:
            return (now, now + timedelta(seconds=1))
        return (max(window[0], now), window[1])

    def _over(self, matches: list[Match], interval: Interval) -> list[Match]:
        """One match per situation - its most serious record - of those that
        apply at some time within the interval."""
        best: dict[str, Match] = {}
        for m in matches:
            if not m.incident.validity.overlaps(interval[0], interval[1], self._tz):
                continue
            held = best.get(m.key)
            if held is None or m.incident.rank > held.incident.rank:
                best[m.key] = m
        return sorted(best.values(), key=lambda m: m.along_m)

    def update(self, incidents: list[Incident], now: datetime) -> list[RouteEvent]:
        schedule = self.config.schedule
        live = {i.id for i in incidents}
        for gone in set(self._placed) - live:
            del self._placed[gone]

        on_route = self._matches(incidents, now)
        focus = self.focus(now)
        relevant = self._over(on_route, focus)
        in_window = schedule.in_window(now)
        # The closure going on now, or else the next one to begin.
        closures = [m for m in on_route if m.incident.kind in CLOSURE_KINDS]
        self.state = RouteState(
            matches=relevant,
            on_route=on_route,
            in_window=in_window,
            focus=focus,
            next_closure=min(
                closures, key=lambda m: (not m.applies_now, -m.incident.rank, m.start or now), default=None
            ),
        )

        events: list[RouteEvent] = []
        current = {m.key: m.incident.rank for m in relevant}
        if self._known is not None and in_window:
            new = [m for m in relevant if m.key not in self._known]
            worse = [m for m in relevant if m.key in self._known and m.incident.rank > self._known[m.key]]
            cleared = [m for m in self._previous if m.key not in current]
            if new:
                events.append(RouteEvent("new", new))
            if worse:
                events.append(RouteEvent("updated", worse))
            if cleared:
                events.append(RouteEvent("cleared", cleared))

        started = schedule.window_started(self._last, now)
        if started:
            events.append(RouteEvent("digest", self._over(on_route, started), "window_start", started))
        if schedule.preview_due(self._last, now):
            windows = schedule.preview_windows(now)
            if windows:  # not driven tomorrow: no preview
                seen: dict[str, Match] = {}
                for window in windows:
                    for m in self._over(on_route, window):
                        if m.key not in seen or m.incident.rank > seen[m.key].incident.rank:
                            seen[m.key] = m
                span = (windows[0][0], windows[-1][1])
                events.append(
                    RouteEvent("digest", sorted(seen.values(), key=lambda m: m.along_m), "evening_preview", span)
                )

        self._known = current
        self._previous = relevant
        self._last = now
        return events
