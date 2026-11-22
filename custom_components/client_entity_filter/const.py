"""Constants for the Client Entity Filter integration."""

DOMAIN = "client_entity_filter"

COMMAND = "subscribe_entities"

CONF_USERS = "users"
CONF_CLIENTS = "clients"
CONF_EXCLUDE_LABELS = "exclude_labels"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_EXCLUDE_DOMAINS = "exclude_domains"
CONF_EXCLUDE_GLOBS = "exclude_globs"
CONF_EXCLUDE_HIDDEN = "exclude_hidden"
CONF_EXCLUDE_CATEGORIES = "exclude_categories"
CONF_KEEP_ENTITIES = "keep_entities"

CLIENTS_ALL = "all"
CLIENTS_APPS = "apps"

# The companion apps sign in with a client ID below this URL
# (https://home-assistant.io/android, https://home-assistant.io/iOS).
APP_CLIENT_ID_PREFIX = "https://home-assistant.io/"

DEFAULT_OPTIONS = {
    CONF_USERS: [],
    CONF_CLIENTS: CLIENTS_ALL,
    CONF_EXCLUDE_LABELS: [],
    CONF_EXCLUDE_ENTITIES: [],
    CONF_EXCLUDE_DOMAINS: [],
    CONF_EXCLUDE_GLOBS: [],
    CONF_EXCLUDE_HIDDEN: False,
    CONF_EXCLUDE_CATEGORIES: [],
    CONF_KEEP_ENTITIES: [],
}
