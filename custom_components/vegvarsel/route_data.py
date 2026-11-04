"""A route's stored data: the schedule fields checked the same way wherever a
route is saved (the setup dialogs and the card), and its line kept small."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .const import CONF_CORRIDOR, CONF_DAYS, CONF_PREVIEW, CONF_WINDOWS, DEFAULT_CORRIDOR
from .geo import simplify
from .schedule import WEEKDAYS, parse_hhmm, parse_window

# A stored route is simplified to this many metres - well inside any corridor.
STORE_TOLERANCE_M = 10.0


def clean_settings(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """The schedule fields, tidied, and an error key per field that is wrong."""
    errors: dict[str, str] = {}
    windows = [w.strip() for w in user_input.get(CONF_WINDOWS) or [] if w and w.strip()]
    try:
        for window in windows:
            parse_window(window)
    except ValueError:
        errors[CONF_WINDOWS] = "invalid_window"
    preview = user_input.get(CONF_PREVIEW) or None
    if preview:
        try:
            parse_hhmm(preview)
        except ValueError:
            errors[CONF_PREVIEW] = "invalid_time"
    days = [d for d in user_input.get(CONF_DAYS) or [] if d in WEEKDAYS]
    if not days:
        errors[CONF_DAYS] = "no_days"
    try:
        corridor = int(user_input.get(CONF_CORRIDOR, DEFAULT_CORRIDOR))
        if not 30 <= corridor <= 1000:
            raise ValueError
    except (TypeError, ValueError):
        errors[CONF_CORRIDOR] = "invalid_corridor"
        corridor = DEFAULT_CORRIDOR
    return (
        {CONF_CORRIDOR: corridor, CONF_DAYS: days, CONF_WINDOWS: windows, CONF_PREVIEW: preview},
        errors,
    )


def route_line(points: Iterable[Sequence[float]]) -> list[list[float]]:
    """A route's line as stored: simplified to STORE_TOLERANCE_M, 6 decimals."""
    return [[round(lat, 6), round(lon, 6)] for lat, lon in simplify([(float(p[0]), float(p[1])) for p in points], STORE_TOLERANCE_M)]
