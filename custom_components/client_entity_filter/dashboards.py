"""Find out which entities the dashboards use.

A dashboard configuration is free-form: cards, also custom ones, name their
entities under many different keys, and templates mention them in text. So the
whole configuration is searched for everything that looks like an entity ID.
Cards that pick their entities by area are covered by keeping the entities of
that area.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

_LOGGER = logging.getLogger(__name__)

_ENTITY_ID = re.compile(r"(?<![a-z0-9_.])([a-z][a-z0-9_]*\.[a-z0-9][a-z0-9_]*)(?![a-z0-9_]*\.)")

# Sensors an area card shows unless it names other classes.
_DEFAULT_SENSOR_CLASSES = frozenset({"temperature", "humidity"})

# What a card shows of an area: things to control and things that alert.
# Sensors are added by device class. Numbers, selects, buttons and the like
# are settings of devices and not shown per area.
_AREA_DOMAINS = frozenset(
    {
        "alarm_control_panel",
        "binary_sensor",
        "camera",
        "climate",
        "cover",
        "fan",
        "humidifier",
        "light",
        "lock",
        "media_player",
        "switch",
        "vacuum",
        "valve",
        "water_heater",
    }
)


@dataclass(frozen=True, slots=True)
class AreaUse:
    """An area a card shows, and the sensor classes it wants from it."""

    area_id: str
    sensor_classes: frozenset[str]


@dataclass(slots=True)
class DashboardIndex:
    """What the dashboards mention, as found at the last refresh."""

    hass: HomeAssistant
    candidates: frozenset[str] = frozenset()
    areas: frozenset[AreaUse] = frozenset()
    strategies: frozenset[str] = frozenset()
    ready: bool = False
    _warned: set[str] = field(default_factory=set)

    async def async_refresh(self) -> None:
        """Read all dashboards and the energy preferences again."""
        candidates: set[str] = set()
        areas: set[AreaUse] = set()
        strategies: set[str] = set()

        for url_path, config in (await self._async_dashboard_configs()).items():
            candidates.update(_ENTITY_ID.findall(json.dumps(config, default=str)))
            _collect(config, areas, strategies, url_path or "default")
        if (energy := await self._async_energy_preferences()) is not None:
            candidates.update(_ENTITY_ID.findall(json.dumps(energy, default=str)))

        self.candidates = frozenset(candidates)
        self.areas = frozenset(areas)
        self.strategies = frozenset(strategies)
        self.ready = True
        for name in sorted(strategies - self._warned):
            self._warned.add(name)
            _LOGGER.warning(
                "Dashboard %s builds itself in the frontend, so the entities it "
                "shows are not known here and may be held back",
                name,
            )

    async def _async_dashboard_configs(self) -> dict[str | None, Any]:
        """Return the configuration of every dashboard that has one."""
        lovelace = self.hass.data.get("lovelace")
        configs: dict[str | None, Any] = {}
        for url_path, dashboard in getattr(lovelace, "dashboards", {}).items():
            try:
                configs[url_path] = await dashboard.async_load(False)
            except Exception as err:  # an unset default dashboard raises
                _LOGGER.debug("Dashboard %s has no configuration: %r", url_path, err)
        return configs

    async def _async_energy_preferences(self) -> Any:
        """Return the energy dashboard preferences, if there are any."""
        if "energy" not in self.hass.config.components:
            return None
        try:
            from homeassistant.components.energy.data import async_get_manager  # noqa: PLC0415

            return (await async_get_manager(self.hass)).data
        except Exception:
            _LOGGER.debug("Could not read the energy preferences", exc_info=True)
            return None

    @callback
    def entity_ids(self) -> frozenset[str]:
        """Return the entities the dashboards use, as far as that can be known."""
        domains = {state.domain for state in self.hass.states.async_all()}
        ent_reg = er.async_get(self.hass)
        domains.update(entry.domain for entry in ent_reg.entities.values())
        used = {candidate for candidate in self.candidates if candidate.split(".")[0] in domains}
        if self.areas:
            used.update(_area_entities(self.hass, ent_reg, self.areas))
        return frozenset(used)


def _collect(node: Any, areas: set[AreaUse], strategies: set[str], name: str) -> None:
    """Walk a dashboard configuration for areas and strategies."""
    if isinstance(node, dict):
        if "strategy" in node:
            strategies.add(name)
        area = node.get("area", node.get("area_id"))
        if isinstance(area, str) and area:
            classes = node.get("sensor_classes")
            areas.add(
                AreaUse(
                    area,
                    frozenset(classes) if isinstance(classes, list) else _DEFAULT_SENSOR_CLASSES,
                )
            )
        for value in node.values():
            _collect(value, areas, strategies, name)
    elif isinstance(node, list):
        for value in node:
            _collect(value, areas, strategies, name)


def _area_entities(
    hass: HomeAssistant, ent_reg: er.EntityRegistry, areas: Iterable[AreaUse]
) -> set[str]:
    """Return what cards show of their areas.

    Kept are the entities of the area a card can control or alert about, and
    of the sensors only the classes the card asks for. Sensors are where the
    many fast-changing values are.
    """
    dev_reg = dr.async_get(hass)
    sensor_classes: dict[str, set[str]] = {}
    for use in areas:
        sensor_classes.setdefault(use.area_id, set()).update(use.sensor_classes)

    used: set[str] = set()
    for entry in ent_reg.entities.values():
        area_id = entry.area_id
        if area_id is None and entry.device_id is not None:
            device = dev_reg.async_get(entry.device_id)
            area_id = device.area_id if device else None
        if area_id not in sensor_classes:
            continue
        if entry.domain == "sensor":
            device_class = entry.device_class or entry.original_device_class
            if device_class not in sensor_classes[area_id]:
                continue
        elif entry.domain not in _AREA_DOMAINS:
            continue
        used.add(entry.entity_id)
    return used
