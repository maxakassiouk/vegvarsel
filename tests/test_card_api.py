"""The websocket commands the dashboard card uses.

Address-search fixtures use fictional street names and arbitrary coordinates.
The route fixtures are public demonstration routes, not household locations.
"""

from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.setup import async_setup_component
import pytest

from custom_components.vegvarsel import places

from .helpers import DATEX_SITUATION_URL, OSRM_RE, ROUTE_ID, feed_without, mock_entry, osrm_body, route_points

OSLO = ZoneInfo("Europe/Oslo")
ADDRESS_RE = re.compile(r"^https://ws\.geonorge\.no/adresser/v1/sok")
NAMES_RE = re.compile(r"^https://ws\.geonorge\.no/stedsnavn/v1/navn")

ADDRESSES = {
    "adresser": [
        {
            "adressetekst": "Eksempeløyvegen 5B",
            "postnummer": "6057",
            "poststed": "ELLINGSØY",
            "kommunenavn": "ÅLESUND",
            "representasjonspunkt": {"epsg": "EPSG:4258", "lat": 62.4, "lon": 6.1},
        }
    ]
}
NAMES = {
    "navn": [
        {
            "skrivemåte": "Eksempeløy",
            "navneobjekttype": "Øy i sjø",
            "kommuner": [{"kommunenavn": "Ålesund"}],
            "representasjonspunkt": {"nord": 62.41, "øst": 6.12},
        }
    ]
}


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
async def oslo(hass: HomeAssistant, tmp_path):
    await hass.config.async_set_time_zone("Europe/Oslo")
    hass.config.config_dir = str(tmp_path)


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _ws(hass_ws_client, hass, msg: dict) -> dict:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_routes_lists_route_with_state(hass: HomeAssistant, hass_ws_client, aioclient_mock, freezer) -> None:
    client = await hass_ws_client(hass)  # log in before the clock moves back
    freezer.move_to(datetime(2026, 11, 4, 7, 10, tzinfo=OSLO))  # the accident is on, in the window
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    entry = mock_entry()
    await _setup(hass, entry)

    await client.send_json_auto_id({"type": "vegvarsel/routes"})
    msg = await client.receive_json()
    assert msg["success"]
    (route,) = msg["result"]["routes"]
    assert route["route_id"] == ROUTE_ID and route["entry_id"] == entry.entry_id
    assert route["name"] == "Work"
    assert route["start"]["label"] == "Ålesund" and route["destination"]["label"] == "Vigra"
    assert len(route["points"]) > 20 and route["points"][0] == [62.4722, 6.1549]
    assert route["windows"] == ["06:30-08:00"] and route["days"][0] == "mon"
    assert route["problem"] is True and route["in_window"] is True
    assert route["watching_until"].startswith("2026-11-04T08:00")
    assert "NPRA_SYN_ELL_ACC" in [i["id"] for i in route["incidents"]]
    assert route["device_id"]


