from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.vegvarsel.datex import parse_situations
from custom_components.vegvarsel.geo import RouteLine
from custom_components.vegvarsel.monitor import RouteConfig, RouteMonitor
from custom_components.vegvarsel.schedule import Schedule

OSLO = ZoneInfo("Europe/Oslo")


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=OSLO)


@pytest.fixture
def incidents(situations_xml):
    return parse_situations(situations_xml)


@pytest.fixture
def monitor(route_points):
    schedule = Schedule.from_config(["mon", "tue", "wed", "thu", "fri"], ["06:30-08:00"], "21:00")
    return RouteMonitor(RouteConfig("r1", "Work", RouteLine(route_points), 150.0, schedule), OSLO)


def ids(matches):
    return [m.incident.id for m in matches]


def without(incidents, *drop):
    return [i for i in incidents if i.id not in drop]


def test_only_route_incidents_are_on_route(monitor, incidents):
    monitor.update(incidents, at(3, 20, 0))
    on_route = ids(monitor.state.on_route)
    assert "NPRA_SYN_PARALLEL_1" not in on_route
    assert "NPRA_SYN_OSLO_1" not in on_route
    assert "NPRA_SYN_SUSPENDED_1" not in on_route
    # in driving order: the tunnel (km ~2-3) before Valderøy (km ~10)
    assert on_route == ["NPRA_SYN_ELL_NIGHT_1", "NPRA_SYN_ELL_ACC_1", "NPRA_SYN_VAL_CONVOY_1"]


def test_night_closure_is_not_a_problem_for_the_morning(monitor, incidents):
    quiet = without(incidents, "NPRA_SYN_ELL_ACC_1", "NPRA_SYN_VAL_CONVOY_1")
    monitor.update(quiet, at(3, 23, 0))  # tunnel closed right now ...
    assert not monitor.state.problem  # ... but open again for tomorrow's 06:30-08:00
    assert monitor.state.next_closure.incident.id == "NPRA_SYN_ELL_NIGHT_1"


def test_first_check_is_a_baseline_then_new_fires_in_window(monitor, incidents):
    before = without(incidents, "NPRA_SYN_ELL_ACC_1")
    assert monitor.update(before, at(4, 7, 0)) == []  # first check after start: silent
    events = monitor.update(incidents, at(4, 7, 10))
    assert [(e.type, ids(e.matches)) for e in events] == [("new", ["NPRA_SYN_ELL_ACC_1"])]
    assert monitor.state.problem
    assert monitor.update(incidents, at(4, 7, 12)) == []  # not twice


def test_cleared_fires_when_it_goes(monitor, incidents):
    monitor.update(without(incidents, "NPRA_SYN_ELL_ACC_1"), at(4, 7, 0))
    monitor.update(incidents, at(4, 7, 10))
    events = monitor.update(without(incidents, "NPRA_SYN_ELL_ACC_1"), at(4, 7, 40))
    assert [(e.type, ids(e.matches)) for e in events] == [("cleared", ["NPRA_SYN_ELL_ACC_1"])]


def test_outside_window_no_live_events(monitor, incidents):
    monitor.update(without(incidents, "NPRA_SYN_ELL_ACC_1"), at(4, 9, 0))
    assert monitor.update(incidents, at(4, 9, 10)) == []
    assert monitor.state.problem  # still reported for tomorrow's window: accident is open-ended


def test_window_start_digest(monitor, incidents):
    # Thursday: convoy 06:00-09:00 in Valderøytunnelen overlaps the 06:30 window
    monitor.update(incidents, at(5, 6, 28))
    events = monitor.update(incidents, at(5, 6, 30))
    digests = [e for e in events if e.type == "digest"]
    assert len(digests) == 1 and digests[0].reason == "window_start"
    assert "NPRA_SYN_VAL_CONVOY_1" in ids(digests[0].matches)
    assert "NPRA_SYN_ELL_NIGHT_1" not in ids(digests[0].matches)


def test_evening_preview_covers_tomorrow(monitor, incidents):
    monitor.update(incidents, at(4, 20, 58))
    events = monitor.update(incidents, at(4, 21, 0))
    (preview,) = [e for e in events if e.type == "digest"]
    assert preview.reason == "evening_preview"
    assert preview.window == (at(5, 6, 30), at(5, 8, 0))
    assert "NPRA_SYN_VAL_CONVOY_1" in ids(preview.matches)
    assert "NPRA_SYN_ELL_NIGHT_1" not in ids(preview.matches)


def test_no_preview_before_a_day_off(monitor, incidents):
    monitor.update(incidents, at(6, 20, 58))
    assert [e for e in monitor.update(incidents, at(6, 21, 0)) if e.type == "digest"] == []


def test_worse_fires_updated(monitor, incidents):
    roadworks = [i for i in incidents if i.id == "NPRA_SYN_ELL_ACC_1"]
    roadworks[0].kind = "roadworks"
    monitor.update(roadworks, at(4, 7, 10))
    monitor.update(roadworks, at(4, 7, 12))
    roadworks[0].kind = "closed"
    events = monitor.update(roadworks, at(4, 7, 14))
    assert [e.type for e in events] == ["updated"]


def test_always_watched_route(route_points, incidents):
    m = RouteMonitor(RouteConfig("r2", "Any", RouteLine(route_points), 150.0, Schedule.from_config(None, None, None)), OSLO)
    m.update(without(incidents, "NPRA_SYN_ELL_ACC_1"), at(7, 12, 0))
    events = m.update(incidents, at(7, 12, 0) + timedelta(minutes=2))
    assert [e.type for e in events] == ["new"]
