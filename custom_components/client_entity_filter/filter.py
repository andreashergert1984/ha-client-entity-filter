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
    CONF_KEEP_DOMAINS,
    CONF_KEEP_ENTITIES,
    CONF_KEEP_GLOBS,
    CONF_MODE,
    CONF_USERS,
    MODE_DASHBOARDS,
)
from .dashboards import DashboardIndex


def _matches(entity_id: str, globs: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(entity_id, glob) for glob in globs)


def _globs(values: Any) -> tuple[str, ...]:
    return tuple(glob.strip() for glob in values or [] if glob.strip())


@dataclass(frozen=True, slots=True)
class ClientFilter:
    """What a filtered client gets and does not get.

    With ``only`` unset, a client gets everything but what the rules hold back.
    With ``only`` set, it gets these entities (less what the rules hold back)
    plus the domains and patterns to keep, and nothing else.
    """

    domains: frozenset[str]
    globs: tuple[str, ...]
    entities: frozenset[str]
    keep: frozenset[str]
    only: frozenset[str] | None = None
    keep_domains: frozenset[str] = frozenset()
    keep_globs: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        """Return if the filter would not limit anything it can be sure about."""
        if self.only is None:
            return not (self.domains or self.globs or self.entities)
        # Without a single known entity the dashboards could not be read;
        # sending nothing at all would be worse than not filtering.
        return not (self.only or self.keep or self.keep_domains or self.keep_globs)

    def _held_back_by_rule(self, entity_id: str) -> bool:
        return (
            entity_id in self.entities
            or split_entity_id(entity_id)[0] in self.domains
            or _matches(entity_id, self.globs)
        )

    def excludes(self, entity_id: str) -> bool:
        """Return if the entity is held back from a filtered client."""
        if entity_id in self.keep:
            return False
        if self.only is None:
            return self._held_back_by_rule(entity_id)
        if split_entity_id(entity_id)[0] in self.keep_domains or _matches(
            entity_id, self.keep_globs
        ):
            return False
        return entity_id not in self.only or self._held_back_by_rule(entity_id)

    def as_message_filter(self) -> dict[str, dict[str, list[str]]]:
        """Return the include and exclude fields for subscribe_entities.

        Home Assistant only honors include entities next to an exclude filter
        when that filter names domains or globs. With an exclude filter of
        entities alone, an include list would turn into "only these", so the
        entities to keep are simply left out of the exclude list instead.

        With ``only`` set, the same "only these" behavior is what is wanted:
        an include filter without any exclude filter.
        """
        nothing: dict[str, list[str]] = {"domains": [], "entity_globs": [], "entities": []}
        if self.only is not None:
            entities = {
                entity_id for entity_id in self.only if not self._held_back_by_rule(entity_id)
            }
            return {
                "include": {
                    "domains": sorted(self.keep_domains),
                    "entity_globs": list(self.keep_globs),
                    "entities": sorted(entities | self.keep),
                },
                "exclude": nothing,
            }
        keep = sorted(self.keep) if (self.domains or self.globs) else []
        return {
            "include": {**nothing, "entities": keep},
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
def build_filter(
    hass: HomeAssistant, options: Mapping[str, Any], index: DashboardIndex | None = None
) -> ClientFilter | None:
    """Resolve the options into a filter.

    Labels, hidden entities and entity categories are resolved against the
    registries now, so they cover the entities known at this moment. Domains
    and globs are matched by Home Assistant for every state change and also
    cover entities that appear later.

    Returns None while the dashboards are needed but have not been read yet.
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

    only: frozenset[str] | None = None
    if options.get(CONF_MODE) == MODE_DASHBOARDS:
        if index is None or not index.ready:
            return None
        only = index.entity_ids()

    return ClientFilter(
        domains=frozenset(options.get(CONF_EXCLUDE_DOMAINS) or []),
        globs=_globs(options.get(CONF_EXCLUDE_GLOBS)),
        entities=frozenset(entities),
        keep=frozenset(options.get(CONF_KEEP_ENTITIES) or []),
        only=only,
        keep_domains=frozenset(options.get(CONF_KEEP_DOMAINS) or [])
        if only is not None
        else frozenset(),
        keep_globs=_globs(options.get(CONF_KEEP_GLOBS)) if only is not None else (),
    )
