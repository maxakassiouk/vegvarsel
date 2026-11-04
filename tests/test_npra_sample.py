"""Against an excerpt of Statens vegvesen's own published DATEX II 3.1 sample:
real records, real coordinates (UTM 33), real recurring validity."""

from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from custom_components.vegvarsel.datex import parse_situations
from custom_components.vegvarsel.geo import RouteLine
from custom_components.vegvarsel.monitor import RouteConfig, RouteMonitor
from custom_components.vegvarsel.schedule import Schedule

from .conftest import FIXTURES, load_fixture

OSLO = ZoneInfo("Europe/Oslo")
SELVAG_CLOSED = "926f3a97-bd5b-4ecf-8dc3-b1ab304f01cb_2"
SELVAG_CONVOY = "926f3a97-bd5b-4ecf-8dc3-b1ab304f01cb_1"
SELVAG = "NPRA_HBT_07-07-2025.113060"  # the situation both records belong to


def at(y: int, mo: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, mo, d, hh, mm, tzinfo=OSLO)


@pytest.fixture(scope="module")
def incidents():
    return parse_situations(load_fixture("npra_sample_excerpt.xml"))


@pytest.fixture(scope="module")
def by_id(incidents):
    return {i.id: i for i in incidents}


@pytest.fixture
def ulstein_eiksund() -> RouteLine:
    data = json.loads((FIXTURES / "route_ulstein_eiksund.json").read_text(encoding="utf-8"))
    return RouteLine([tuple(p) for p in data["points"]])


def test_every_record_is_placed_in_norway(incidents):
    assert len(incidents) == 16
    for incident in incidents:
        assert incident.lines, incident.id
        for lat, lon in incident.points:
            assert 57 < lat < 72 and 4 < lon < 32, incident.id


def test_utm_lines_land_on_their_display_point(incidents):
    """The GML line is in UTM 33 metres; converted, it runs through the
    record's own display point."""
    for incident in incidents:
        if incident.display and len(incident.points) > 1:
            nearest = min(
                ((lat - incident.display[0]) * 111_320) ** 2 + ((lon - incident.display[1]) * 52_000) ** 2
                for lat, lon in incident.points
            ) ** 0.5
            assert nearest < 1_500, incident.id


def test_several_stretches_kept_apart(by_id):
    granfoss = by_id["3ae0ad4e-0400-4c96-a664-161cc5848762_2"]
    assert len(granfoss.lines) == 10
    assert granfoss.kind == "closed"


def test_kinds(by_id):
    assert by_id[SELVAG_CLOSED].kind == "closed"
    assert by_id[SELVAG_CONVOY].kind == "convoy"  # only the text says "Kolonne"
    assert by_id["97cc6c45-c48f-4c8a-a3fd-eae2a62bb3ee_2"].kind == "restriction"  # intermittent short closures
    assert by_id["6de80f58-12a6-4d12-ba62-8a7420e242ba_1"].kind == "accident"
    assert by_id["00a9d93a-252a-46ca-a0a4-6d4e822c4225_1"].kind == "obstruction"


def test_text_road_and_place(by_id):
    bridge = by_id["2dadcb28-8c9a-4195-bc2d-56f34f1b7b13_2"]
    assert bridge.road == "Fv217"
    assert bridge.places[0] == "Fv. 217 Åkrestrømmen bru i Rendalen, Innlandet"
    # the generated summary first, then the free text
    assert bridge.description.startswith("Vegarbeid, vegen er stengt, gyldig mellom 22:00 og 06:00")
    assert bridge.description.endswith("Utrykningskjøretøy kan passere.")


def test_night_closure_split_at_midnight_is_one_stretch(by_id):
    v = by_id["2dadcb28-8c9a-4195-bc2d-56f34f1b7b13_2"].validity  # Mon-Thu nights 22-06
    assert v.active_at(at(2025, 8, 12, 23, 0))  # Tuesday night
    assert v.active_at(at(2025, 8, 15, 3, 0))  # Thursday night, into Friday
    assert not v.active_at(at(2025, 8, 16, 3, 0))  # Friday night, into Saturday
    assert not v.active_at(at(2025, 8, 12, 12, 0))  # daytime
    assert v.current_end(at(2025, 8, 12, 23, 0)) == at(2025, 8, 13, 6, 0)  # not 23:59:59
    assert v.stretch_start(at(2025, 8, 13, 1, 0)) == at(2025, 8, 12, 22, 0)  # not 00:00


def test_recurring_time_is_local_after_the_clock_change(by_id):
    v = by_id[SELVAG_CLOSED].validity  # "20:00:00+02:00" every day, until 30 Oct
    assert v.next_start(at(2025, 10, 28, 12, 0)) == at(2025, 10, 28, 20, 0)  # CET: still 20:00


def test_selvag_on_a_route_through_the_tunnel(incidents, ulstein_eiksund):
    matched = {i.id for i in incidents if ulstein_eiksund.match(i.lines, 150) is not None}
    assert matched == {SELVAG_CLOSED, SELVAG_CONVOY}


def _monitor(line: RouteLine, windows: list[str]) -> RouteMonitor:
    schedule = Schedule.from_config(["mon", "tue", "wed", "thu", "fri"], windows, "19:00")
    return RouteMonitor(RouteConfig("r", "Eiksund", line, 150.0, schedule), OSLO)


def test_morning_commute_is_clear_evening_trip_is_not(incidents, ulstein_eiksund):
    morning = _monitor(ulstein_eiksund, ["06:30-08:00"])
    morning.update(incidents, at(2025, 9, 1, 6, 0))  # Monday
    assert not morning.state.problem  # closed 20-06 only
    assert morning.state.next_closure.key == SELVAG
    assert morning.state.next_closure.start == at(2025, 9, 1, 20, 0)

    evening = _monitor(ulstein_eiksund, ["20:30-21:30"])
    evening.update(incidents, at(2025, 9, 1, 18, 58))
    (only,) = evening.state.matches  # one situation, though two records
    assert only.incident.id == SELVAG_CLOSED  # its most serious record
    events = evening.update(incidents, at(2025, 9, 1, 19, 0))
    (preview,) = [e for e in events if e.type == "digest"]
    assert preview.reason == "evening_preview" and [m.key for m in preview.matches] == [SELVAG]
