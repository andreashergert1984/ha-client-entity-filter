"""Tests for sending only what the dashboards use."""

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from .conftest import STATES, subscribe

Setup = Callable[..., Awaitable[MockConfigEntry]]

DASHBOARD = {
    "views": [
        {
            "title": "Home",
            "cards": [
                {"type": "entities", "entities": ["light.kitchen", {"entity": "update.core"}]},
                {
                    "type": "markdown",
                    "content": "Power: {{ states('sensor.power') }} W, see image.png",
                },
                {"type": "custom:some-card", "anything": {"deep": ["sensor.not_there_yet"]}},
            ],
        }
    ]
}


async def save_dashboard(hass: HomeAssistant, client: Any, config: dict[str, Any]) -> None:
    """Save the default dashboard like the dashboard editor does."""
    await client.send_json_auto_id({"type": "lovelace/config/save", "config": config})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()


@pytest.fixture
async def lovelace(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, states: Any) -> Any:
    """Set up dashboards with one saved configuration; return a client."""
    assert await async_setup_component(hass, "lovelace", {})
    client = await hass_ws_client(hass)
    await save_dashboard(hass, client, DASHBOARD)
    return client


async def test_only_dashboard_entities(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, lovelace: Any, setup_filter: Setup
) -> None:
    """Only entities a dashboard mentions are sent, also in the later stream."""
    await setup_filter(mode="dashboards")
    client = await hass_ws_client(hass)
    assert await subscribe(client) == {"light.kitchen", "update.core", "sensor.power"}

    for entity_id in sorted(STATES):
        hass.states.async_set(entity_id, "changed")
    # Mentioned on the dashboard before it existed, and something new that is not.
    hass.states.async_set("sensor.not_there_yet", "1")
    hass.states.async_set("sensor.brand_new", "1")
    hass.states.async_set("update.core", "end")
    await hass.async_block_till_done()
    seen: set[str] = set()
    while True:
        event = (await client.receive_json())["event"]
        seen |= set(event.get("a", {})) | set(event.get("c", {}))
        if event.get("c", {}).get("update.core", {}).get("+", {}).get("s") == "end":
            break
    assert seen == {"light.kitchen", "update.core", "sensor.power", "sensor.not_there_yet"}


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (
            {"keep_domains": ["automation"]},
            {"light.kitchen", "update.core", "sensor.power", "automation.publish"},
        ),
        (
            {"keep_globs": ["sensor.battery1_cell_1*"]},
            {"light.kitchen", "update.core", "sensor.power", "sensor.battery1_cell_1_voltage"},
        ),
        (
            {"keep_entities": ["light.bedroom"]},
            {"light.kitchen", "update.core", "sensor.power", "light.bedroom"},
        ),
        # Rules also hold back what is on a dashboard ...
        ({"exclude_domains": ["update"]}, {"light.kitchen", "sensor.power"}),
        ({"exclude_globs": ["sensor.*"], "exclude_entities": ["light.kitchen"]}, {"update.core"}),
        # ... unless it is kept explicitly.
        (
            {"exclude_domains": ["update"], "keep_entities": ["update.core"]},
            {"light.kitchen", "update.core", "sensor.power"},
        ),
    ],
)
async def test_keep_and_rules(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    lovelace: Any,
    setup_filter: Setup,
    options: dict[str, Any],
    expected: set[str],
) -> None:
    """Things to keep are added, rules take away."""
    await setup_filter(mode="dashboards", **options)
    assert await subscribe(await hass_ws_client(hass)) == expected


async def test_keep_options_do_nothing_in_rules_mode(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, lovelace: Any, setup_filter: Setup
) -> None:
    """Domains and patterns to keep belong to the dashboards mode only."""
    await setup_filter(mode="rules", keep_domains=["light"], exclude_domains=["update"])
    assert await subscribe(await hass_ws_client(hass)) == set(STATES) - {"update.core"}


