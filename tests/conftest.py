"""Fixtures for the Client Entity Filter tests."""

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.client_entity_filter.const import DEFAULT_OPTIONS, DOMAIN

STATES = {
    "light.kitchen": "on",
    "light.bedroom": "off",
    "sensor.power": "120",
    "sensor.battery1_cell_1_voltage": "3.31",
    "sensor.battery1_cell_2_voltage": "3.32",
    "update.core": "off",
    "automation.publish": "on",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration under test."""


@pytest.fixture
async def states(hass: HomeAssistant) -> dict[str, str]:
    """Put a few states into the state machine."""
    assert await async_setup_component(hass, "websocket_api", {})
    for entity_id, state in STATES.items():
        hass.states.async_set(entity_id, state)
    return STATES


@pytest.fixture
def setup_filter(
    hass: HomeAssistant, states: dict[str, str]
) -> Callable[..., Awaitable[MockConfigEntry]]:
    """Return a function that sets the integration up with options."""

    async def _setup(**options: Any) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN, title="Client Entity Filter", options={**DEFAULT_OPTIONS, **options}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


async def subscribe(client: Any, **fields: Any) -> set[str]:
    """Subscribe and return the entity IDs of the initial states."""
    await client.send_json_auto_id({"type": "subscribe_entities", **fields})
    result = await client.receive_json()
    assert result["success"], result
    event = await client.receive_json()
    assert event["type"] == "event"
    return set(event["event"]["a"])
