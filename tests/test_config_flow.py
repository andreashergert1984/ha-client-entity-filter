"""Tests for the config and options flow."""

from collections.abc import Awaitable, Callable

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.client_entity_filter.const import DEFAULT_OPTIONS, DOMAIN

from .conftest import STATES, subscribe

Setup = Callable[..., Awaitable[MockConfigEntry]]


async def test_user_flow(hass: HomeAssistant, states: dict[str, str]) -> None:
    """The user flow creates the entry with complete options."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"clients": "apps", "exclude_hidden": True, "exclude_domains": ["update", "my_domain"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {}
    assert result["options"] == {
        **DEFAULT_OPTIONS,
        "clients": "apps",
        "exclude_hidden": True,
        "exclude_domains": ["update", "my_domain"],
    }


async def test_only_one_entry(hass: HomeAssistant, setup_filter: Setup) -> None:
    """A second entry is refused."""
    await setup_filter()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, setup_filter: Setup
) -> None:
    """Options show what is held back and apply to the next subscription."""
    entry = await setup_filter(exclude_domains=["light"], exclude_globs=["sensor.battery*"])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"excluded": "4", "total": str(len(STATES))}

    # Clearing a field leaves it out of the input; it must not keep its old value.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"clients": "all", "exclude_hidden": False, "exclude_domains": ["update"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**DEFAULT_OPTIONS, "exclude_domains": ["update"]}
    assert await subscribe(await hass_ws_client(hass)) == set(STATES) - {"update.core"}
