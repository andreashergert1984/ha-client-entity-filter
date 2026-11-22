"""Tests for wrapping the subscribe_entities command."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.client_entity_filter.const import DOMAIN

from .conftest import STATES, subscribe

ALL = set(STATES)
CELLS = {"sensor.battery1_cell_1_voltage", "sensor.battery1_cell_2_voltage"}
Setup = Callable[..., Awaitable[MockConfigEntry]]


async def test_without_rules_nothing_is_held_back(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, setup_filter: Setup
) -> None:
    """An entry without rules leaves the subscription alone."""
    await setup_filter()
    assert await subscribe(await hass_ws_client(hass)) == ALL


@pytest.mark.parametrize(
    ("options", "held_back"),
    [
        ({"exclude_domains": ["update", "automation"]}, {"update.core", "automation.publish"}),
        ({"exclude_globs": ["sensor.battery*_cell_*"]}, CELLS),
        ({"exclude_globs": ["  sensor.battery*_cell_*  ", ""]}, CELLS),
        ({"exclude_entities": ["sensor.power"]}, {"sensor.power"}),
        (
            {"exclude_domains": ["light"], "exclude_entities": ["sensor.power"]},
            {"light.kitchen", "light.bedroom", "sensor.power"},
        ),
        # An entity to keep wins over a domain and over a pattern ...
        ({"exclude_domains": ["light"], "keep_entities": ["light.kitchen"]}, {"light.bedroom"}),
        (
            {
                "exclude_globs": ["sensor.battery*"],
                "keep_entities": ["sensor.battery1_cell_1_voltage"],
            },
            {"sensor.battery1_cell_2_voltage"},
        ),
        # ... and over a single entity, without turning into "only these".
        (
            {
                "exclude_entities": ["sensor.power", "light.kitchen"],
                "keep_entities": ["light.kitchen"],
            },
            {"sensor.power"},
        ),
        ({"keep_entities": ["light.kitchen"]}, set()),
    ],
)
async def test_rules(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    setup_filter: Setup,
    options: dict[str, Any],
    held_back: set[str],
) -> None:
    """Rules hold back the initial states and the later changes."""
    await setup_filter(**options)
    client = await hass_ws_client(hass)
    assert await subscribe(client) == ALL - held_back

    # Change every entity, then one more as a marker for the end.
    for entity_id in sorted(ALL):
        hass.states.async_set(entity_id, "changed")
    hass.states.async_set("sun.marker", "end")
    await hass.async_block_till_done()
    changed: set[str] = set()
    while True:
        event = (await client.receive_json())["event"]
        if "sun.marker" in event.get("a", {}):
            break
        changed |= set(event.get("c", {}))
    assert changed == ALL - held_back

    # An entity that appears later is matched by domains and patterns, too.
    hass.states.async_set("update.addon", "on")
    hass.states.async_set("sensor.battery2_cell_1_voltage", "3.3")
    hass.states.async_set("sun.marker2", "end")
    await hass.async_block_till_done()
    added: set[str] = set()
    while True:
        event = (await client.receive_json())["event"]
        added |= set(event.get("a", {}))
        if "sun.marker2" in added:
            break
    expected = {"sun.marker2"}
    if "update" not in options.get("exclude_domains", []):
        expected.add("update.addon")
    if not options.get("exclude_globs"):
        expected.add("sensor.battery2_cell_1_voltage")
    assert added == expected


async def test_labels_hidden_and_categories(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    setup_filter: Setup,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    label_registry: lr.LabelRegistry,
) -> None:
    """Labels, hidden entities and categories are resolved from the registries."""
    entry = await setup_filter()
    label = label_registry.async_create("Under the hood")
    device_label = label_registry.async_create("Noisy device")
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "battery")}
    )
    device_registry.async_update_device(device.id, labels={device_label.label_id})

    def register(object_id: str, **kwargs: Any) -> str:
        entity = entity_registry.async_get_or_create("sensor", "test", object_id, **kwargs)
        hass.states.async_set(entity.entity_id, "1")
        return entity.entity_id

    labelled = register("labelled")
    entity_registry.async_update_entity(labelled, labels={label.label_id})
    on_device = register("on_device", device_id=device.id)
    hidden = register("hidden", hidden_by=er.RegistryEntryHider.USER)
    diagnostic = register("diagnostic", entity_category=EntityCategory.DIAGNOSTIC)
    config = register("config", entity_category=EntityCategory.CONFIG)
    plain = register("plain")
    everything = ALL | {labelled, on_device, hidden, diagnostic, config, plain}

    async def held_back(**options: Any) -> set[str]:
        hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
        return everything - await subscribe(await hass_ws_client(hass))

    assert await held_back() == set()
    assert await held_back(exclude_labels=[label.label_id]) == {labelled}
    assert await held_back(exclude_labels=[device_label.label_id]) == {on_device}
    assert await held_back(exclude_labels=[], exclude_hidden=True) == {hidden}
    assert await held_back(exclude_hidden=False, exclude_categories=["diagnostic"]) == {diagnostic}
    assert await held_back(exclude_categories=["diagnostic", "config"], keep_entities=[config]) == {
        diagnostic
    }


async def test_only_the_chosen_users(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: Any,
    setup_filter: Setup,
) -> None:
    """Other users keep the full subscription."""
    entry = await setup_filter(exclude_domains=["light"], users=["someone-else"])
    assert await subscribe(await hass_ws_client(hass)) == ALL

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "users": [hass_admin_user.id]}
    )
    assert await subscribe(await hass_ws_client(hass)) == ALL - {"light.kitchen", "light.bedroom"}


@pytest.mark.parametrize(
    ("client_id", "filtered"),
    [
        ("https://home-assistant.io/android", True),
        ("https://home-assistant.io/iOS", True),
        ("https://my-home.example.com/", False),
        (None, False),
    ],
)
async def test_only_the_mobile_apps(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: Any,
    setup_filter: Setup,
    client_id: str | None,
    filtered: bool,
) -> None:
    """The mobile apps are told apart by the client ID of their login."""
    await setup_filter(exclude_domains=["light"], clients="apps")
    if client_id is None:
        token = await hass.auth.async_create_refresh_token(
            hass_admin_user,
            client_name="A script",
            token_type="long_lived_access_token",
        )
    else:
        token = await hass.auth.async_create_refresh_token(hass_admin_user, client_id)
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    expected = ALL - {"light.kitchen", "light.bedroom"} if filtered else ALL
    assert await subscribe(client) == expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"entity_ids": ["light.kitchen", "sensor.power"]}, {"light.kitchen", "sensor.power"}),
        ({"include": {"domains": ["light"]}}, {"light.kitchen", "light.bedroom"}),
        ({"exclude": {"domains": ["sensor"]}}, ALL - CELLS - {"sensor.power"}),
    ],
)
async def test_client_with_its_own_filter_is_left_alone(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    setup_filter: Setup,
    fields: dict[str, Any],
    expected: set[str],
) -> None:
    """A client that limits its subscription gets exactly what it asked for."""
    await setup_filter(exclude_domains=["light"])
    assert await subscribe(await hass_ws_client(hass), **fields) == expected


async def test_failure_does_not_block_the_client(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    setup_filter: Setup,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the filter can't be built, the client gets everything."""
    await setup_filter(exclude_domains=["light"])
    with patch(
        "custom_components.client_entity_filter.build_filter", side_effect=RuntimeError("boom")
    ):
        assert await subscribe(await hass_ws_client(hass)) == ALL
        assert await subscribe(await hass_ws_client(hass)) == ALL
    assert caplog.text.count("Could not build the entity filter") == 1


