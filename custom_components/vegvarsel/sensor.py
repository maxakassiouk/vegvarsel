"""Per route: how many incidents lie over the trip at hand, and when the
next closure on the route begins."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import VegvarselConfigEntry, match_payload, summary_text
from .entity import RouteEntity

# Incidents listed in the attribute: enough for a card or a template,
# without filling the recorder.
MAX_LISTED = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VegvarselConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    for route_id in coordinator.monitors:
        async_add_entities(
            [RouteIncidentsSensor(coordinator, route_id), RouteNextClosureSensor(coordinator, route_id)],
            config_subentry_id=route_id,
        )


class RouteIncidentsSensor(RouteEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:road-variant"

    def __init__(self, coordinator, route_id: str) -> None:
        super().__init__(coordinator, route_id, "incidents")

    @property
    def native_value(self) -> int:
        return len(self.route_state.matches)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        language = self.hass.config.language if self.hass else None
        items = [match_payload(m, language) for m in self.route_state.matches[:MAX_LISTED]]
        return {"incidents": items}


class RouteNextClosureSensor(RouteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:road-variant"

    def __init__(self, coordinator, route_id: str) -> None:
        super().__init__(coordinator, route_id, "next_closure")

    @property
    def native_value(self) -> datetime | None:
        closure = self.route_state.next_closure
        if closure is None:
            return None
        # A closure going on since before anyone said: closed as of now.
        return closure.start or (dt_util.now() if closure.applies_now else None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        closure = self.route_state.next_closure
        if not closure:
            return {}
        language = self.hass.config.language if self.hass else None
        return {
            "ends": closure.end.isoformat() if closure.end else None,
            "summary": summary_text(closure.incident, language),
        }
