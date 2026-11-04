from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.vegvarsel.datex import classify, parse_situations

OSLO = ZoneInfo("Europe/Oslo")


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=OSLO)


@pytest.fixture
def by_id(situations_xml):
    return {i.id: i for i in parse_situations(situations_xml)}


def test_all_records_read(by_id):
    assert set(by_id) == {
        "NPRA_SYN_ELL_NIGHT_1",
        "NPRA_SYN_ELL_ACC_1",
        "NPRA_SYN_PARALLEL_1",
        "NPRA_SYN_OSLO_1",
        "NPRA_SYN_VAL_CONVOY_1",
        "NPRA_SYN_SUSPENDED_1",
    }


def test_closure_record(by_id):
    night = by_id["NPRA_SYN_ELL_NIGHT_1"]
    assert night.kind == "closed"
    assert night.record_type == "RoadOrCarriagewayOrLaneManagement"
    assert night.situation_id == "NPRA_SYN_ELL_NIGHT"
    assert night.version == "3"
    assert night.road == "Fv658"
    assert night.places == ["Hessa", "Ellingsøya"]
    assert night.points == [(62.4738, 6.1765), (62.4915, 6.1797)]
    assert night.description.startswith("Ellingsøytunnelen er stengt om natta")


def test_kinds(by_id):
    assert by_id["NPRA_SYN_ELL_ACC_1"].kind == "accident"
    assert by_id["NPRA_SYN_PARALLEL_1"].kind == "roadworks"
    assert by_id["NPRA_SYN_VAL_CONVOY_1"].kind == "convoy"


def test_gml_line(by_id):
    convoy = by_id["NPRA_SYN_VAL_CONVOY_1"]
    assert convoy.points == [(62.5115, 6.1006), (62.516, 6.1002), (62.521, 6.0999)]


def test_recurring_night_closure(by_id):
    v = by_id["NPRA_SYN_ELL_NIGHT_1"].validity
    assert v.active_at(at(3, 23, 0))  # Tuesday night
    assert v.active_at(at(4, 5, 30))  # ... until 06:00 Wednesday
    assert not v.active_at(at(4, 7, 0))  # morning commute is clear
    assert not v.overlaps(at(4, 6, 30), at(4, 8, 0))
    assert not v.active_at(at(6, 23, 0))  # Friday night: not an applicable day
    assert v.next_start(at(4, 12, 0)) == at(4, 22, 0)
    assert v.current_end(at(3, 23, 0)) == at(4, 6, 0)
    assert v.next_start(at(20, 7, 0)) is None  # all over


def test_open_ended_active(by_id):
    v = by_id["NPRA_SYN_ELL_ACC_1"].validity
    assert not v.active_at(at(4, 7, 0))
    assert v.active_at(at(4, 7, 10))
    assert v.current_end(at(4, 7, 10)) is None


def test_suspended_never_applies(by_id):
    assert not by_id["NPRA_SYN_SUSPENDED_1"].validity.active_at(at(3, 12, 0))


def test_classify_fallbacks():
    assert classify("RoadOrCarriagewayOrLaneManagement", ["laneClosures"]) == "restriction"
    assert classify("RoadOrCarriagewayOrLaneManagement", ["carriagewayClosures"]) == "closed"
    assert classify("SomethingNew", []) == "info"


def test_odd_record_does_not_break_the_rest():
    xml = b"""<p xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <situation id="A"><situationRecord xsi:type="Accident" id="A1">
        <validity><validityStatus>active</validityStatus>
          <validityTimeSpecification><overallStartTime>not a time</overallStartTime></validityTimeSpecification>
        </validity></situationRecord></situation>
    </p>"""
    (only,) = parse_situations(xml)
    assert only.kind == "accident" and only.validity.start is None


def test_pipe_in_comment_is_a_line_break():
    """Statens vegvesen separates lines in a comment with "|"."""
    xml = """<p xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><situation id="S">
      <situationRecord xsi:type="MaintenanceWorks" id="S1"><generalPublicComment><comment><values>
        <value lang="no">Vegarbeid, gyldig mellom 02.11.2026 23:00 og 05.11.2026 05:30.|Manuell dirigering.</value>
      </values></comment></generalPublicComment></situationRecord></situation></p>"""
    (only,) = parse_situations(xml)
    assert only.description == "Vegarbeid, gyldig mellom 02.11.2026 23:00 og 05.11.2026 05:30. Manuell dirigering."
