"""Building blocks for the Home Assistant tests."""

from __future__ import annotations

import json
import re

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvarsel.const import (
    CONF_CORRIDOR,
    CONF_DAYS,
    CONF_DESTINATION,
    CONF_POINTS,
    CONF_PREVIEW,
    CONF_START,
    CONF_VIAS,
    CONF_WINDOWS,
    DATEX_SITUATION_URL,
    DOMAIN,
    SUBENTRY_ROUTE,
)

from .conftest import FIXTURES, load_fixture

OSRM_RE = re.compile(r"^https://router\.project-osrm\.org/route/v1/driving/")
ROUTE_ID = "route_work"


def route_points() -> list[list[float]]:
    return json.loads((FIXTURES / "route_aalesund_vigra.json").read_text(encoding="utf-8"))["points"]


def osrm_body() -> dict:
    data = json.loads((FIXTURES / "route_aalesund_vigra.json").read_text(encoding="utf-8"))
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": data["distance_m"],
                "duration": data["duration_s"],
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in data["points"]]},
            }
        ],
    }


def feed_without(*record_ids: str) -> str:
    """The synthetic feed with some situations taken out (by record id)."""
    text = load_fixture("situations_synthetic.xml").decode("utf-8")
    for record_id in record_ids:
        situation = record_id.rsplit("_", 1)[0]
        text = re.sub(
            rf'<sit:situation id="{situation}">.*?</sit:situation>', "", text, flags=re.DOTALL
        )
    return text


def mock_entry(windows: list[str] | None = None, preview: str | None = "21:00:00") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Statens vegvesen (user)",
        unique_id="user",
        data={CONF_USERNAME: "user", CONF_PASSWORD: "secret"},
        subentries_data=[
            ConfigSubentryData(
                subentry_id=ROUTE_ID,
                subentry_type=SUBENTRY_ROUTE,
                title="Work",
                unique_id=None,
                data={
                    CONF_START: {"latitude": 62.4722, "longitude": 6.1549, "label": "Ålesund"},
                    CONF_DESTINATION: {"latitude": 62.559, "longitude": 6.115, "label": "Vigra"},
                    CONF_VIAS: [],
                    CONF_POINTS: route_points(),
                    CONF_CORRIDOR: 150,
                    CONF_DAYS: ["mon", "tue", "wed", "thu", "fri"],
                    CONF_WINDOWS: ["06:30-08:00"] if windows is None else windows,
                    CONF_PREVIEW: preview,
                },
            )
        ],
    )


__all__ = ["DATEX_SITUATION_URL", "OSRM_RE", "ROUTE_ID", "feed_without", "mock_entry", "osrm_body"]
