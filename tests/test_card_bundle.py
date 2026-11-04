"""Shipping the dashboard card and the blueprint with the integration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest

from custom_components.vegvarsel import bundle, lovelace_resource
from custom_components.vegvarsel.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def tmp_config(hass: HomeAssistant, tmp_path):
    hass.config.config_dir = str(tmp_path)


async def test_card_served_and_listed(hass: HomeAssistant) -> None:
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch.object(bundle, "add_extra_js_url") as add:
        await bundle.async_register_card(hass)
    (url,) = [call.args[1] for call in add.call_args_list]
    assert url.startswith("/vegvarsel_static/vegvarsel-card-loader.js?v=")
    served = {p.url_path for p in hass.http.async_register_static_paths.call_args.args[0]}
    assert {"/vegvarsel_static/vegvarsel-card.js", "/vegvarsel_static/vegvarsel-card-loader.js"} <= served
    version = hass.data[DOMAIN]["card_version"]
    assert isinstance(version, int) and url.endswith(f"?v={version}")


async def test_card_version_command(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    hass.data[DOMAIN]["card_version"] = 1234
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "vegvarsel/card_version"})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"] == {"version": 1234}


class FakeResources:
    """The dashboards' storage-mode resource collection, as far as we use it."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = list(items or [])
        self.loaded = False

    async def async_get_info(self):
        self.loaded = True
        return {"resources": len(self.items)}

    def async_items(self):
        assert self.loaded, "items read before the store was loaded"
        return self.items

    async def async_create_item(self, data):
        self.items.append({"id": f"id{len(self.items)}", "url": data["url"], "type": data["res_type"]})

    async def async_update_item(self, item_id, data):
        for item in self.items:
            if item["id"] == item_id:
                item.update(url=data["url"], type=data["res_type"])

    async def async_delete_item(self, item_id):
        self.items = [i for i in self.items if i["id"] != item_id]


async def test_resource_listed_once_and_kept_current(hass: HomeAssistant) -> None:
    other = {"id": "mine", "url": "/local/other-card.js", "type": "module"}
    resources = FakeResources([other])
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    paths = bundle.CARD_RESOURCE_PATHS

    await lovelace_resource.async_register(hass, "/vegvarsel_static/vegvarsel-card-loader.js?v=1", paths)
    await lovelace_resource.async_register(hass, "/vegvarsel_static/vegvarsel-card-loader.js?v=1", paths)
    ours = [i for i in resources.items if i["url"].startswith("/vegvarsel_static/")]
    assert len(ours) == 1 and other in resources.items

    # a second, stale entry of ours (added by hand) is cleaned up, the kept one updated
    resources.items.append({"id": "hand", "url": "/vegvarsel_static/vegvarsel-card.js", "type": "js"})
    await lovelace_resource.async_register(hass, "/vegvarsel_static/vegvarsel-card-loader.js?v=2", paths)
    ours = [i for i in resources.items if i["url"].startswith("/vegvarsel_static/")]
    assert ours == [{"id": ours[0]["id"], "url": "/vegvarsel_static/vegvarsel-card-loader.js?v=2", "type": "module"}]
    assert other in resources.items


async def test_resource_yaml_mode_left_alone(hass: HomeAssistant) -> None:
    hass.data["lovelace"] = SimpleNamespace(resources=SimpleNamespace())  # no create/update: YAML mode
    await lovelace_resource.async_register(hass, "/vegvarsel_static/x.js?v=1", bundle.CARD_RESOURCE_PATHS)


async def test_blueprint_updated_only_when_untouched(hass: HomeAssistant, tmp_path: Path) -> None:
    source = tmp_path / "shipped"
    (source / "automation" / DOMAIN).mkdir(parents=True)
    shipped = source / "automation" / DOMAIN / "route_alerts.yaml"
    installed = Path(hass.config.config_dir) / "blueprints" / "automation" / DOMAIN / "route_alerts.yaml"

    shipped.write_text("v1\n", encoding="utf-8")
    await bundle.async_install_blueprints(hass, source)
    assert installed.read_text(encoding="utf-8") == "v1\n"

    shipped.write_text("v2\n", encoding="utf-8")  # a new release: the untouched copy follows
    await bundle.async_install_blueprints(hass, source)
    assert installed.read_text(encoding="utf-8") == "v2\n"

    installed.write_text("mine\n", encoding="utf-8")  # the user edits it
    shipped.write_text("v3\n", encoding="utf-8")
    await bundle.async_install_blueprints(hass, source)
    assert installed.read_text(encoding="utf-8") == "mine\n"
