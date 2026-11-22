"""Client Entity Filter: hold entities back from the frontend's state stream.

The frontend follows states with the ``subscribe_entities`` WebSocket command
and asks for every entity. Home Assistant can limit that subscription, but the
frontend never asks it to. This integration wraps the command and adds an
exclude filter for the clients it is set up for. Everything else is left to
the command of Home Assistant itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError

from .const import COMMAND
from .filter import applies_to_client, build_filter

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeData:
    """What is needed to put the original command back."""

    original: tuple[Any, Any]
    wrapper: Any


type ClientEntityFilterConfigEntry = ConfigEntry[RuntimeData]


def _client_filters_itself(msg: dict[str, Any]) -> bool:
    """Return if the client already limits the subscription."""
    if msg.get("entity_ids"):
        return True
    return any(values for key in ("include", "exclude") for values in (msg.get(key) or {}).values())


async def async_setup_entry(hass: HomeAssistant, entry: ClientEntityFilterConfigEntry) -> bool:
    """Wrap the subscribe_entities command."""
    handlers: dict[str, tuple[Any, Any]] = hass.data[websocket_api.DOMAIN]
    if COMMAND not in handlers:
        raise ConfigEntryError(f"The {COMMAND} WebSocket command was not found")
    original_handler, schema = original = handlers[COMMAND]

    # The filter fields have to be part of the command, or the wrapped
    # command would reject what this integration adds.
    try:
        schema({"id": 1, "type": COMMAND, "exclude": {"domains": ["sensor"]}})
    except Exception as err:
        raise ConfigEntryError(
            f"This Home Assistant version has no entity filter on {COMMAND}"
        ) from err

    failed_before = False

    @callback
    def handle_subscribe_entities(
        hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
    ) -> None:
        """Add the filter, then hand over to the command of Home Assistant.

        The options are read for every subscription, so a change applies to
        the next connection without a reload.
        """
        nonlocal failed_before
        try:
            if not _client_filters_itself(msg) and applies_to_client(
                hass, entry.options, connection.user.id, connection.refresh_token_id
            ):
                client_filter = build_filter(hass, entry.options)
                if not client_filter.empty:
                    msg = {**msg, **client_filter.as_message_filter()}
        except Exception:
            # Never keep a client from its states: without a filter the
            # frontend works as it does without this integration.
            if not failed_before:
                failed_before = True
                _LOGGER.exception("Could not build the entity filter; not filtering")
        original_handler(hass, connection, msg)

    websocket_api.async_register_command(hass, COMMAND, handle_subscribe_entities, schema)
    entry.runtime_data = RuntimeData(original, handle_subscribe_entities)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClientEntityFilterConfigEntry) -> bool:
    """Put the original command back."""
    handlers: dict[str, tuple[Any, Any]] = hass.data[websocket_api.DOMAIN]
    current = handlers.get(COMMAND)
    if current is not None and current[0] is entry.runtime_data.wrapper:
        handlers[COMMAND] = entry.runtime_data.original
    else:
        _LOGGER.warning(
            "The %s command was replaced by something else; leaving it as it is",
            COMMAND,
        )
    return True
