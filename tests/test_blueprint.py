"""The bundled blueprint, run by Home Assistant's own automation engine."""

from __future__ import annotations

from pathlib import Path
import shutil

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.vegvarsel.const import EVENT_CLEARED, EVENT_DIGEST, EVENT_NEW

SOURCE = Path(__file__).parents[1] / "custom_components/vegvarsel/blueprints/automation/vegvarsel/route_alerts.yaml"

INCIDENT = {
    "config_entry_id": "e1",
    "route_id": "r1",
    "route": "Til jobb",
    "device_id": "dev1",
    "id": "NPRA_1",
    "kind": "closed",
    "kind_name": "Stengt veg",
    "summary": "Stengt veg · Fv658 / Ellingsøytunnelen — Tunnelen er stengt.",
    "road": "Fv658 / Ellingsøytunnelen",
    "description": "Tunnelen er stengt.",
    "distance_km": 3.3,
    "start": "2026-11-04T07:05:00+01:00",
    "end": None,
    "applies_now": True,
}


@pytest.fixture
async def calls(hass: HomeAssistant, tmp_path):
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints/automation/vegvarsel"
    target.mkdir(parents=True)
    shutil.copyfile(SOURCE, target / "route_alerts.yaml")
    calls = async_mock_service(hass, "test", "notify")
    yield calls


async def _automation(hass: HomeAssistant, **inputs) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "vegvarsel/route_alerts.yaml",
                    "input": {
                        "user_actions": [
                            {"action": "test.notify", "data": {"title": "{{ title }}", "message": "{{ message }}"}}
                        ],
                        **inputs,
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()


async def test_new_incident(hass: HomeAssistant, calls) -> None:
    await _automation(hass)
    hass.bus.async_fire(EVENT_NEW, INCIDENT)
    await hass.async_block_till_done()
    (call,) = calls
    assert call.data["title"] == "🚧 Til jobb: Stengt veg"
    assert call.data["message"] == "Stengt veg · Fv658 / Ellingsøytunnelen — Tunnelen er stengt. (km 3.3)"


async def test_planned_incident_says_from_when(hass: HomeAssistant, calls) -> None:
    await _automation(hass)
    hass.bus.async_fire(EVENT_NEW, INCIDENT | {"applies_now": False})
    await hass.async_block_till_done()
    assert "From " in calls[0].data["message"]


async def test_filters(hass: HomeAssistant, calls) -> None:
    await _automation(hass, kinds=["accident"], routes=["another-device"])
    hass.bus.async_fire(EVENT_NEW, INCIDENT)
    await hass.async_block_till_done()
    assert calls == []


async def test_cleared(hass: HomeAssistant, calls) -> None:
    await _automation(hass)
    hass.bus.async_fire(EVENT_CLEARED, INCIDENT)
    await hass.async_block_till_done()
    assert calls[0].data["title"] == "✅ Til jobb: cleared"


async def test_digest_lists_incidents_and_all_clear_is_optional(hass: HomeAssistant, calls) -> None:
    await _automation(hass)
    digest = {
        "route_id": "r1", "route": "Til jobb", "device_id": "dev1", "reason": "evening_preview",
        "count": 1, "incidents": [INCIDENT], "summary": INCIDENT["summary"],
    }  # fmt: skip
    hass.bus.async_fire(EVENT_DIGEST, digest)
    hass.bus.async_fire(EVENT_DIGEST, digest | {"count": 0, "incidents": [], "summary": ""})
    await hass.async_block_till_done()
    (call,) = calls  # the empty one is not sent by default
    assert call.data["title"] == "🌙 Tomorrow, Til jobb"
    assert call.data["message"].startswith("• Stengt veg")


async def test_all_clear_when_asked(hass: HomeAssistant, calls) -> None:
    await _automation(hass, send_all_clear=True)
    hass.bus.async_fire(
        EVENT_DIGEST,
        {"route_id": "r1", "route": "Til jobb", "device_id": "dev1", "reason": "window_start", "count": 0, "incidents": []},
    )
    await hass.async_block_till_done()
    assert calls[0].data["title"] == "✅ Til jobb"
    assert calls[0].data["message"] == "Nothing reported on the route."
