"""Per route: is there a problem on the trip at hand."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import VegvarselConfigEntry, summary_text
from .entity import RouteEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VegvarselConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    for route_id in coordinator.monitors:
        async_add_entities([RouteProblemSensor(coordinator, route_id)], config_subentry_id=route_id)


class RouteProblemSensor(RouteEntity, BinarySensorEntity):
    """On while something on the route lies over the current or next trip."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, route_id: str) -> None:
        super().__init__(coordinator, route_id, "problem")

    @property
    def is_on(self) -> bool:
        return self.route_state.problem

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.route_state
        worst = state.worst
        language = self.hass.config.language if self.hass else None
        return {
            "in_window": state.in_window,
            "watching_from": state.focus[0].isoformat() if state.focus else None,
            "watching_until": state.focus[1].isoformat() if state.focus else None,
            "count": len(state.matches),
            "worst_kind": worst.incident.kind if worst else None,
            "worst": summary_text(worst.incident, language) if worst else None,
        }
