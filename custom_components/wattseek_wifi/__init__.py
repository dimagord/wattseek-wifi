"""The WattSeek Wi-Fi integration (local MQTT, no cloud)."""
from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_ADDRESS, CONF_INVERTER_ID, CONF_PRODUCT_KEY, DOMAIN
from .coordinator import WattSeekCoordinator
from .device import WattSeekWifiDevice

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WattSeek Wi-Fi from a config entry."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT integration is not available")

    device = WattSeekWifiDevice(
        hass,
        entry.data[CONF_PRODUCT_KEY],
        entry.data[CONF_ADDRESS],
        entry.data[CONF_INVERTER_ID],
    )
    # Subscribe first: the stick will not answer passthrough reads until its
    # registration/time-sync requests have been answered, so we must keep
    # listening even while the first poll fails.
    await device.async_start()
    entry.async_on_unload(device.async_stop)

    coordinator = WattSeekCoordinator(hass, entry, device)
    await coordinator.async_refresh()  # never raises; entities wait for data

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options (e.g. update interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
