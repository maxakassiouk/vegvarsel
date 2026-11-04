"""The integration end to end: a mocked feed, a route, the clock."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.vegvarsel.const import DOMAIN, EVENT_CLEARED, EVENT_DIGEST, EVENT_NEW, SUBENTRY_ROUTE

from .helpers import DATEX_SITUATION_URL, ROUTE_ID, feed_without, mock_entry

OSLO = ZoneInfo("Europe/Oslo")
ACCIDENT = "NPRA_SYN_ELL_ACC_1"


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
async def oslo_time(hass: HomeAssistant, tmp_path):
    await hass.config.async_set_time_zone("Europe/Oslo")
    hass.config.language = "nb"
    hass.config.config_dir = str(tmp_path)


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=OSLO)


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass, entry):
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _entity(hass, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{ROUTE_ID}_{key}")
    assert entity_id, f"no {platform} {key}"
    return entity_id


async def test_accident_in_the_tunnel(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    freezer.move_to(at(4, 7, 0))
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without(ACCIDENT))
    entry = mock_entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    problem = _entity(hass, "binary_sensor", "problem")
    incidents = _entity(hass, "sensor", "incidents")
    assert hass.states.get(problem).state == "off"  # night closure is over by 06:00
    assert hass.states.get(incidents).state == "0"

    new_events = async_capture_events(hass, EVENT_NEW)
    aioclient_mock.clear_requests()
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    freezer.move_to(at(4, 7, 10))
    await _poll(hass, entry)

    assert hass.states.get(problem).state == "on"
    assert hass.states.get(incidents).state == "1"
    (event,) = new_events
    (device,) = (
        device
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (DOMAIN, ROUTE_ID) in device.identifiers
    )
    assert event.data["route"] == "Work"
    assert event.data["device_id"] == device.id
    assert event.data["kind"] == "accident"
    assert event.data["kind_name"] == "Ulykke"
    assert 3.0 < event.data["distance_km"] < 3.6
    assert "Ellingsøytunnelen" in event.data["summary"]

    # a marker on the map
    markers = [s for s in hass.states.async_all("geo_location") if s.attributes.get("source") == "vegvarsel_work"]
    assert [m.attributes["record_id"] for m in markers] == [ACCIDENT]

    # cleared
    cleared = async_capture_events(hass, EVENT_CLEARED)
    aioclient_mock.clear_requests()
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without(ACCIDENT))
    freezer.move_to(at(4, 7, 40))
    await _poll(hass, entry)
    assert [e.data["record_id"] for e in cleared] == [ACCIDENT]
    assert hass.states.get(problem).state == "off"
    assert not [s for s in hass.states.async_all("geo_location") if s.attributes.get("source") == "vegvarsel_work"]


async def test_window_start_digest_and_preview(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without(ACCIDENT))
    freezer.move_to(at(4, 20, 58))
    entry = mock_entry()
    await _setup(hass, entry)
    digests = async_capture_events(hass, EVENT_DIGEST)

    freezer.move_to(at(4, 21, 0))
    await _poll(hass, entry)
    (preview,) = digests
    assert preview.data["reason"] == "evening_preview"
    assert [i["kind"] for i in preview.data["incidents"]] == ["convoy"]

    freezer.move_to(at(5, 6, 30))
    await _poll(hass, entry)
    assert digests[-1].data["reason"] == "window_start"
    assert digests[-1].data["count"] == 1

    # the convoy (06:00-09:00) is going on, so it is the closure shown - from when it began
    closure = hass.states.get(_entity(hass, "sensor", "next_closure"))
    assert closure.state == "2026-11-05T05:00:00+00:00"  # 06:00 Oslo
    assert closure.attributes["summary"].startswith("Kolonnekjøring")

    # after it, the night closure of the tunnel is next: Thursday 22:00
    freezer.move_to(at(5, 9, 30))
    await _poll(hass, entry)
    closure = hass.states.get(_entity(hass, "sensor", "next_closure"))
    assert closure.state == "2026-11-05T21:00:00+00:00"
    assert closure.attributes["ends"].startswith("2026-11-06T06:00:00")


async def test_bad_password_starts_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, status=401)
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_blueprint_installed(hass: HomeAssistant, aioclient_mock, tmp_path) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    await _setup(hass, mock_entry())
    assert (tmp_path / "blueprints" / "automation" / DOMAIN / "route_alerts.yaml").is_file()


async def test_adding_a_route_reloads(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    entry = mock_entry()
    await _setup(hass, entry)
    route = entry.subentries[ROUTE_ID]
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(data=dict(route.data), subentry_type=SUBENTRY_ROUTE, title="Home", unique_id=None),
    )
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.runtime_data.monitors) == 2
    problems = [s for s in hass.states.async_all("binary_sensor") if s.entity_id.endswith(("problem_pa_ruten", "problem_pa_ruten_2"))]
    assert len(problems) == 2

    hass.config_entries.async_remove_subentry(entry, ROUTE_ID)
    await hass.async_block_till_done()
    assert list(entry.runtime_data.monitors) != [ROUTE_ID] and len(entry.runtime_data.monitors) == 1


async def test_unload(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    entry = mock_entry()
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
