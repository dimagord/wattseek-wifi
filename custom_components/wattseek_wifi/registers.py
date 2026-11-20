"""Inverter Modbus register map (JSD Solar 3KU family, protocol V1.20).

Read over the WattSeek Wi-Fi TRANSPARENT tunnel. Addresses, scales, signedness
and 16/32-bit widths come from the published register map used by the ESPHome
JSDSolar project. 32-bit values are stored high-word-first (validated against
captures).
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)

_MEAS = SensorStateClass.MEASUREMENT
_TOTAL = SensorStateClass.TOTAL_INCREASING


@dataclass(frozen=True)
class Reg:
    key: str
    name: str
    address: int
    scale: float = 1.0
    signed: bool = False
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = _MEAS
    words: int = 1  # 1 = 16-bit, 2 = 32-bit (high word first)
    diagnostic: bool = False


_V = SensorDeviceClass.VOLTAGE
_A = SensorDeviceClass.CURRENT
_F = SensorDeviceClass.FREQUENCY
_P = SensorDeviceClass.POWER
_T = SensorDeviceClass.TEMPERATURE
_B = SensorDeviceClass.BATTERY
_E = SensorDeviceClass.ENERGY
_AP = SensorDeviceClass.APPARENT_POWER
_VV = UnitOfElectricPotential.VOLT
_AA = UnitOfElectricCurrent.AMPERE
_HZ = UnitOfFrequency.HERTZ
_W = UnitOfPower.WATT
_C = UnitOfTemperature.CELSIUS
_KWH = UnitOfEnergy.KILO_WATT_HOUR


def _energy(key: str, name: str, addr: int, words: int = 2, scale: float = 0.01) -> Reg:
    return Reg(key, name, addr, scale, False, _KWH, _E, _TOTAL, words)


REGISTERS: tuple[Reg, ...] = (
    # --- Grid -------------------------------------------------------------
    Reg("grid_voltage", "Grid Voltage", 0x0050, 0.1, False, _VV, _V),
    Reg("grid_current", "Grid Current", 0x0051, 0.01, False, _AA, _A),
    Reg("grid_frequency", "Grid Frequency", 0x0052, 0.01, False, _HZ, _F),
    # Inverter reports import as negative; flip so import > 0 (HA convention).
    Reg("grid_power", "Grid Power", 0x0053, -1, True, _W, _P),
    # --- Load -------------------------------------------------------------
    Reg("load_voltage", "Load Voltage", 0x0058, 0.1, False, _VV, _V),
    Reg("load_current", "Load Current", 0x0059, 0.01, False, _AA, _A),
    Reg("load_frequency", "Load Frequency", 0x005A, 0.01, False, _HZ, _F),
    Reg("load_power", "Load Active Power", 0x005B, 1, True, _W, _P),
    Reg("load_apparent_power", "Load Apparent Power", 0x005C, 1, True, UnitOfApparentPower.VOLT_AMPERE, _AP),
    Reg("load_percentage", "Load Percentage", 0x005D, 0.1, False, PERCENTAGE, None),
    # --- Battery ----------------------------------------------------------
    Reg("battery_voltage", "Battery Voltage", 0x0080, 0.1, False, _VV, _V),
    Reg("battery_current", "Battery Current", 0x0081, 0.1, True, _AA, _A),
    Reg("battery_soc", "Battery SOC", 0x0084, 1, False, PERCENTAGE, _B),
    Reg("battery_power", "Battery Power", 0x0085, 1, True, _W, _P),
    # --- BMS (present only when a smart battery is wired to the BMS port) --
    Reg("bms_voltage", "BMS Voltage", 0x0088, 0.1, False, _VV, _V),
    Reg("bms_current", "BMS Current", 0x0089, 0.1, True, _AA, _A),
    Reg("bms_soc", "BMS SOC", 0x008A, 1, False, PERCENTAGE, _B),
    Reg("bms_temperature", "BMS Temperature", 0x008B, 1, True, _C, _T),
    # --- PV ---------------------------------------------------------------
    Reg("pv1_voltage", "PV1 Voltage", 0x0096, 0.1, False, _VV, _V),
    Reg("pv1_current", "PV1 Current", 0x0097, 0.01, False, _AA, _A),
    Reg("pv1_power", "PV1 Power", 0x0098, 1, True, _W, _P),
    Reg("pv2_voltage", "PV2 Voltage", 0x0099, 0.1, False, _VV, _V),
    Reg("pv2_current", "PV2 Current", 0x009A, 0.01, False, _AA, _A),
    Reg("pv2_power", "PV2 Power", 0x009B, 1, True, _W, _P),
    Reg("pv_energy_today", "PV Energy Today", 0x009C, 0.1, False, _KWH, _E, _TOTAL),
    Reg("pv_energy_total", "PV Energy Total", 0x009D, 0.1, False, _KWH, _E, _TOTAL),
    Reg("pv_total_voltage", "PV Total Voltage", 0x0260, 0.1, False, _VV, _V),
    Reg("pv_total_power", "PV Total Power", 0x0263, 1, True, _W, _P),
    _energy("pv_energy_today_total", "PV Energy Today (all strings)", 0x0267),
    _energy("pv_energy_month_total", "PV Energy Month (all strings)", 0x0269),
    _energy("pv_energy_year_total", "PV Energy Year (all strings)", 0x026B),
    _energy("pv_energy_total_all", "PV Energy Total (all strings)", 0x026D),
    # --- Output -----------------------------------------------------------
    Reg("output_voltage", "Output Voltage", 0x0218, 0.1, False, _VV, _V),
    Reg("output_frequency", "Output Frequency", 0x0219, 0.01, False, _HZ, _F),
    Reg("output_current", "Output Current", 0x021A, 0.01, False, _AA, _A),
    Reg("output_power", "Output Active Power", 0x021C, 1, True, _W, _P),
    Reg("output_percentage", "Output Load Percentage", 0x0220, 0.1, False, PERCENTAGE, None),
    _energy("output_energy_today", "Output Energy Today", 0x0221),
    _energy("output_energy_month", "Output Energy Month", 0x0223),
    _energy("output_energy_year", "Output Energy Year", 0x0225),
    _energy("output_energy_total", "Output Energy Total", 0x0227),
    # --- Grid energy counters --------------------------------------------
    _energy("grid_feed_in_today", "Grid Feed-in Today", 0x01B7),
    _energy("grid_feed_in_month", "Grid Feed-in Month", 0x01B9),
    _energy("grid_feed_in_year", "Grid Feed-in Year", 0x01BB),
    _energy("grid_feed_in_total", "Grid Feed-in Total", 0x01BD),
    _energy("grid_consumption_today", "Grid Consumption Today", 0x01BF),
    _energy("grid_consumption_month", "Grid Consumption Month", 0x01C1),
    _energy("grid_consumption_year", "Grid Consumption Year", 0x01C3),
    _energy("grid_consumption_total", "Grid Consumption Total", 0x01C5),
    # --- Temperatures -----------------------------------------------------
    Reg("pv_temperature", "PV Temperature", 0x0330, 0.1, True, _C, _T, diagnostic=True),
    Reg("inverter_temperature", "Inverter Temperature", 0x0331, 0.1, True, _C, _T, diagnostic=True),
    Reg("charger_temperature", "Charger Temperature", 0x0332, 0.1, True, _C, _T, diagnostic=True),
    Reg("charger2_temperature", "Charger 2 Temperature", 0x0333, 0.1, True, _C, _T, diagnostic=True),
    Reg("ambient_temperature", "Ambient Temperature", 0x0334, 0.1, True, _C, _T, diagnostic=True),
    Reg("discharge_temperature", "Discharge Temperature", 0x0335, 0.1, True, _C, _T, diagnostic=True),
    # --- Cooling -------------------------------------------------------------
    Reg("fan_speed", "Fan Speed", 0x0320, 1, False, PERCENTAGE, None, diagnostic=True),
    # --- Diagnostics (raw codes) -----------------------------------------
    Reg("inverter_state", "Inverter State", 0x0042, 1, False, None, None, diagnostic=True),
    Reg("fault_code", "Fault Code", 0x0046, 1, False, None, None, diagnostic=True),
    Reg("alarm_code", "Alarm Code", 0x0048, 1, False, None, None, diagnostic=True),
)

# Contiguous blocks to read (start, count); each <= 16 registers.
READ_BLOCKS: tuple[tuple[int, int], ...] = (
    (0x0042, 0x08),  # state, fault, alarm codes
    (0x0050, 0x0E),  # grid + load
    (0x0080, 0x0C),  # battery + bms
    (0x0096, 0x08),  # pv + pv energy (word)
    (0x01B7, 0x10),  # grid feed-in / consumption counters
    (0x0218, 0x10),  # output + output energy
    (0x0260, 0x0F),  # pv totals + pv energy counters
    (0x0330, 0x06),  # temperatures
    (0x0320, 0x02),  # fan speed + fan status
    (0x0176, 0x01),  # charging stage
)

# Value a 16-bit register carries when the inverter has no data for it.
_SENTINELS = (0x7FFF, 0xFFFF)


def decode(reg: Reg, words: dict[int, int]) -> float | None:
    """Decode one register's engineering value from a {address: word} map."""
    hi = words.get(reg.address)
    if hi is None:
        return None
    if reg.words == 2:
        lo = words.get(reg.address + 1)
        if lo is None:
            return None
        raw = (hi << 16) | lo
        if reg.signed and raw >= 0x80000000:
            raw -= 0x100000000
    else:
        if hi in _SENTINELS:
            return None
        raw = hi
        if reg.signed and raw >= 0x8000:
            raw -= 0x10000
    return round(raw * reg.scale, 2)