async def test_area_cards(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    lovelace: Any,
    setup_filter: Setup,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """A card that shows an area gets the entities of that area."""
    entry = await setup_filter(mode="dashboards")
    kitchen = area_registry.async_create("Kitchen")
    cellar = area_registry.async_create("Cellar")
    garage = area_registry.async_create("Garage")
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "meter")}
    )
    device_registry.async_update_device(device.id, area_id=kitchen.id)

    def register(domain: str, object_id: str, area_id: str | None, **kwargs: Any) -> str:
        entity = entity_registry.async_get_or_create(domain, "test", object_id, **kwargs)
        if area_id:
            entity_registry.async_update_entity(entity.entity_id, area_id=area_id)
        hass.states.async_set(entity.entity_id, "1")
        return entity.entity_id

    lamp = register("light", "lamp", kitchen.id)
    temperature = register("sensor", "temp", kitchen.id, original_device_class="temperature")
    power = register("sensor", "kitchen_power", kitchen.id, original_device_class="power")
    via_device = register("switch", "meter_relay", None, device_id=device.id)
    device_power = register(
        "sensor", "meter_power", None, device_id=device.id, original_device_class="power"
    )
    cellar_power = register("sensor", "cellar_power", cellar.id, original_device_class="power")
    cellar_temp = register("sensor", "cellar_temp", cellar.id, original_device_class="temperature")
    register("light", "garage", garage.id)
    setting = register("number", "lamp_brightness_limit", kitchen.id)

    await save_dashboard(
        hass,
        lovelace,
        {
            "views": [
                {
                    "cards": [
                        {"type": "area", "area": kitchen.id},
                        {"type": "area", "area": cellar.id, "sensor_classes": ["power"]},
                    ]
                }
            ]
        },
    )
    got = await subscribe(await hass_ws_client(hass))
    assert got == {lamp, temperature, via_device, cellar_power}
    assert not {power, device_power, cellar_temp, setting} & got


async def test_saving_a_dashboard_applies_to_the_next_connection(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, lovelace: Any, setup_filter: Setup
) -> None:
    """The dashboards are read again when one is saved."""
    await setup_filter(mode="dashboards")
    await save_dashboard(
        hass, lovelace, {"views": [{"cards": [{"type": "entity", "entity": "light.bedroom"}]}]}
    )
    assert await subscribe(await hass_ws_client(hass)) == {"light.bedroom"}


async def test_switching_the_mode_reads_the_dashboards(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, lovelace: Any, setup_filter: Setup
) -> None:
    """Changing from rules to dashboards needs no restart."""
    entry = await setup_filter()
    assert await subscribe(await hass_ws_client(hass)) == set(STATES)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "mode": "dashboards"})
    await hass.async_block_till_done()
    assert await subscribe(await hass_ws_client(hass)) == {
        "light.kitchen",
        "update.core",
        "sensor.power",
    }


async def test_energy_dashboard(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, lovelace: Any, setup_filter: Setup
) -> None:
    """Entities of the energy dashboard are sent, too."""
    preferences = {
        "energy_sources": [{"type": "solar", "stat_energy_from": "sensor.battery1_cell_1_voltage"}]
    }

    async def get_manager(hass: HomeAssistant) -> Any:
        return SimpleNamespace(data=preferences)

    hass.config.components.add("energy")
    with patch("homeassistant.components.energy.data.async_get_manager", get_manager):
        await setup_filter(mode="dashboards")
    assert "sensor.battery1_cell_1_voltage" in await subscribe(await hass_ws_client(hass))


async def test_energy_preferences_that_cannot_be_read_are_skipped(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, lovelace: Any, setup_filter: Setup
) -> None:
    """A failing energy dashboard does not take the dashboards with it."""
    hass.config.components.add("energy")
    with patch(
        "homeassistant.components.energy.data.async_get_manager", side_effect=RuntimeError("boom")
    ):
        await setup_filter(mode="dashboards")
    expected = {"light.kitchen", "update.core", "sensor.power"}
    assert await subscribe(await hass_ws_client(hass)) == expected


async def test_without_any_known_entity_nothing_is_held_back(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, setup_filter: Setup
) -> None:
    """If no dashboard could be read, the client gets everything rather than nothing."""
    await setup_filter(mode="dashboards")
    assert await subscribe(await hass_ws_client(hass)) == set(STATES)


async def test_strategy_dashboard_is_reported(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    lovelace: Any,
    setup_filter: Setup,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A dashboard that builds itself in the frontend can't be covered; say so once."""
    await setup_filter(mode="dashboards")
    for _ in range(2):
        await save_dashboard(
            hass,
            lovelace,
            {
                "strategy": {"type": "original-states"},
                "views": [{"cards": [{"entity": "light.kitchen"}]}],
            },
        )
    assert caplog.text.count("builds itself in the frontend") == 1
    assert await subscribe(await hass_ws_client(hass)) == {"light.kitchen"}
