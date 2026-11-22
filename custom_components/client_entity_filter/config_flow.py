"""Config flow for the Client Entity Filter integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

try:  # Home Assistant moved its schemas from voluptuous to probatio.
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant versions
    import voluptuous as vol

from .const import (
    CLIENTS_ALL,
    CLIENTS_APPS,
    CONF_CLIENTS,
    CONF_EXCLUDE_CATEGORIES,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_GLOBS,
    CONF_EXCLUDE_HIDDEN,
    CONF_EXCLUDE_LABELS,
    CONF_KEEP_ENTITIES,
    CONF_USERS,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .filter import build_filter

TITLE = "Client Entity Filter"


async def _async_schema(hass: HomeAssistant, options: dict[str, Any]) -> vol.Schema:
    """Build the form, filled with the current options."""
    users = [
        selector.SelectOptionDict(value=user.id, label=user.name or user.id)
        for user in await hass.auth.async_get_users()
        if not user.system_generated and user.is_active
    ]
    domains = sorted(
        {state.domain for state in hass.states.async_all()} | set(options[CONF_EXCLUDE_DOMAINS])
    )

    def field(key: str) -> vol.Optional:
        return vol.Optional(key, description={"suggested_value": options[key]})

    return vol.Schema(
        {
            field(CONF_USERS): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=users,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_CLIENTS, default=options[CONF_CLIENTS]): (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[CLIENTS_ALL, CLIENTS_APPS],
                        translation_key=CONF_CLIENTS,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            ),
            field(CONF_EXCLUDE_LABELS): selector.LabelSelector(
                selector.LabelSelectorConfig(multiple=True)
            ),
            field(CONF_EXCLUDE_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            field(CONF_EXCLUDE_DOMAINS): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=domains,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            field(CONF_EXCLUDE_GLOBS): selector.TextSelector(
                selector.TextSelectorConfig(multiple=True)
            ),
            vol.Required(
                CONF_EXCLUDE_HIDDEN, default=options[CONF_EXCLUDE_HIDDEN]
            ): selector.BooleanSelector(),
            field(CONF_EXCLUDE_CATEGORIES): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["diagnostic", "config"],
                    multiple=True,
                    translation_key=CONF_EXCLUDE_CATEGORIES,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            field(CONF_KEEP_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return complete options; a cleared field comes back as missing."""
    return {**DEFAULT_OPTIONS, **user_input}


@callback
def _placeholders(hass: HomeAssistant, options: dict[str, Any]) -> dict[str, str]:
    """Count what the options hold back right now."""
    client_filter = build_filter(hass, options)
    states = hass.states.async_all()
    return {
        "excluded": str(sum(1 for state in states if client_filter.excludes(state.entity_id))),
        "total": str(len(states)),
    }


class ClientEntityFilterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the one filter of this Home Assistant."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the filter."""
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=_normalize(user_input))
        options = dict(DEFAULT_OPTIONS)
        return self.async_show_form(
            step_id="user",
            data_schema=await _async_schema(self.hass, options),
            description_placeholders=_placeholders(self.hass, options),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ClientEntityFilterOptionsFlow()


class ClientEntityFilterOptionsFlow(OptionsFlow):
    """Change the filter."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the filter."""
        if user_input is not None:
            return self.async_create_entry(data=_normalize(user_input))
        options = {**DEFAULT_OPTIONS, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=await _async_schema(self.hass, options),
            description_placeholders=_placeholders(self.hass, options),
        )
