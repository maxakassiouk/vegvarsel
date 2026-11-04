"""What every route entity shares: its device and its route's state."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, NAME
from .coordinator import VegvarselCoordinator
from .monitor import RouteState


def route_device(route_id: str, name: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, route_id)},
        name=name,
        manufacturer=NAME,
        model="Route",
        entry_type=DeviceEntryType.SERVICE,
    )


class RouteEntity(CoordinatorEntity[VegvarselCoordinator]):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: VegvarselCoordinator, route_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.route_id = route_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{route_id}_{key}"
        self._attr_device_info = route_device(route_id, coordinator.monitors[route_id].config.name)

    @property
    def route_state(self) -> RouteState:
        data = self.coordinator.data
        if data and self.route_id in data.routes:
            return data.routes[self.route_id]
        return RouteState()
