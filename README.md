# Client Entity Filter for Home Assistant

Hold entities back from the state stream that dashboards and apps receive.

The Home Assistant frontend subscribes to every entity of your system, whatever
the dashboard shows. On a large installation a phone or a wall tablet then
receives and processes thousands of states at startup and a constant stream of
changes for entities it never displays.

Home Assistant itself can limit that subscription. The frontend just never asks
for it. This integration adds the filter on the server, for the users and
clients you choose. The entities themselves are not touched: automations,
history, statistics, voice assistants and everything else keep working as
before. Filtered clients simply do not receive the states of the entities you
hold back.

## Is this for you?

It helps when your system has many entities that change often but are only
needed "under the hood": cell voltages of a battery, energy counters, raw
values of an inverter, helper automations, diagnostic sensors.

As an example, on the installation this was written for (about 4,200 entities)
a connected client received 78 state changes per second, and 64 % of them came
from entities that are on no dashboard at all.

If your system is small or your devices are fast, you will not notice a
difference.

## What a filtered client sees

An entity that is held back does not exist for that client:

- A card that uses it shows "Entity not found".
- It has no state in the developer tools and in the more-info dialog.
- History graphs still work, because history comes from the recorder.

So only hold back what you do not show on that client, and keep one client
unfiltered for administration (see "Filtered clients" below).

## Installation

With [HACS](https://hacs.xyz): add this repository as a custom repository of
type "Integration", install "Client Entity Filter" and restart Home Assistant.

Manually: copy `custom_components/client_entity_filter` into the
`custom_components` folder of your configuration and restart Home Assistant.

Then go to Settings > Devices & services > Add integration and choose
"Client Entity Filter".

## Configuration

Everything is set in the user interface and can be changed later with
"Configure". A change applies the next time a client connects, for example
after reloading the page or restarting the app.

| Setting | Meaning |
| --- | --- |
| Filtered users | Only connections of these users are filtered. Empty: every user. |
| Filtered clients | All clients, or only the Home Assistant mobile apps. With the second choice the browser on your computer stays unfiltered while the same user is filtered on the phone. |
| Labels to hold back | Entities with one of these labels, and all entities of devices with one of these labels. Create a label like "Under the hood" and assign it wherever you like. |
| Entities to hold back | Single entities. |
| Domains to hold back | All entities of a domain, for example `update`. |
| Entity ID patterns to hold back | Patterns with `*` as a wildcard, for example `sensor.battery*_cell_*`. |
| Hold back hidden entities | Entities that are hidden in their settings. |
| Entity categories to hold back | Diagnostic and/or configuration entities. |
| Entities to keep anyway | Always sent, even if a rule above matches them. |

The "Configure" dialog shows how many of your entities the saved settings hold
back.

Domains and patterns also cover entities that are created later. Labels, hidden
entities and categories are looked up when a client connects, so a newly
labelled entity is held back from the next connection on.

## How it works

The frontend follows states with the `subscribe_entities` WebSocket command.
That command accepts an `include` and `exclude` filter. This integration wraps
the command: when a client that is to be filtered subscribes without a filter
of its own, the configured exclude filter is added, and the request is handed
to the unchanged command of Home Assistant. Initial states and later changes
are then filtered by Home Assistant itself.

- A client that sends its own filter gets exactly what it asked for.
- If the filter cannot be built for any reason, the client gets everything.
  A dashboard is never blocked by this integration.
- Removing the integration puts the original command back.

## Limitations

- This wraps a command of Home Assistant that is not meant to be wrapped. It
  uses only the public registration of WebSocket commands and the documented
  filter fields, but a future Home Assistant release can still break it. If
  the command no longer takes a filter, the integration refuses to set up and
  says so, and nothing is filtered.
- Only `subscribe_entities` is filtered. Other ways to read states (the REST
  API, `get_states`, templates, history) are not. This is a way to save
  bandwidth and client CPU, not a way to hide entities from a user. Do not use
  it as access control.
- The entity registry is still sent in full, so held-back entities are listed
  in the settings, just without a state.
- Tested with Home Assistant 2026.10 and 2026.11.

## Development

```
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest
```

## License

MIT
