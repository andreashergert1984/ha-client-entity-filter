"""Build the entity filter a client subscription is limited to."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import fnmatch
from typing import Any

from homeassistant.core import HomeAssistant, callback, split_entity_id
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    APP_CLIENT_ID_PREFIX,
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
)


@dataclass(frozen=True, slots=True)
class ClientFilter:
    """What a filtered client does not get."""

    domains: frozenset[str]
    globs: tuple[str, ...]
    entities: frozenset[str]
    keep: frozenset[str]

    @property
    def empty(self) -> bool:
        """Return if nothing is excluded."""
        return not (self.domains or self.globs or self.entities)

    def excludes(self, entity_id: str) -> bool:
        """Return if the entity is held back from a filtered client."""
        if entity_id in self.keep:
            return False
        if entity_id in self.entities:
            return True
        if split_entity_id(entity_id)[0] in self.domains:
            return True
        return any(fnmatch.fnmatchcase(entity_id, glob) for glob in self.globs)

    def as_message_filter(self) -> dict[str, dict[str, list[str]]]:
        """Return the include and exclude fields for subscribe_entities.

        Home Assistant only honors include entities next to an exclude filter
        when that filter names domains or globs. With an exclude filter of
        entities alone, an include list would turn into "only these", so the
        entities to keep are simply left out of the exclude list instead.
        """
        keep = sorted(self.keep) if (self.domains or self.globs) else []
        return {
            "include": {"domains": [], "entity_globs": [], "entities": keep},
            "exclude": {
                "domains": sorted(self.domains),
                "entity_globs": list(self.globs),
                "entities": sorted(self.entities - self.keep),
            },
        }


@callback
def applies_to_client(
    hass: HomeAssistant,
    options: Mapping[str, Any],
    user_id: str,
    refresh_token_id: str | None,
) -> bool:
    """Return if the subscription of this client is to be filtered."""
    users = options.get(CONF_USERS) or []
    if users and user_id not in users:
        return False
    if options.get(CONF_CLIENTS) != CLIENTS_APPS:
        return True
    if refresh_token_id is None:
        return False
    token = hass.auth.async_get_refresh_token(refresh_token_id)
    client_id = token.client_id if token else None
    return bool(client_id and client_id.startswith(APP_CLIENT_ID_PREFIX))


@callback
def build_filter(hass: HomeAssistant, options: Mapping[str, Any]) -> ClientFilter:
    """Resolve the options into a filter.

    Labels, hidden entities and entity categories are resolved against the
    registries now, so they cover the entities known at this moment. Domains
    and globs are matched by Home Assistant for every state change and also
    cover entities that appear later.
    """
    entities: set[str] = set(options.get(CONF_EXCLUDE_ENTITIES) or [])
    labels = options.get(CONF_EXCLUDE_LABELS) or []
    categories = set(options.get(CONF_EXCLUDE_CATEGORIES) or [])
    hidden = bool(options.get(CONF_EXCLUDE_HIDDEN))

    if labels or categories or hidden:
        ent_reg = er.async_get(hass)
        if labels:
            dev_reg = dr.async_get(hass)
            for label in labels:
                entities.update(
                    entry.entity_id for entry in er.async_entries_for_label(ent_reg, label)
                )
                for device in dr.async_entries_for_label(dev_reg, label):
                    entities.update(
                        entry.entity_id
                        for entry in er.async_entries_for_device(
                            ent_reg, device.id, include_disabled_entities=True
                        )
                    )
        if categories or hidden:
            for entry in ent_reg.entities.values():
                if (hidden and entry.hidden_by is not None) or (
                    entry.entity_category is not None and entry.entity_category.value in categories
                ):
                    entities.add(entry.entity_id)

    return ClientFilter(
        domains=frozenset(options.get(CONF_EXCLUDE_DOMAINS) or []),
        globs=tuple(glob.strip() for glob in options.get(CONF_EXCLUDE_GLOBS) or [] if glob.strip()),
        entities=frozenset(entities),
        keep=frozenset(options.get(CONF_KEEP_ENTITIES) or []),
    )
