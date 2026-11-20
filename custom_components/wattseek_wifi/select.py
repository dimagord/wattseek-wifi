"""Select platform for WattSeek Wi-Fi (writable inverter settings)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN
from .coordinator import WattSeekCoordinator
from .settings import SELECTS, SelectSetting


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WattSeekCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    async_add_entities(WattSeekSelect(coordinator, address, s) for s in SELECTS)


class WattSeekSelect(CoordinatorEntity[WattSeekCoordinator], SelectEntity):
    """A writable enumerated inverter setting."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: WattSeekCoordinator, address: str, setting: SelectSetting) -> None:
        super().__init__(coordinator)
        self._setting = setting
        self._attr_unique_id = f"{address}_{setting.key}"
        self._attr_name = setting.name
        self._attr_options = list(setting.options.values())
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"WattSeek Inverter ({address})",
            manufacturer="JSD Solar / WattSeek",
            model="Hybrid Inverter (Wi-Fi local)",
        )

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self._setting.label_for(self.coordinator.data.get(self._setting.address))

    async def async_select_option(self, option: str) -> None:
        value = self._setting.value_for(option)
        if value is None:
            return
        await self.coordinator.async_write_setting(self._setting.address, value)
