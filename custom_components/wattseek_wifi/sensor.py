"""Sensor platform for WattSeek Wi-Fi."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN
from .coordinator import WattSeekCoordinator
from .registers import REGISTERS, Reg, decode
from .status import CHARGE_STAGE_ADDR, CHARGE_STAGE_ICONS, CHARGE_STAGES, ALARM_SPEC, FAULT_SPEC, STATE_ADDR, STATE_ICONS, STATES, active_bits, localize


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WattSeekCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    entities: list[SensorEntity] = [WattSeekSensor(coordinator, address, reg) for reg in REGISTERS]
    entities += [
        WattSeekStatusSensor(coordinator, address),
        WattSeekChargeStageSensor(coordinator, address),
        WattSeekBitsSensor(coordinator, address, "active_faults", "faults", FAULT_SPEC, "mdi:alert-octagon"),
        WattSeekBitsSensor(coordinator, address, "active_alarms", "alarms", ALARM_SPEC, "mdi:alert"),
    ]
    entities += [WattSeekTimingSensor(coordinator, address, d) for d in TIMING_SENSORS]
    entities.append(WattSeekRequestErrorsSensor(coordinator, address))
    entities += [WattSeekStickSensor(coordinator, address, d) for d in STICK_SENSORS]
    async_add_entities(entities)


def _device_info(address: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, address)},
        name=f"WattSeek Inverter ({address})",
        manufacturer="JSD Solar / WattSeek",
        model="Hybrid Inverter (Wi-Fi local)",
    )


class WattSeekStatusSensor(CoordinatorEntity[WattSeekCoordinator], SensorEntity):
    """Human-readable inverter state machine."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATES.values())

    def __init__(self, coordinator: WattSeekCoordinator, address: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_status"
        self._attr_device_info = _device_info(address)

    @property
    def native_value(self) -> str | None:
        raw = (self.coordinator.data or {}).get(STATE_ADDR)
        return STATES.get(raw) if raw is not None else None

    @property
    def icon(self) -> str:
        return STATE_ICONS.get(self.native_value or "", "mdi:state-machine")


class WattSeekChargeStageSensor(CoordinatorEntity[WattSeekCoordinator], SensorEntity):
    """Battery charging stage (register 0x0176)."""

    _attr_has_entity_name = True
    _attr_translation_key = "charging_stage"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CHARGE_STAGES.values())

    def __init__(self, coordinator: WattSeekCoordinator, address: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_charging_stage"
        self._attr_device_info = _device_info(address)

    @property
    def native_value(self) -> str | None:
        raw = (self.coordinator.data or {}).get(CHARGE_STAGE_ADDR)
        return CHARGE_STAGES.get(raw) if raw is not None else None

    @property
    def icon(self) -> str:
        return CHARGE_STAGE_ICONS.get(self.native_value or "", "mdi:battery-unknown")


class WattSeekBitsSensor(CoordinatorEntity[WattSeekCoordinator], SensorEntity):
    """Decoded fault/alarm bitfields: 'OK' or a list of active conditions."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, address, key, translation_key, spec, icon) -> None:
        super().__init__(coordinator)
        self._spec = spec
        self._problem_icon = icon
        self._attr_unique_id = f"{address}_{key}"
        self._attr_translation_key = translation_key
        self._attr_device_info = _device_info(address)

    def _active(self) -> list[str] | None:
        active = active_bits(self.coordinator.data or {}, self._spec)
        return None if active is None else localize(active, self.hass.config.language)

    @property
    def native_value(self) -> str | None:
        active = self._active()
        if active is None:
            return None
        if not active:
            return "Немає" if self.hass.config.language.split("-")[0] == "uk" else "None"
        return ", ".join(active)[:255]

    @property
    def icon(self) -> str:
        return self._problem_icon if self._active() else "mdi:check-circle-outline"

    @property
    def extra_state_attributes(self) -> dict:
        active = self._active() or []
        return {"count": len(active), "active": active}


_RAW_CODES = {"inverter_state", "fault_code", "alarm_code"}

# Energy counters can only creep up (a few hundredths of a kWh per poll) or
# roll over to ~0 at the start of a day/month/year. Anything else is a bad
# read; HA statistics would book a drop as a meter reset and add the whole
# counter to the day. A changed value is accepted once it repeats this many
# polls in a row (e.g. after a long gap).
ENERGY_MAX_STEP = 5.0  # kWh between two accepted readings
ENERGY_ROLLOVER_MAX = 5.0  # a period counter may drop to below this
ENERGY_CONFIRM = 3


class EnergyGuard:
    """Rejects implausible jumps in an energy counter."""

    def __init__(self, can_roll_over: bool) -> None:
        self._roll = can_roll_over
        self._last: float | None = None
        self._pending: float | None = None
        self._seen = 0

    def __call__(self, value: float | None) -> float | None:
        if value is None:
            return self._last
        last = self._last
        delta = None if last is None else value - last
        plausible = (
            last is None
            or 0 <= delta <= ENERGY_MAX_STEP
            or (self._roll and delta < 0 and value < ENERGY_ROLLOVER_MAX)
        )
        if not plausible:
            if self._pending == value:
                self._seen += 1
            else:
                self._pending, self._seen = value, 1
            if self._seen < ENERGY_CONFIRM:
                return last
        self._last, self._pending, self._seen = value, None, 0
        return value


class WattSeekSensor(CoordinatorEntity[WattSeekCoordinator], SensorEntity):
    """A single inverter register exposed as a sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WattSeekCoordinator, address: str, reg: Reg) -> None:
        super().__init__(coordinator)
        self._reg = reg
        self._attr_unique_id = f"{address}_{reg.key}"
        # Derive display precision from the register scale (0.1 -> 1, 0.01 -> 2,
        # 1 -> 0) so values show consistently, e.g. "56.0 V" rather than "56 V".
        if reg.scale >= 1:
            precision = 0
        else:
            precision = len(f"{reg.scale:f}".rstrip("0").split(".")[1])
        self.entity_description = SensorEntityDescription(
            key=reg.key,
            name=reg.name,
            native_unit_of_measurement=reg.unit,
            device_class=reg.device_class,
            state_class=reg.state_class,
            suggested_display_precision=precision,
            entity_category=EntityCategory.DIAGNOSTIC if reg.diagnostic else None,
            # Raw state/fault/alarm codes are superseded by the decoded sensors.
            entity_registry_enabled_default=reg.key not in _RAW_CODES,
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"WattSeek Inverter ({address})",
            manufacturer="JSD Solar / WattSeek",
            model="Hybrid Inverter (Wi-Fi local)",
        )
        self._guard = (
            EnergyGuard(can_roll_over=not reg.key.endswith("_total"))
            if reg.device_class == SensorDeviceClass.ENERGY
            else None
        )
        self._value = self._read()

    def _read(self) -> float | None:
        if self.coordinator.data is None:
            return None
        value = decode(self._reg, self.coordinator.data)
        return self._guard(value) if self._guard else value

    def _handle_coordinator_update(self) -> None:
        self._value = self._read()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        return self._value

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self.native_value is not None
        )


