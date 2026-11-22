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
    CONF_KEEP_DOMAINS,
    CONF_KEEP_ENTITIES,
    CONF_KEEP_GLOBS,
    CONF_MODE,
    CONF_USERS,
    DEFAULT_OPTIONS,
    DOMAIN,
    MODE_DASHBOARDS,
    MODE_RULES,
)
from .dashboards import DashboardIndex
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
        {state.domain for state in hass.states.async_all()}
        | set(options[CONF_EXCLUDE_DOMAINS])
        | set(options[CONF_KEEP_DOMAINS])
    )

    def domain_selector() -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=domains,
                multiple=True,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
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
            vol.Required(CONF_MODE, default=options[CONF_MODE]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[MODE_RULES, MODE_DASHBOARDS],
                    translation_key=CONF_MODE,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            field(CONF_KEEP_DOMAINS): domain_selector(),
            field(CONF_KEEP_GLOBS): selector.TextSelector(
                selector.TextSelectorConfig(multiple=True)
            ),
            field(CONF_KEEP_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            field(CONF_EXCLUDE_LABELS): selector.LabelSelector(
                selector.LabelSelectorConfig(multiple=True)
            ),
            field(CONF_EXCLUDE_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            field(CONF_EXCLUDE_DOMAINS): domain_selector(),
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
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return complete options; a cleared field comes back as missing."""
    return {**DEFAULT_OPTIONS, **user_input}


async def _async_placeholders(hass: HomeAssistant, options: dict[str, Any]) -> dict[str, str]:
    """Count what the options hold back right now."""
    index = DashboardIndex(hass)
    if options[CONF_MODE] == MODE_DASHBOARDS:
        await index.async_refresh()
    client_filter = build_filter(hass, options, index)
    states = hass.states.async_all()
    held_back = (
        0
        if client_filter is None or client_filter.empty
        else sum(1 for state in states if client_filter.excludes(state.entity_id))
    )
    return {"excluded": str(held_back), "total": str(len(states))}


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
            description_placeholders=await _async_placeholders(self.hass, options),
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
            description_placeholders=await _async_placeholders(self.hass, options),
        )
