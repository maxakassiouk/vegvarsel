"""The demo feed in tools/demo_feed.py: does Vegvarsel read what it serves?"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import importlib.util
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.vegvarsel.datex import parse_situations
from custom_components.vegvarsel.geo import RouteLine
from custom_components.vegvarsel.monitor import RouteConfig, RouteMonitor
from custom_components.vegvarsel.schedule import Schedule

from .conftest import load_fixture

OSLO = ZoneInfo("Europe/Oslo")
_spec = importlib.util.spec_from_file_location("demo_feed", Path(__file__).parents[1] / "tools" / "demo_feed.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)


def test_shift_by_whole_weeks_keeps_weekdays():
    text = load_fixture("npra_sample_excerpt.xml").decode("utf-8")
    days = demo.week_shift(text, date(2026, 11, 3))
    assert days % 7 == 0 and days > 0
    shifted = demo.shift_times(text, days)
    before = {i.id: i for i in parse_situations(text)}
    after = {i.id: i for i in parse_situations(shifted)}
    for rid, incident in before.items():
        if incident.validity.start:
            moved = after[rid].validity.start
            assert moved - incident.validity.start == timedelta(days=days)
            assert moved.weekday() == incident.validity.start.weekday()


def test_shift_leaves_fractions_and_offsets():
    assert demo.shift_times("<a>2025-08-08T15:58:34.1475489+02:00</a>", 7) == "<a>2025-08-15T15:58:34.1475489+02:00</a>"


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 11, 4, 7, 10, tzinfo=OSLO)  # a Wednesday morning


@pytest.fixture
def feed(now):
    base = demo.shift_times(load_fixture("npra_sample_excerpt.xml").decode("utf-8"), 0)
    active = {name: now - timedelta(minutes=1) for name in demo.SCENARIOS}
    return parse_situations(demo.build_feed(base, active, now))


def test_scenarios_are_read(feed):
    ours = {i.id: i for i in feed if i.id.startswith("DEMO_")}
    assert ours["DEMO_ACCIDENT_1"].kind == "accident"
    assert ours["DEMO_ACCIDENT_2"].kind == "closed"
    assert ours["DEMO_CONVOY_1"].kind == "convoy"
    assert ours["DEMO_NIGHT_CLOSURES_2"].kind == "closed"
    assert ours["DEMO_ACCIDENT_1"].road == "Fv658"
    assert len(feed) == 16 + len(ours)  # the sample's own records are all still there


def test_scenarios_on_the_aalesund_route(feed, now, route_points):
    schedule = Schedule.from_config(["mon", "tue", "wed", "thu", "fri"], ["06:30-08:00"], "21:00")
    monitor = RouteMonitor(RouteConfig("r", "Til jobb", RouteLine(route_points), 150.0, schedule), OSLO)
    monitor.update(feed, now)
    relevant = {m.key for m in monitor.state.matches}
    assert relevant == {"DEMO_ACCIDENT", "DEMO_CONVOY"}  # not the night closure, not the parallel road
    assert monitor.state.worst.incident.kind == "closed"
    assert monitor.state.next_closure.key == "DEMO_ACCIDENT"  # going on now
    night = next(i for i in feed if i.id == "DEMO_NIGHT_CLOSURES_2")
    assert night.validity.active_at(datetime(2026, 11, 4, 23, 30, tzinfo=OSLO))
    assert night.validity.current_end(datetime(2026, 11, 4, 23, 30, tzinfo=OSLO)) == datetime(
        2026, 11, 5, 6, 0, tzinfo=OSLO
    )


def test_nothing_switched_on_is_the_sample_alone():
    base = load_fixture("npra_sample_excerpt.xml").decode("utf-8")
    assert demo.build_feed(base, {}, datetime.now(OSLO)) == base.encode("utf-8")