def _ms(key: str, icon: str) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        icon=icon,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


TIMING_SENSORS: tuple[SensorEntityDescription, ...] = (
    _ms("response_time", "mdi:timer-sync-outline"),
    _ms("response_time_max", "mdi:timer-alert-outline"),
    _ms("poll_duration", "mdi:timer-outline"),
    _ms("write_response_time", "mdi:timer-edit-outline"),
    SensorEntityDescription(
        key="last_response",
        translation_key="last_response",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class WattSeekTimingSensor(CoordinatorEntity[WattSeekCoordinator], SensorEntity):
    """Link timing: how fast the stick answers our passthrough requests."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WattSeekCoordinator, address: str, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = _device_info(address)

    @property
    def native_value(self):
        return self.coordinator.timing.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        # Stay available after a failed poll so slow/failed cycles stay visible.
        return self.native_value is not None


class WattSeekRequestErrorsSensor(CoordinatorEntity[WattSeekCoordinator], SensorEntity):
    """Requests that timed out or failed since HA started."""

    _attr_has_entity_name = True
    _attr_translation_key = "request_errors"
    _attr_icon = "mdi:wifi-alert"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: WattSeekCoordinator, address: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_request_errors"
        self._attr_device_info = _device_info(address)

    @property
    def native_value(self) -> int:
        return self.coordinator.request_errors

    @property
    def available(self) -> bool:
        return True


STICK_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        icon="mdi:access-point-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class WattSeekStickSensor(CoordinatorEntity[WattSeekCoordinator], SensorEntity):
    """What the Wi-Fi stick reports about itself."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WattSeekCoordinator, address: str, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = _device_info(address)

    @property
    def native_value(self):
        device = self.coordinator.device
        if self.entity_description.key == "wifi_signal":
            return device.stick_status.get("signalStrength")
        return device.last_seen

    @property
    def extra_state_attributes(self):
        if self.entity_description.key != "wifi_signal":
            return None
        st = self.coordinator.device.stick_status
        return {k: st[k] for k in ("ssid", "networkConnectWay", "dataUploadCycle") if k in st} or None

    @property
    def available(self) -> bool:
        return self.native_value is not None
