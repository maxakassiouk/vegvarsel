"""Finding places in Norway by what you type: Kartverket's address register
and its place names (both open, no key)."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import aiohttp

from .const import USER_AGENT

_LOGGER = logging.getLogger(__name__)

ADDRESS_URL = "https://ws.geonorge.no/adresser/v1/sok"
NAMES_URL = "https://ws.geonorge.no/stedsnavn/v1/navn"
POINT_URL = "https://ws.geonorge.no/adresser/v1/punktsok"
TIMEOUT = aiohttp.ClientTimeout(total=8)
MIN_LENGTH = 3


def _title(text: str) -> str:
    """Kartverket writes post towns in capitals: "ELLINGSØY" -> "Ellingsøy"."""
    return text.title() if text.isupper() else text


async def _get(session: aiohttp.ClientSession, url: str, params: dict[str, Any]) -> dict:
    try:
        async with session.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return {}
            return await resp.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError) as err:
        _LOGGER.debug("Place search at %s failed: %s", url, err)
        return {}


def _address_place(item: dict[str, Any]) -> dict[str, Any] | None:
    point = item.get("representasjonspunkt") or {}
    if point.get("lat") is None:
        return None
    town = _title(item.get("poststed") or item.get("kommunenavn") or "")
    label = ", ".join(p for p in (item.get("adressetekst"), town) if p)
    return {
        "label": label, "latitude": point["lat"], "longitude": point["lon"], "kind": "address",
        "_street": (item.get("adressenavn") or "", town),
    }


# Kartverket has no "near" filter, so a wide page of matches is fetched and
# sorted by distance from home here.
FETCH = 50
# An exact name this close to home goes before every other match.
EXACT_NEAR_KM = 100


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * 111.2, (a[1] - b[1]) * 111.2 * math.cos(math.radians((a[0] + b[0]) / 2)))


async def async_search(
    session: aiohttp.ClientSession,
    text: str,
    limit: int = 6,
    near: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Places matching what was typed: addresses and place names that start
    with it, then fuzzy near misses; within each, nearest to `near` first
    (Kartverket's own order without it). Duplicates dropped."""
    text = text.strip()
    if len(text) < MIN_LENGTH:
        return []
    common = {"treffPerSide": FETCH, "utkoordsys": 4258}
    prefix, fuzzy, names = await asyncio.gather(
        _get(session, ADDRESS_URL, {"sok": f"{text}*", **common}),
        _get(session, ADDRESS_URL, {"sok": text, "fuzzy": "true", **common}),
        _get(session, NAMES_URL, {"sok": f"{text}*", **common}),
    )
    matches: list[dict[str, Any]] = [p for p in map(_address_place, prefix.get("adresser") or []) if p]
    for item in names.get("navn") or []:
        point = item.get("representasjonspunkt") or {}
        if point.get("nord") is None:
            continue
        kind = item.get("navneobjekttype")
        town = ((item.get("kommuner") or [{}])[0]).get("kommunenavn")
        label = item.get("skrivemåte", "") + (f" ({kind})" if kind else "")
        label = ", ".join(p for p in (label, town) if p)
        exact = (item.get("skrivemåte") or "").casefold() == text.casefold()
        matches.append(
            {"label": label, "latitude": point["nord"], "longitude": point["øst"], "kind": "place", "_exact": exact}
        )
    misses = [p for p in map(_address_place, fuzzy.get("adresser") or []) if p]
    if near:
        def by_distance(place: dict[str, Any]) -> float:
            return _distance_km(near, (place["latitude"], place["longitude"]))

        matches.sort(key=by_distance)
        misses.sort(key=by_distance)
    # A place called exactly what was typed first - "Moa" before the
    # addresses in "Moa park" - when it is near; a namesake across the
    # country keeps its place by distance.
    def ahead(place: dict[str, Any]) -> bool:
        near_enough = near is None or _distance_km(near, (place["latitude"], place["longitude"])) <= EXACT_NEAR_KM
        return bool(place.get("_exact")) and near_enough

    matches.sort(key=lambda place: not ahead(place))
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_street: dict[tuple[str, str], int] = {}
    for place in matches + misses:
        street = place.get("_street")
        if place["label"] in seen or (street and street[0] and per_street.get(street, 0) >= 2):
            continue
        seen.add(place["label"])
        if street:
            per_street[street] = per_street.get(street, 0) + 1
        unique.append({k: v for k, v in place.items() if not k.startswith("_")})
    return unique[:limit]


async def async_where(session: aiohttp.ClientSession, latitude: float, longitude: float, radius: int = 250) -> str | None:
    """The nearest address to a point, as a label - or None if there is none
    within `radius` metres."""
    found = await _get(
        session,
        POINT_URL,
        {"lat": latitude, "lon": longitude, "radius": radius, "treffPerSide": 1, "utkoordsys": 4258},
    )
    for item in found.get("adresser") or []:
        place = _address_place(item)
        if place:
            return str(place["label"])
    return None
