"""Setup: the DATEX account, then any number of routes under it."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)
import voluptuous as vol

from .api import DatexAuthError, DatexClient, DatexError, RoutingError, async_osrm_route
from .const import (
    CONF_CORRIDOR,
    CONF_DAYS,
    CONF_DESTINATION,
    CONF_DISTANCE,
    CONF_DURATION,
    CONF_POINTS,
    CONF_PREVIEW,
    CONF_SCAN_MINUTES,
    CONF_START,
    CONF_VIAS,
    CONF_WINDOWS,
    DATEX_ACCESS_URL,
    DATEX_SITUATION_URL,
    DEFAULT_CORRIDOR,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    MAX_SCAN_MINUTES,
    MAX_VIAS,
    MIN_SCAN_MINUTES,
    SUBENTRY_ROUTE,
)
from .route_data import clean_settings, route_line
from .schedule import WEEKDAYS

_LOGGER = logging.getLogger(__name__)


CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(),
        vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    }
)


async def _check_credentials(
    hass: HomeAssistant, username: str, password: str, url: str = DATEX_SITUATION_URL
) -> str | None:
    """None if the feed answers, else an error key."""
    try:
        await DatexClient(async_get_clientsession(hass), username, password, url).async_fetch()
    except DatexAuthError:
        return "invalid_auth"
    except DatexError as err:
        _LOGGER.warning("DATEX feed did not answer: %s", err)
        return "cannot_connect"
    return None


class VegvarselConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VegvarselOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_ROUTE: RouteSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            url = ((user_input.get("advanced") or {}).get(CONF_URL) or DATEX_SITUATION_URL).strip()
            custom = url != DATEX_SITUATION_URL
            await self.async_set_unique_id(f"{username.lower()}@{url}" if custom else username.lower())
            self._abort_if_unique_id_configured()
            error = await _check_credentials(self.hass, username, user_input[CONF_PASSWORD], url)
            if error is None:
                data = {CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                if custom:
                    data[CONF_URL] = url
                return self.async_create_entry(
                    title=f"Feed at {url}" if custom else f"Statens vegvesen ({username})", data=data
                )
            errors["base"] = error
        # A feed address other than Statens vegvesen's - the demo feed in
        # tools/demo_feed.py, or a mirror - tucked away in a folded section.
        schema = CREDENTIALS_SCHEMA.extend(
            {
                vol.Optional("advanced"): section(
                    vol.Schema({vol.Optional(CONF_URL, default=DATEX_SITUATION_URL): TextSelector()}),
                    {"collapsed": True},
                )
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
            description_placeholders={"access_url": DATEX_ACCESS_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _check_credentials(
                self.hass,
                entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                entry.data.get(CONF_URL, DATEX_SITUATION_URL),
            )
            if error is None:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]})
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
            ),
            errors=errors,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
        )


class VegvarselOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_SCAN_MINUTES: int(user_input[CONF_SCAN_MINUTES])})
        current = self.config_entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_MINUTES, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_MINUTES, max=MAX_SCAN_MINUTES, step=1,
                            mode=NumberSelectorMode.BOX, unit_of_measurement="min",
                        )  # fmt: skip
                    )
                }
            ),
        )


# --- routes -------------------------------------------------------------------


def _settings_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CORRIDOR, default=defaults.get(CONF_CORRIDOR, DEFAULT_CORRIDOR)): NumberSelector(
                NumberSelectorConfig(min=30, max=1000, step=10, mode=NumberSelectorMode.BOX, unit_of_measurement="m")
            ),
            vol.Required(CONF_DAYS, default=defaults.get(CONF_DAYS, list(WEEKDAYS[:5]))): SelectSelector(
                SelectSelectorConfig(
                    options=list(WEEKDAYS), multiple=True, mode=SelectSelectorMode.LIST, translation_key="weekday"
                )
            ),
            vol.Optional(CONF_WINDOWS, default=defaults.get(CONF_WINDOWS, ["06:30-08:00"])): TextSelector(
                TextSelectorConfig(multiple=True)
            ),
            vol.Optional(
                CONF_PREVIEW, description={"suggested_value": defaults.get(CONF_PREVIEW, "21:00:00")}
            ): TimeSelector(),
        }
    )


def _place(lat: float, lon: float, label: str) -> dict[str, Any]:
    return {"latitude": round(float(lat), 6), "longitude": round(float(lon), 6), "label": label}


class RouteSubentryFlow(ConfigSubentryFlow):
    """Name, start, destination, optional via points, review, schedule."""

    def __init__(self) -> None:
        self._name = ""
        self._start: dict[str, Any] | None = None
        self._destination: dict[str, Any] | None = None
        self._vias: list[dict[str, Any]] = []
        self._route: dict[str, Any] | None = None
        # Changing an existing route's line (reconfigure): its current ends
        # can be kept, and the result updates the route rather than adding one.
        self._editing = False

    def _home(self) -> dict[str, float]:
        return {"latitude": self.hass.config.latitude, "longitude": self.hass.config.longitude}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._name = user_input[CONF_NAME].strip() or "Route"
            return await self.async_step_start()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default="Til jobb"): TextSelector()}),
        )

    # start / destination: a zone or a point on the map

    async def async_step_start(self, user_input=None) -> SubentryFlowResult:
        options = ["start_zone", "start_point"]
        if self._editing and self._start:
            options.insert(0, "start_keep")
        return self.async_show_menu(
            step_id="start", menu_options=options, description_placeholders={"current": self._label("start")}
        )

    async def async_step_destination(self, user_input=None) -> SubentryFlowResult:
        options = ["destination_zone", "destination_point"]
        if self._editing and self._destination:
            options.insert(0, "destination_keep")
        return self.async_show_menu(
            step_id="destination", menu_options=options, description_placeholders={"current": self._label("destination")}
        )

    async def async_step_start_keep(self, user_input=None) -> SubentryFlowResult:
        return await self.async_step_destination()

    async def async_step_destination_keep(self, user_input=None) -> SubentryFlowResult:
        return await self.async_step_vias()

    def _label(self, end: str) -> str:
        place = self._start if end == "start" else self._destination
        return place["label"] if place else "-"

    def _map_default(self, end: str | None) -> dict[str, float]:
        """Where a map opens: the point being changed, else between the two
        ends (a via point lies on the way), else home."""
        place = {"start": self._start, "destination": self._destination}.get(end or "")
        if place:
            return {"latitude": place["latitude"], "longitude": place["longitude"]}
        if self._start and self._destination:
            return {
                "latitude": (self._start["latitude"] + self._destination["latitude"]) / 2,
                "longitude": (self._start["longitude"] + self._destination["longitude"]) / 2,
            }
        return self._home()

    async def async_step_start_zone(self, user_input=None) -> SubentryFlowResult:
        return await self._zone_step("start", user_input)

    async def async_step_destination_zone(self, user_input=None) -> SubentryFlowResult:
        return await self._zone_step("destination", user_input)

    async def async_step_start_point(self, user_input=None) -> SubentryFlowResult:
        return await self._point_step("start", user_input)

    async def async_step_destination_point(self, user_input=None) -> SubentryFlowResult:
        return await self._point_step("destination", user_input)

    async def _zone_step(self, end: str, user_input) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            state = self.hass.states.get(user_input["zone"])
            if state and state.attributes.get("latitude") is not None:
                place = _place(
                    state.attributes["latitude"],
                    state.attributes["longitude"],
                    state.attributes.get("friendly_name") or user_input["zone"],
                )
                return await self._accept(end, place)
            errors["base"] = "zone_without_position"
        return self.async_show_form(
            step_id=f"{end}_zone",
            data_schema=vol.Schema({vol.Required("zone"): EntitySelector(EntitySelectorConfig(domain="zone"))}),
            errors=errors,
        )

    async def _point_step(self, end: str, user_input) -> SubentryFlowResult:
        if user_input is not None:
            loc = user_input["location"]
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
            return await self._accept(end, _place(lat, lon, f"{lat:.5f}, {lon:.5f}"))
        return self.async_show_form(
            step_id=f"{end}_point",
            data_schema=vol.Schema(
                {
                    vol.Required("location", default=self._map_default(end)): LocationSelector(
                        LocationSelectorConfig(radius=False)
                    )
                }
            ),
        )

    async def _accept(self, end: str, place: dict[str, Any]) -> SubentryFlowResult:
        self._route = None
        if end == "start":
            self._start = place
            return await self.async_step_destination()
        self._destination = place
        return await self.async_step_vias()

    # via points: to make the line follow the road you actually drive

    async def async_step_vias(self, user_input=None) -> SubentryFlowResult:
        options = ["review"]
        if len(self._vias) < MAX_VIAS:
            options.insert(0, "via")
        if self._vias:
            options.append("vias_clear")
        return self.async_show_menu(
            step_id="vias", menu_options=options, description_placeholders={"count": str(len(self._vias))}
        )

    async def async_step_via(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            loc = user_input["location"]
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
            self._vias.append(_place(lat, lon, f"{lat:.5f}, {lon:.5f}"))
            self._route = None
            return await self.async_step_vias()
        return self.async_show_form(
            step_id="via",
            data_schema=vol.Schema(
                {
                    vol.Required("location", default=self._map_default(None)): LocationSelector(
                        LocationSelectorConfig(radius=False)
                    )
                }
            ),
        )

    async def async_step_vias_clear(self, user_input=None) -> SubentryFlowResult:
        self._vias = []
        self._route = None
        return await self.async_step_vias()

    async def async_step_review(self, user_input=None) -> SubentryFlowResult:
        if self._route is None:
            assert self._start and self._destination
            stops = [self._start, *self._vias, self._destination]
            try:
                route = await async_osrm_route(
                    async_get_clientsession(self.hass), [(p["latitude"], p["longitude"]) for p in stops]
                )
            except RoutingError as err:
                _LOGGER.warning("No route: %s", err)
                return self.async_abort(reason="no_route", description_placeholders={"error": str(err)})
            self._route = {
                CONF_POINTS: route_line(route.points),
                CONF_DISTANCE: round(route.distance_m),
                CONF_DURATION: round(route.duration_s),
            }
        if user_input is not None:
            if self._editing:
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    data_updates={
                        CONF_START: self._start,
                        CONF_DESTINATION: self._destination,
                        CONF_VIAS: self._vias,
                        **self._route,
                    },
                )
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="review",
            data_schema=vol.Schema({}),
            description_placeholders={
                "start": self._start["label"],
                "destination": self._destination["label"],
                "vias": str(len(self._vias)),
                "km": f"{self._route[CONF_DISTANCE] / 1000:.1f}",
                "minutes": str(round(self._route[CONF_DURATION] / 60)),
                "map_url": _map_url(self._start, self._vias, self._destination),
            },
        )

    async def async_step_settings(self, user_input=None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            settings, errors = clean_settings(user_input)
            if not errors:
                return self.async_create_entry(
                    title=self._name,
                    data={
                        CONF_START: self._start,
                        CONF_DESTINATION: self._destination,
                        CONF_VIAS: self._vias,
                        **(self._route or {}),
                        **settings,
                    },
                )
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(_settings_schema({}), user_input or {}),
            errors=errors,
        )

    # reconfigure: the schedule and corridor, or the line itself

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_settings", "reconfigure_route"],
            description_placeholders={"name": self._get_reconfigure_subentry().title},
        )

    async def async_step_reconfigure_route(self, user_input=None) -> SubentryFlowResult:
        """The same steps as a new route, starting from this one's points."""
        data = self._get_reconfigure_subentry().data
        self._editing = True
        self._start = dict(data[CONF_START])
        self._destination = dict(data[CONF_DESTINATION])
        self._vias = [dict(v) for v in data.get(CONF_VIAS, [])]
        self._route = None
        return await self.async_step_start()

    async def async_step_reconfigure_settings(self, user_input=None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            settings, errors = clean_settings(user_input)
            updates: dict[str, Any] = dict(settings)
            if not errors and user_input.get("recalculate"):
                data = subentry.data
                stops = [data[CONF_START], *data.get(CONF_VIAS, []), data[CONF_DESTINATION]]
                try:
                    route = await async_osrm_route(
                        async_get_clientsession(self.hass), [(p["latitude"], p["longitude"]) for p in stops]
                    )
                except RoutingError:
                    errors["base"] = "no_route"
                else:
                    updates[CONF_POINTS] = route_line(route.points)
                    updates[CONF_DISTANCE] = round(route.distance_m)
                    updates[CONF_DURATION] = round(route.duration_s)
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=(user_input.get(CONF_NAME) or subentry.title).strip(),
                    data_updates=updates,
                )
        schema = vol.Schema(
            {vol.Required(CONF_NAME, default=subentry.title): TextSelector()}
            | dict(_settings_schema(subentry.data).schema)
            | {vol.Optional("recalculate", default=False): BooleanSelector()}
        )
        return self.async_show_form(step_id="reconfigure_settings", data_schema=schema, errors=errors)


def _map_url(start: dict, vias: list[dict], destination: dict) -> str:
    """The same route on openstreetmap.org, to check it is the road you drive."""
    points = [start, *vias, destination]
    route = ";".join(f"{p['latitude']},{p['longitude']}" for p in points)
    return f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={route}"