async def test_unload_puts_the_command_back(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, setup_filter: Setup
) -> None:
    """Unloading restores the command of Home Assistant."""
    handlers = hass.data[websocket_api.DOMAIN]
    original = handlers["subscribe_entities"]
    entry = await setup_filter(exclude_domains=["light"])
    assert handlers["subscribe_entities"] != original
    assert handlers["subscribe_entities"][1] is original[1]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert handlers["subscribe_entities"] == original
    assert await subscribe(await hass_ws_client(hass)) == ALL


async def test_unload_leaves_a_foreign_command_alone(
    hass: HomeAssistant, setup_filter: Setup, caplog: pytest.LogCaptureFixture
) -> None:
    """A command registered by something else after setup is not overwritten."""
    handlers = hass.data[websocket_api.DOMAIN]
    entry = await setup_filter()
    foreign = (lambda hass, connection, msg: None, handlers["subscribe_entities"][1])
    handlers["subscribe_entities"] = foreign

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert handlers["subscribe_entities"] is foreign
    assert "leaving it as it is" in caplog.text


async def test_setup_fails_without_filter_support(
    hass: HomeAssistant, states: dict[str, str]
) -> None:
    """A Home Assistant whose command takes no filter is reported, not wrapped."""
    handlers = hass.data[websocket_api.DOMAIN]
    handler, _ = original = handlers["subscribe_entities"]

    def strict_schema(msg: dict[str, Any]) -> dict[str, Any]:
        if "exclude" in msg:
            raise ValueError("extra keys not allowed")
        return msg

    handlers["subscribe_entities"] = (handler, strict_schema)
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert handlers["subscribe_entities"][0] is handler
    handlers["subscribe_entities"] = original
