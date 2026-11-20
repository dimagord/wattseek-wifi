"""Remote power on/off switch for WattSeek Wi-Fi (register 0x4123).

0x4123 "Remote power on/off enable": 0 = remote control disabled,
1 = remote control enabled and powered on, 2 = remote control enabled and
powered off. Turning it off stops the inverter output: anything fed from the
inverter loses power. Subject to the 'Allow changing inverter settings' option.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN
from .coordinator import WattSeekCoordinator

REMOTE_POWER_ADDR = 0x4123
_ON, _OFF = 1, 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WattSeekCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WattSeekRemotePower(coordinator, entry.data[CONF_ADDRESS])])


class WattSeekRemotePower(CoordinatorEntity[WattSeekCoordinator], SwitchEntity):
    """Inverter output on/off via the remote power command."""

    _attr_has_entity_name = True
    _attr_translation_key = "remote_power"
    _attr_icon = "mdi:power"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: WattSeekCoordinator, address: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_remote_power"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"WattSeek Inverter ({address})",
            manufacturer="JSD Solar / WattSeek",
            model="Hybrid Inverter (Wi-Fi local)",
        )

    @property
    def is_on(self) -> bool | None:
        raw = (self.coordinator.data or {}).get(REMOTE_POWER_ADDR)
        if raw is None:
            return None
        return raw != _OFF  # 0 (remote disabled) still means the unit is running

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        raw = (self.coordinator.data or {}).get(REMOTE_POWER_ADDR)
        return {"remote_control_enabled": raw in (_ON, _OFF) if raw is not None else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_setting(REMOTE_POWER_ADDR, _ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_setting(REMOTE_POWER_ADDR, _OFF)
