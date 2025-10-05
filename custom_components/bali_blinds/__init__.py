"""The Bali Blinds integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BaliAPI, BaliAuthError, BaliConnectionError
from .const import CONF_GATEWAY_ID
from .coordinator import BaliBlindCoordinator
from .models import BaliBlindData

PLATFORMS: list[Platform] = [Platform.COVER, Platform.SENSOR]

type BaliBlindConfigEntry = ConfigEntry[BaliBlindData]


async def async_setup_entry(hass: HomeAssistant, entry: BaliBlindConfigEntry) -> bool:
    """Set up Bali Blinds from a config entry."""
    session = async_get_clientsession(hass)

    api = BaliAPI(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=session,
        gateway_id=entry.data.get(CONF_GATEWAY_ID),
    )

    try:
        await api.authenticate()
    except BaliAuthError as err:
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except BaliConnectionError as err:
        raise ConfigEntryNotReady(f"Failed to connect: {err}") from err

    # Connect WebSocket for real-time communication
    try:
        await api.connect_websocket()
    except BaliConnectionError as err:
        raise ConfigEntryNotReady(f"Failed to connect WebSocket: {err}") from err

    gateway_id = entry.data.get(CONF_GATEWAY_ID, "auto")
    if api._auth_data:
        gateway_id = api._auth_data.device_id

    coordinator = BaliBlindCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = BaliBlindData(
        api=api,
        gateway_id=gateway_id,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: BaliBlindConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Disconnect WebSocket
        await entry.runtime_data.api.disconnect_websocket()

    return unload_ok
