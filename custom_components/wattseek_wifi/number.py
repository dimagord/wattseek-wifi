"""Number platform for WattSeek Wi-Fi (writable inverter setpoints)."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN
from .coordinator import WattSeekCoordinator
from .settings import MODE_UPS, NUMBERS, ORDER_RULES, OPERATING_MODE_ADDR, UPS_RANGES, NumberSetting


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WattSeekCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    async_add_entities(WattSeekNumber(coordinator, address, n) for n in NUMBERS)


class WattSeekNumber(CoordinatorEntity[WattSeekCoordinator], NumberEntity):
    """A writable numeric inverter setpoint."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: WattSeekCoordinator, address: str, setting: NumberSetting) -> None:
        super().__init__(coordinator)
        self._setting = setting
        self._attr_unique_id = f"{address}_{setting.key}"
        self._attr_name = setting.name
        self._attr_native_min_value = setting.min_value
        self._attr_native_max_value = setting.max_value
        self._attr_native_step = setting.step
        self._attr_native_unit_of_measurement = setting.unit
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"WattSeek Inverter ({address})",
            manufacturer="JSD Solar / WattSeek",
            model="Hybrid Inverter (Wi-Fi local)",
        )

    def _range(self) -> tuple[float, float]:
        data = self.coordinator.data or {}
        if data.get(OPERATING_MODE_ADDR) == MODE_UPS and self._setting.key in UPS_RANGES:
            return UPS_RANGES[self._setting.key]
        return self._setting.min_value, self._setting.max_value

    @property
    def native_min_value(self) -> float:
        return self._range()[0]

    @property
    def native_max_value(self) -> float:
        return self._range()[1]

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get(self._setting.address)
        if raw is None or raw in (0x7FFF, 0xFFFF):
            return None
        return round(raw * self._setting.scale, 2)

    async def async_set_native_value(self, value: float) -> None:
        lo, hi = self._range()
        if not lo <= value <= hi:
            raise ServiceValidationError(
                f"{self._setting.name}: {value} is outside the allowed range {lo}-{hi}"
            )
        data = self.coordinator.data or {}
        by_key = {n.key: n for n in NUMBERS}
        for lower, upper in ORDER_RULES:
            if self._setting.key not in (lower, upper):
                continue
            other = by_key[upper if self._setting.key == lower else lower]
            other_raw = data.get(other.address)
            if other_raw is None:
                raise ServiceValidationError(
                    f"{self._setting.name}: current {other.name} is unknown, refusing to write"
                )
            other_val = other_raw * other.scale
            ok = value < other_val if self._setting.key == lower else value > other_val
            if not ok:
                rel = "below" if self._setting.key == lower else "above"
                raise ServiceValidationError(
                    f"{self._setting.name} must be {rel} {other.name} ({other_val:.1f} {other.unit})"
                )
        raw = round(value / self._setting.scale)
        await self.coordinator.async_write_setting(self._setting.address, raw)
