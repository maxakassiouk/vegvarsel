from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvarsel.const import (
    CONF_CORRIDOR,
    CONF_DAYS,
    CONF_POINTS,
    CONF_PREVIEW,
    CONF_START,
    CONF_WINDOWS,
    DOMAIN,
    SUBENTRY_ROUTE,
    VERSION,
)

from .helpers import DATEX_SITUATION_URL, OSRM_RE, ROUTE_ID, feed_without, mock_entry, osrm_body


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def tmp_config(hass: HomeAssistant, tmp_path):
    hass.config.config_dir = str(tmp_path)


@pytest.fixture(autouse=True)
def no_setup(monkeypatch):
    """Config flow tests do not set the entry up."""

    async def _ok(*_args, **_kwargs):
        return True

    monkeypatch.setattr("custom_components.vegvarsel.async_setup_entry", _ok)


async def test_account_ok(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: " user ", CONF_PASSWORD: "secret"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_USERNAME: "user", CONF_PASSWORD: "secret"}


async def test_account_refused(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, status=401)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user", CONF_PASSWORD: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_account_unreachable(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, status=503)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user", CONF_PASSWORD: "secret"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_add_route(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(OSRM_RE, json=osrm_body())
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_USERNAME: "u", CONF_PASSWORD: "p"}, unique_id="u")
    entry.add_to_hass(hass)

    flows = hass.config_entries.subentries
    result = await flows.async_init((entry.entry_id, SUBENTRY_ROUTE), context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await flows.async_configure(result["flow_id"], {"name": "Work"})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "start"
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "start_point"})
    result = await flows.async_configure(result["flow_id"], {"location": {"latitude": 62.4722, "longitude": 6.1549}})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "destination"
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "destination_point"})
    result = await flows.async_configure(result["flow_id"], {"location": {"latitude": 62.559, "longitude": 6.115}})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "vias"
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "review"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "review"
    assert result["description_placeholders"]["km"] == "17.1"
    result = await flows.async_configure(result["flow_id"], {})
    assert result["step_id"] == "settings"

    # a bad window is refused
    result = await flows.async_configure(
        result["flow_id"],
        {CONF_CORRIDOR: 150, CONF_DAYS: ["mon"], CONF_WINDOWS: ["half past six"], CONF_PREVIEW: "21:00:00"},
    )
    assert result["errors"] == {CONF_WINDOWS: "invalid_window"}

    result = await flows.async_configure(
        result["flow_id"],
        {CONF_CORRIDOR: 150, CONF_DAYS: ["mon", "tue"], CONF_WINDOWS: ["06:30-08:00", "15:30-17:00"], CONF_PREVIEW: "21:00:00"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "Work"
    assert subentry.data[CONF_WINDOWS] == ["06:30-08:00", "15:30-17:00"]
    assert 20 < len(subentry.data[CONF_POINTS]) < 100


async def test_no_route(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(OSRM_RE, json={"code": "NoRoute", "message": "Impossible route"})
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_USERNAME: "u", CONF_PASSWORD: "p"}, unique_id="u")
    entry.add_to_hass(hass)
    flows = hass.config_entries.subentries
    result = await flows.async_init((entry.entry_id, SUBENTRY_ROUTE), context={"source": config_entries.SOURCE_USER})
    result = await flows.async_configure(result["flow_id"], {"name": "Boat"})
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "start_point"})
    result = await flows.async_configure(result["flow_id"], {"location": {"latitude": 62.0, "longitude": 6.0}})
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "destination_point"})
    result = await flows.async_configure(result["flow_id"], {"location": {"latitude": 62.1, "longitude": 4.0}})
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "review"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "no_route"


