"""The FortiManager integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FortiManagerAuthError, FortiManagerClient, FortiManagerConnectionError
from .const import CLIENT, CONF_VERIFY_SSL, COORDINATOR, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FortiManager from a config entry."""
    client = FortiManagerClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
    )

    try:
        await client.login()
    except FortiManagerAuthError as err:
        raise ConfigEntryAuthFailed from err
    except FortiManagerConnectionError as err:
        raise ConfigEntryNotReady from err

    async def _async_update_data() -> tuple[list[dict], list[dict]]:
        """Return (devices, available_firmware) tuple.

        available_firmware may be empty on older FMG versions — that's fine,
        the update entities will simply report no update known.
        """
        try:
            devices = await client.get_devices()
            firmware = await client.get_available_firmware()
            return devices, firmware
        except FortiManagerAuthError as err:
            raise ConfigEntryAuthFailed from err
        except FortiManagerConnectionError as err:
            raise UpdateFailed(f"Error communicating with FortiManager: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=_async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        COORDINATOR: coordinator,
        CLIENT: client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        await entry_data[CLIENT].close()
    return unload_ok
