from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.vegvarsel.schedule import Schedule, parse_window

OSLO = ZoneInfo("Europe/Oslo")


def at(day: int, hh: int, mm: int = 0) -> datetime:
    """A time in November 2026 (Mon 2nd, Tue 3rd, ... Fri 6th, Sat 7th, Sun 8th, Mon 9th)."""
    return datetime(2026, 11, day, hh, mm, tzinfo=OSLO)


@pytest.fixture
def commute() -> Schedule:
    return Schedule.from_config(
        ["mon", "tue", "wed", "thu", "fri"], ["06:30-08:00", "15:30-17:00"], "21:00"
    )


def test_parse_window():
    assert parse_window("06:30-08:00") == (time(6, 30), time(8, 0))
    assert parse_window("22:00 – 02:00") == (time(22, 0), time(2, 0))
    with pytest.raises(ValueError):
        parse_window("06:30")
    with pytest.raises(ValueError):
        parse_window("07:00-07:00")


def test_in_window(commute):
    assert commute.in_window(at(3, 7, 0))
    assert not commute.in_window(at(3, 8, 0))  # end is exclusive
    assert not commute.in_window(at(7, 7, 0))  # Saturday


def test_next_window(commute):
    assert commute.next_window(at(3, 5, 0)) == (at(3, 6, 30), at(3, 8, 0))
    assert commute.next_window(at(3, 7, 0)) == (at(3, 6, 30), at(3, 8, 0))
    assert commute.next_window(at(3, 9, 0)) == (at(3, 15, 30), at(3, 17, 0))
    # Friday evening -> Monday morning
    assert commute.next_window(at(6, 18, 0)) == (at(9, 6, 30), at(9, 8, 0))


def test_window_across_midnight():
    night = Schedule.from_config(["fri"], ["22:00-02:00"], None)
    assert night.in_window(at(7, 1, 0))  # Saturday 01:00 belongs to Friday's window
    assert not night.in_window(at(8, 1, 0))
    assert night.current_window(at(7, 1, 0)) == (at(6, 22, 0), at(7, 2, 0))


def test_preview_windows_look_at_tomorrow(commute):
    assert commute.preview_windows(at(3, 21, 0)) == [
        (at(4, 6, 30), at(4, 8, 0)),
        (at(4, 15, 30), at(4, 17, 0)),
    ]
    assert commute.preview_windows(at(6, 21, 0)) == []  # Friday: not driven Saturday
    assert commute.preview_windows(at(8, 21, 0))  # Sunday: driven Monday


def test_preview_due_fires_once_between_checks(commute):
    assert commute.preview_due(None, at(3, 21, 1)) is None  # first check after a start
    assert commute.preview_due(at(3, 20, 59), at(3, 21, 1)) == at(3, 21, 0)
    assert commute.preview_due(at(3, 21, 1), at(3, 21, 3)) is None


def test_window_started(commute):
    assert commute.window_started(at(3, 6, 29), at(3, 6, 31)) == (at(3, 6, 30), at(3, 8, 0))
    assert commute.window_started(at(3, 6, 31), at(3, 6, 33)) is None
    assert commute.window_started(None, at(3, 6, 31)) is None


def test_no_windows_means_always():
    always = Schedule.from_config(None, None, None)
    assert always.always and always.in_window(at(7, 3, 0))
    assert always.window_started(at(3, 6, 0), at(3, 7, 0)) is None
