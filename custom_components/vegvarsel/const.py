"""Constants for Vegvarsel."""

from __future__ import annotations

DOMAIN = "vegvarsel"
NAME = "Vegvarsel"
VERSION = "0.2.1"
USER_AGENT = f"vegvarsel-homeassistant/{VERSION} (+https://github.com/maxakassiouk/vegvarsel)"

# Statens vegvesen DATEX II v3.1, situation publication (Basic auth, free access on request).
DATEX_SITUATION_URL = "https://datex-server-get-v3-1.atlas.vegvesen.no/datexapi/GetSituation/pullsnapshotdata"
DATEX_ACCESS_URL = "https://www.vegvesen.no/en/fag/technology/open-data/a-selection-of-open-data/what-is-datex/get-access/"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving/"

# The dashboard card: served from here, and the element it defines.
CARD_URL_BASE = f"/{DOMAIN}_static"
CARD_TAG = f"{DOMAIN}-card"

ATTRIBUTION = "Trafikkdata fra Statens vegvesen (NLOD). Ruter fra OSRM / © OpenStreetMap-bidragsytere."

# Main entry
CONF_SCAN_MINUTES = "scan_minutes"
DEFAULT_SCAN_MINUTES = 2
MIN_SCAN_MINUTES = 1
MAX_SCAN_MINUTES = 30

# Route subentries
SUBENTRY_ROUTE = "route"
CONF_START = "start"
CONF_DESTINATION = "destination"
CONF_VIAS = "vias"
CONF_POINTS = "points"
CONF_DISTANCE = "distance_m"
CONF_DURATION = "duration_s"
CONF_CORRIDOR = "corridor_m"
CONF_DAYS = "days"
CONF_WINDOWS = "windows"
CONF_PREVIEW = "preview"
DEFAULT_CORRIDOR = 150
MAX_VIAS = 5

# Events
EVENT_NEW = f"{DOMAIN}_incident_new"
EVENT_UPDATED = f"{DOMAIN}_incident_updated"
EVENT_CLEARED = f"{DOMAIN}_incident_cleared"
EVENT_DIGEST = f"{DOMAIN}_digest"

# Polls failing in a row before a repair is raised.
FAILURES_FOR_REPAIR = 3

KIND_ICONS = {
    "closed": "mdi:road-variant",
    "accident": "mdi:car-emergency",
    "convoy": "mdi:car-multiple",
    "obstruction": "mdi:alert-octagon",
    "traffic": "mdi:car-clock",
    "restriction": "mdi:traffic-light",
    "roadworks": "mdi:account-hard-hat",
    "conditions": "mdi:snowflake-alert",
    "info": "mdi:information-outline",
}

KIND_LABELS = {
    "closed": {"en": "Road closed", "nb": "Stengt veg", "nn": "Stengd veg"},
    "accident": {"en": "Accident", "nb": "Ulykke", "nn": "Ulukke"},
    "convoy": {"en": "Convoy driving", "nb": "Kolonnekjøring", "nn": "Kolonnekøyring"},
    "obstruction": {"en": "Obstruction", "nb": "Hindring i vegen", "nn": "Hinder i vegen"},
    "traffic": {"en": "Queues", "nb": "Kø", "nn": "Kø"},
    "restriction": {"en": "Restriction", "nb": "Trafikkregulering", "nn": "Trafikkregulering"},
    "roadworks": {"en": "Roadworks", "nb": "Vegarbeid", "nn": "Vegarbeid"},
    "conditions": {"en": "Driving conditions", "nb": "Føreforhold", "nn": "Føreforhold"},
    "info": {"en": "Traffic message", "nb": "Trafikkmelding", "nn": "Trafikkmelding"},
}


def kind_label(kind: str, language: str | None) -> str:
    labels = KIND_LABELS.get(kind) or KIND_LABELS["info"]
    code = (language or "en").lower()
    if code.startswith("no"):
        code = "nb"
    return labels.get(code) or labels.get(code[:2]) or labels["en"]
