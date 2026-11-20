"""Binary sensor platform for WattSeek Wi-Fi (derived status)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN
from .coordinator import WattSeekCoordinator
from .registers import decode, REGISTERS
from .status import ALARM_SPEC, FAULT_SPEC, STATE_ADDR, active_bits

_REG = {r.key: r for r in REGISTERS}


def _value(data: dict[int, int], key: str) -> float | None:
    reg = _REG.get(key)
    if reg is None or data is None:
        return None
    return decode(reg, data)


@dataclass(frozen=True, kw_only=True)
class WSBinary(BinarySensorEntityDescription):
    is_on: Callable[[dict[int, int]], bool | None] = lambda data: None


def _grid_connected(data: dict[int, int]) -> bool | None:
    v = _value(data, "grid_voltage")
    return None if v is None else v > 50

def _pv_producing(data: dict[int, int]) -> bool | None:
    p = _value(data, "pv_total_power")
    if p is None:
        p = _value(data, "pv1_power")
    return None if p is None else p > 10

def _battery_charging(data: dict[int, int]) -> bool | None:
    p = _value(data, "battery_power")
    return None if p is None else p < -10


def _problem(data: dict[int, int]) -> bool | None:
    faults = active_bits(data, FAULT_SPEC)
    alarms = active_bits(data, ALARM_SPEC)
    if faults is None or alarms is None:
        return None
    return bool(faults or alarms) or data.get(STATE_ADDR) == 7


def _fan_stalled(data: dict[int, int]) -> bool | None:
    # Alarm code 1 (0x0048) BIT08 "Fan stalled". Register 0x0321 ("fan status")
    # is non-zero whenever the fan is simply switched off, so it can't be used.
    raw = data.get(0x0048)
    if raw is None:
        return None
    return bool(raw & (1 << 8))


BINARY_SENSORS: tuple[WSBinary, ...] = (
    WSBinary(
        key="inverter_online",
        name="Inverter Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    WSBinary(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on=_problem,
    ),
    WSBinary(
        key="fan_stalled",
        translation_key="fan_stalled",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on=_fan_stalled,
    ),
    WSBinary(
        key="grid_connected",
        name="Grid Connected",
        device_class=BinarySensorDeviceClass.POWER,
        is_on=_grid_connected,
    ),
    WSBinary(
        key="pv_producing",
        name="PV Producing",
        device_class=BinarySensorDeviceClass.POWER,
        is_on=_pv_producing,
    ),
    WSBinary(
        key="battery_charging",
        name="Battery Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on=_battery_charging,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WattSeekCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    async_add_entities(
        WattSeekBinarySensor(coordinator, address, desc) for desc in BINARY_SENSORS
    )


class WattSeekBinarySensor(CoordinatorEntity[WattSeekCoordinator], BinarySensorEntity):
    """A derived on/off status."""

    _attr_has_entity_name = True
    entity_description: WSBinary

    def __init__(self, coordinator: WattSeekCoordinator, address: str, desc: WSBinary) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_unique_id = f"{address}_{desc.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"WattSeek Inverter ({address})",
            manufacturer="JSD Solar / WattSeek",
            model="Hybrid Inverter (Wi-Fi local)",
        )

    @property
    def is_on(self) -> bool | None:
        # Connectivity: reflects whether the last poll reached the inverter.
        if self.entity_description.key == "inverter_online":
            return self.coordinator.last_update_success
        if self.coordinator.data is None:
            return None
        return self.entity_description.is_on(self.coordinator.data)

    @property
    def available(self) -> bool:
        if self.entity_description.key == "inverter_online":
            return True  # the connectivity sensor is always meaningful
        return super().available and self.is_on is not None