async def test_reconfigure_route(hass: HomeAssistant) -> None:
    entry = mock_entry()
    entry.add_to_hass(hass)
    flows = hass.config_entries.subentries
    result = await flows.async_init(
        (entry.entry_id, SUBENTRY_ROUTE),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": ROUTE_ID},
    )
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "reconfigure"
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "reconfigure_settings"})
    assert result["step_id"] == "reconfigure_settings"
    result = await flows.async_configure(
        result["flow_id"],
        {"name": "Til jobb", CONF_CORRIDOR: 200, CONF_DAYS: ["mon"], CONF_WINDOWS: [], "recalculate": False},
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    subentry = entry.subentries[ROUTE_ID]
    assert subentry.title == "Til jobb"
    assert subentry.data[CONF_CORRIDOR] == 200 and subentry.data[CONF_WINDOWS] == []
    assert subentry.data[CONF_PREVIEW] is None


async def test_change_the_route_itself(hass: HomeAssistant, aioclient_mock) -> None:
    """Keep the start, move the destination, replace the via points; the schedule stays."""
    aioclient_mock.get(OSRM_RE, json=osrm_body())
    entry = mock_entry()
    entry.add_to_hass(hass)
    before = dict(entry.subentries[ROUTE_ID].data)
    flows = hass.config_entries.subentries
    result = await flows.async_init(
        (entry.entry_id, SUBENTRY_ROUTE),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": ROUTE_ID},
    )
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "reconfigure_route"})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "start"
    assert result["menu_options"][0] == "start_keep"
    assert result["description_placeholders"]["current"] == "Ålesund"
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "start_keep"})
    assert result["step_id"] == "destination" and "destination_keep" in result["menu_options"]
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "destination_point"})
    # the map opens at the current destination
    location = next(k for k in result["data_schema"].schema if str(k) == "location")
    assert location.default() == {"latitude": 62.559, "longitude": 6.115}
    result = await flows.async_configure(result["flow_id"], {"location": {"latitude": 62.56, "longitude": 6.12}})
    assert result["step_id"] == "vias"
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "via"})
    result = await flows.async_configure(result["flow_id"], {"location": {"latitude": 62.5, "longitude": 6.15}})
    result = await flows.async_configure(result["flow_id"], {"next_step_id": "review"})
    assert result["step_id"] == "review"
    result = await flows.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    after = entry.subentries[ROUTE_ID].data
    assert after[CONF_START] == before[CONF_START]
    assert after["destination"]["latitude"] == 62.56
    assert len(after["vias"]) == 1
    assert after[CONF_WINDOWS] == before[CONF_WINDOWS] and after[CONF_DAYS] == before[CONF_DAYS]
    assert len(entry.subentries) == 1  # the same route, not a new one


async def test_custom_feed_address(hass: HomeAssistant, aioclient_mock) -> None:
    demo_url = "http://192.168.1.20:8765/datexapi/GetSituation/pullsnapshotdata"
    aioclient_mock.get(demo_url, text=feed_without())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "demo", CONF_PASSWORD: "demo", "advanced": {"url": demo_url}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["url"] == demo_url
    assert result["title"] == f"Feed at {demo_url}"


async def test_default_feed_address_is_not_stored(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, text=feed_without())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "u", CONF_PASSWORD: "p", "advanced": {"url": DATEX_SITUATION_URL}}
    )
    assert "url" not in result["data"]


async def test_406_falls_back_to_plainer_headers(hass: HomeAssistant, aioclient_mock) -> None:
    """Statens vegvesen answered 406 to the first way of asking; the plainer one works."""
    calls: list[dict] = []

    async def _answer(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        headers = aioclient_mock.mock_calls[-1][3]
        calls.append(dict(headers))
        if headers.get("User-Agent", "").startswith("vegvarsel"):
            return AiohttpClientMockResponse(method, url, status=406)
        return AiohttpClientMockResponse(method, url, status=200, text=feed_without())

    aioclient_mock.get(DATEX_SITUATION_URL, side_effect=_answer)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user", CONF_PASSWORD: "secret"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [c["User-Agent"] for c in calls] == [f"vegvarsel-homeassistant/{VERSION}", "python-requests/2.32.3"]
    assert all(c["Accept-Encoding"] == "gzip, deflate" for c in calls)


async def test_406_every_way_is_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DATEX_SITUATION_URL, status=406)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user", CONF_PASSWORD: "secret"}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert aioclient_mock.call_count == 3