async def test_search_handles_norwegian_letters(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(ADDRESS_RE, json=ADDRESSES)
    aioclient_mock.get(NAMES_RE, json=NAMES)
    found = await places.async_search(async_get_clientsession(hass), "Eksempeløyvegen 5b")
    queries = [dict(c[1].query) for c in aioclient_mock.mock_calls if "adresser" in str(c[1])]
    assert {"sok": "Eksempeløyvegen 5b*"}.items() <= next(q for q in queries if "fuzzy" not in q).items()
    assert next(q for q in queries if q.get("fuzzy") == "true")["sok"] == "Eksempeløyvegen 5b"
    assert found[0] == {
        "label": "Eksempeløyvegen 5B, Ellingsøy",
        "latitude": 62.4,
        "longitude": 6.1,
        "kind": "address",
    }
    assert found[1] == {"label": "Eksempeløy (Øy i sjø), Ålesund", "latitude": 62.41, "longitude": 6.12, "kind": "place"}


async def test_search_command(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(ADDRESS_RE, json=ADDRESSES)
    aioclient_mock.get(NAMES_RE, json={"navn": []})
    assert await async_setup_component(hass, "vegvarsel", {})
    msg = await _ws(hass_ws_client, hass, {"type": "vegvarsel/search", "text": "Eksempeløy"})
    assert msg["success"] and [p["kind"] for p in msg["result"]["places"]] == ["address"]


async def test_search_short_text_is_empty(hass: HomeAssistant, aioclient_mock) -> None:
    assert await places.async_search(async_get_clientsession(hass), "Gr") == []
    assert aioclient_mock.call_count == 0


async def test_search_network_error_is_empty(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(ADDRESS_RE, exc=aiohttp.ClientError("down"))
    aioclient_mock.get(NAMES_RE, status=500)
    assert await places.async_search(async_get_clientsession(hass), "Eksempelvegen") == []


# --- plan and save ------------------------------------------------------------

def _osrm_two_routes() -> dict:
    body = osrm_body()
    first = body["routes"][0]
    detour = {
        "distance": first["distance"] + 4000,
        "duration": first["duration"] + 300,
        "geometry": {"type": "LineString", "coordinates": [[6.1549, 62.4722], [6.10, 62.45], [6.115, 62.559]]},
    }
    return {"code": "Ok", "routes": [first, detour]}


STOPS = [
    {"latitude": 62.4722, "longitude": 6.1549, "label": "Ålesund"},
    {"latitude": 62.559, "longitude": 6.115, "label": "Vigra"},
]


async def test_plan_returns_alternatives_and_incidents(hass: HomeAssistant, hass_ws_client, aioclient_mock, freezer) -> None:
    client = await hass_ws_client(hass)
    freezer.move_to(datetime(2026, 11, 4, 7, 10, tzinfo=OSLO))
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    aioclient_mock.get(OSRM_RE, json=_osrm_two_routes())
    await _setup(hass, mock_entry())

    await client.send_json_auto_id({"type": "vegvarsel/plan", "stops": STOPS})
    msg = await client.receive_json()
    assert msg["success"], msg
    first, second = msg["result"]["routes"]
    assert first["distance_m"] < second["distance_m"]
    assert len(first["points"]) > 20 and first["points"][0] == [62.4722, 6.1549]
    ids = {i["id"] for i in first["incidents"]}
    assert {"NPRA_SYN_ELL_ACC", "NPRA_SYN_ELL_NIGHT", "NPRA_SYN_VAL_CONVOY"} <= ids
    assert "NPRA_SYN_PARALLEL" not in ids
    osrm_call = next(c for c in aioclient_mock.mock_calls if "osrm" in str(c[1]))
    assert osrm_call[1].query["alternatives"] == "true"


async def test_plan_osrm_failure_is_error(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    aioclient_mock.get(OSRM_RE, json={"code": "NoRoute", "message": "Impossible route"})
    await _setup(hass, mock_entry())
    msg = await _ws(hass_ws_client, hass, {"type": "vegvarsel/plan", "stops": STOPS})
    assert not msg["success"] and msg["error"]["code"] == "no_route"


async def test_plan_needs_two_stops(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    await _setup(hass, mock_entry())
    msg = await _ws(hass_ws_client, hass, {"type": "vegvarsel/plan", "stops": STOPS[:1]})
    assert not msg["success"] and msg["error"]["code"] == "invalid_stops"


def _save_msg(**overrides) -> dict:
    msg = {
        "type": "vegvarsel/save_route",
        "name": "Example route",
        "start": STOPS[0],
        "destination": STOPS[1],
        "vias": [{"latitude": 62.5, "longitude": 6.15, "label": "Via"}],
        "points": [[lat, lon] for lat, lon in route_points()],
        "distance_m": 17147,
        "duration_s": 1133,
        "corridor_m": 200,
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "windows": ["06:45-08:15", "15:00-17:00"],
        "preview": "21:00:00",
    }
    msg.update(overrides)
    return msg


async def test_save_creates_route(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    entry = mock_entry()
    await _setup(hass, entry)
    msg = await _ws(hass_ws_client, hass, _save_msg())
    assert msg["success"], msg
    route_id = msg["result"]["route_id"]
    assert route_id != ROUTE_ID and len(entry.subentries) == 2
    data = entry.subentries[route_id].data
    assert entry.subentries[route_id].title == "Example route"
    assert data["windows"] == ["06:45-08:15", "15:00-17:00"] and data["corridor_m"] == 200
    assert data["vias"][0]["label"] == "Via"
    assert 20 < len(data["points"]) <= len(route_points())
    await hass.async_block_till_done()
    assert route_id in entry.runtime_data.monitors  # reloaded with the new route


async def test_save_updates_same_subentry(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    entry = mock_entry()
    await _setup(hass, entry)
    device_before = entry.runtime_data.device_id(ROUTE_ID)
    msg = await _ws(hass_ws_client, hass, _save_msg(route_id=ROUTE_ID, name="Renamed"))
    assert msg["success"], msg
    assert msg["result"]["route_id"] == ROUTE_ID
    await hass.async_block_till_done()
    assert list(entry.subentries) == [ROUTE_ID]
    assert entry.subentries[ROUTE_ID].title == "Renamed"
    assert entry.subentries[ROUTE_ID].data["windows"] == ["06:45-08:15", "15:00-17:00"]
    assert entry.runtime_data.device_id(ROUTE_ID) == device_before


async def test_save_rejects_bad_window(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    entry = mock_entry()
    await _setup(hass, entry)
    before = dict(entry.subentries[ROUTE_ID].data)
    msg = await _ws(hass_ws_client, hass, _save_msg(route_id=ROUTE_ID, windows=["7-8"]))
    assert not msg["success"] and msg["error"]["code"] == "invalid_schedule"
    assert "windows" in msg["error"]["message"]
    assert dict(entry.subentries[ROUTE_ID].data) == before


async def test_save_unknown_route_is_error(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    await _setup(hass, mock_entry())
    msg = await _ws(hass_ws_client, hass, _save_msg(route_id="nope"))
    assert not msg["success"] and msg["error"]["code"] == "not_found"


async def test_save_requires_admin(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    entry = mock_entry()
    await _setup(hass, entry)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(_save_msg())
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
    assert len(entry.subentries) == 1


def _address(text: str, town: str, lat: float, lon: float) -> dict:
    return {"adressetekst": text, "poststed": town, "representasjonspunkt": {"lat": lat, "lon": lon}}


async def test_search_prefix_matches_come_first(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(re.compile(r"adresser/v1/sok\?.*fuzzy=true"), json={"adresser": [
        _address("Annenvegen 12", "KLØFTA", 60.0, 11.0), _address("Eksempelvegen 12", "ÅLESUND", 62.47, 6.20)]})
    aioclient_mock.get(ADDRESS_RE, json={"adresser": [
        _address("Eksempelvegen 12", "ÅLESUND", 62.47, 6.20), _address("Eksempelvegen 120", "ÅLESUND", 62.45, 6.15)]})
    aioclient_mock.get(NAMES_RE, json={"navn": []})
    found = await places.async_search(async_get_clientsession(hass), "Eksempelvegen 12")
    assert [p["label"] for p in found] == [
        "Eksempelvegen 12, Ålesund", "Eksempelvegen 120, Ålesund", "Annenvegen 12, Kløfta"]


async def test_where_names_a_point(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(re.compile(r"adresser/v1/punktsok"), json={"adresser": [
        {**_address("Eksempeløyvegen 5B", "ELLINGSØY", 62.4, 6.1), "meterDistanseTilPunkt": 0.3}]})
    label = await places.async_where(async_get_clientsession(hass), 62.4, 6.1)
    assert label == "Eksempeløyvegen 5B, Ellingsøy"
    call = aioclient_mock.mock_calls[-1][1]
    assert call.query["lat"] == "62.4" and call.query["lon"] == "6.1"


async def test_where_nothing_near_is_none(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(re.compile(r"adresser/v1/punktsok"), json={"adresser": []})
    assert await places.async_where(async_get_clientsession(hass), 70.0, 25.0) is None


async def test_where_command(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    aioclient_mock.get(re.compile(r"adresser/v1/punktsok"), json={"adresser": [
        _address("Eksempelvegen 120", "ÅLESUND", 62.45, 6.15)]})
    assert await async_setup_component(hass, "vegvarsel", {})
    msg = await _ws(hass_ws_client, hass, {"type": "vegvarsel/where", "latitude": 62.45, "longitude": 6.15})
    assert msg["success"] and msg["result"] == {"label": "Eksempelvegen 120, Ålesund"}


async def test_search_nearby_first(hass: HomeAssistant, aioclient_mock) -> None:
    """Kartverket searches all of Norway; what is near home comes first."""
    aioclient_mock.get(re.compile(r"adresser/v1/sok\?.*fuzzy=true"), json={"adresser": [
        _address("Moo 1", "ÅLESUND", 62.47, 6.20)]})
    aioclient_mock.get(ADDRESS_RE, json={"adresser": [
        _address("Moavegen 33", "NAMDALSEID", 64.2, 11.2), _address("Moa park 2", "ÅLESUND", 62.47, 6.33)]})
    aioclient_mock.get(NAMES_RE, json={"navn": [
        {"skrivemåte": "Moadalen", "navneobjekttype": "Dal", "kommuner": [{"kommunenavn": "Rauma"}],
         "representasjonspunkt": {"nord": 62.55, "øst": 7.68}},
        {"skrivemåte": "Moa", "navneobjekttype": "Tettbebyggelse", "kommuner": [{"kommunenavn": "Ålesund"}],
         "representasjonspunkt": {"nord": 62.465, "øst": 6.34}},
    ]})
    found = await places.async_search(async_get_clientsession(hass), "Moa", limit=5, near=(62.4, 6.1))
    labels = [p["label"] for p in found]
    assert labels[:2] == ["Moa (Tettbebyggelse), Ålesund", "Moa park 2, Ålesund"]  # exact name, then nearest
    assert labels[2:4] == ["Moadalen (Dal), Rauma", "Moavegen 33, Namdalseid"]
    assert labels[4] == "Moo 1, Ålesund"  # a near miss comes after every real match
    queries = [dict(c[1].query) for c in aioclient_mock.mock_calls]
    assert all(q["treffPerSide"] == "50" for q in queries)


async def test_search_exact_name_first_and_two_per_street(hass: HomeAssistant, aioclient_mock) -> None:
    def park(n: int) -> dict:
        return {**_address(f"Moa park {n}", "ÅLESUND", 62.465, 6.34), "adressenavn": "Moa park"}

    aioclient_mock.get(re.compile(r"adresser/v1/sok\?.*fuzzy=true"), json={"adresser": []})
    aioclient_mock.get(ADDRESS_RE, json={"adresser": [park(2), park(4), park(6), park(8)]})
    aioclient_mock.get(NAMES_RE, json={"navn": [
        {"skrivemåte": "Moa", "navneobjekttype": "Tettbebyggelse", "kommuner": [{"kommunenavn": "Ålesund"}],
         "representasjonspunkt": {"nord": 62.47, "øst": 6.35}},
    ]})
    found = await places.async_search(async_get_clientsession(hass), "moa", near=(62.4, 6.1))
    assert [p["label"] for p in found] == [
        "Moa (Tettbebyggelse), Ålesund", "Moa park 2, Ålesund", "Moa park 4, Ålesund"]


async def test_search_far_exact_name_does_not_jump_ahead(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(re.compile(r"adresser/v1/sok\?.*fuzzy=true"), json={"adresser": []})
    aioclient_mock.get(ADDRESS_RE, json={"adresser": [_address("Moa park 2", "ÅLESUND", 62.465, 6.34)]})
    aioclient_mock.get(NAMES_RE, json={"navn": [
        {"skrivemåte": "Moa", "navneobjekttype": "Bygdelag (bygd)", "kommuner": [{"kommunenavn": "Grong"}],
         "representasjonspunkt": {"nord": 64.46, "øst": 12.31}},
        {"skrivemåte": "Moa", "navneobjekttype": "Tettbebyggelse", "kommuner": [{"kommunenavn": "Ålesund"}],
         "representasjonspunkt": {"nord": 62.47, "øst": 6.35}},
    ]})
    found = await places.async_search(async_get_clientsession(hass), "Moa", near=(62.4, 6.1))
    assert [p["label"] for p in found] == [
        "Moa (Tettbebyggelse), Ålesund", "Moa park 2, Ålesund", "Moa (Bygdelag (bygd)), Grong"]


async def test_routes_says_starting_while_vegvarsel_sets_up(hass: HomeAssistant, hass_ws_client, aioclient_mock) -> None:
    from homeassistant.config_entries import ConfigEntryState

    aioclient_mock.get(DATEX_SITUATION_URL, status=503)
    entry = mock_entry()
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    assert await async_setup_component(hass, "vegvarsel", {})
    msg = await _ws(hass_ws_client, hass, {"type": "vegvarsel/routes"})
    assert msg["success"] and msg["result"] == {"routes": [], "starting": True}
