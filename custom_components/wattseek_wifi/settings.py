"""Writable inverter settings (JSD Solar 3KU, menu registers at 0x4100+).

Addresses, option maps and ranges mirror the validated ESPHome JSDSolar
config. Written over the WattSeek Wi-Fi TRANSPARENT tunnel (single-register
Modbus write with function 0x10). Dangerous commands (factory
reset, power on/off) are intentionally omitted.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectSetting:
    key: str
    name: str
    address: int
    options: dict[int, str]  # register value -> label

    def label_for(self, raw: int | None) -> str | None:
        return self.options.get(raw) if raw is not None else None

    def value_for(self, label: str) -> int | None:
        for v, lbl in self.options.items():
            if lbl == label:
                return v
        return None


@dataclass(frozen=True)
class NumberSetting:
    key: str
    name: str
    address: int
    min_value: float
    max_value: float
    step: float = 1.0
    scale: float = 1.0  # engineering = raw * scale
    unit: str | None = None


_AC_CURRENT = {2: "2A"} | {a: f"{a}A" for a in range(10, 130, 10)}

# Operating-mode register; some ranges depend on it (manual program 04).
OPERATING_MODE_ADDR = 0x4103
MODE_UPS = 1

# Exposed on purpose: only everyday operating choices plus setpoints whose
# ranges are bounded by the inverter manual (J6500HC, LCD programs 03-06,
# 20, 22, 23). Deliberately NOT exposed: output voltage/frequency (01/02,
# risk to connected appliances), battery type (17, changes the whole charge
# profile), grid-tie feed-in (36/37), factory reset (26) and the unverified
# 0x412F register. Note: 0x4118 is program 38 (dual-output cutoff voltage),
# not the charge voltage as the ESPHome config labelled it.
SELECTS: tuple[SelectSetting, ...] = (
    SelectSetting(
        "output_priority", "Output Priority", 0x4102,
        {0: "GPB (Grid-PV-Battery)", 1: "PGB (PV-Grid-Battery)", 2: "PBG (PV-Battery-Grid)", 3: "MKS Mode"},
    ),
    SelectSetting("operating_mode", "Operating Mode", OPERATING_MODE_ADDR, {0: "APP", 1: "UPS", 2: "GEN"}),
    SelectSetting(
        "charging_priority", "Charging Priority", 0x4104,
        {0: "PNG (PV & Grid)", 1: "OPV (Only PV)", 2: "PVF (PV First)"},
    ),
    SelectSetting("ac_charging_current", "AC Charging Current", 0x4105, _AC_CURRENT),
)

NUMBERS: tuple[NumberSetting, ...] = (
    # Battery voltage setpoints (raw = V*10), mapped on a real inverter:
    # 0x410A = program 20 (CV), 0x410B = 21 (float), 0x410C = 15 (back to
    # grid), 0x410D = 16 (back to battery). Ranges are the manual's CUS/LIB
    # ranges, with CV capped at 58.4 V (no BMS link to stop an overcharge).
    NumberSetting("constant_charge_voltage", "Constant Charge Voltage", 0x410A, 48.0, 58.4, 0.1, 0.1, "V"),
    NumberSetting("float_charge_voltage", "Float Charge Voltage", 0x410B, 50.0, 58.0, 0.1, 0.1, "V"),
    NumberSetting("back_to_grid_voltage", "Switch to Grid Voltage", 0x410C, 40.0, 50.0, 0.1, 0.1, "V"),
    NumberSetting("back_to_battery_voltage", "Switch to Battery Voltage", 0x410D, 46.0, 58.0, 0.1, 0.1, "V"),
    # Program 22: APP/GEN 90-154 V, UPS 170-200 V (see UPS_RANGES).
    NumberSetting("grid_low_voltage", "Grid Low Voltage", 0x410E, 90.0, 154.0, 1.0, 1.0, "V"),
    # Program 23: APP/GEN 264-280 V; fixed at 264 V in UPS mode.
    NumberSetting("grid_high_voltage", "Grid High Voltage", 0x410F, 264.0, 280.0, 1.0, 1.0, "V"),
)

# Ordering rules the manual requires: (lower_key, upper_key) -> lower < upper.
ORDER_RULES: tuple[tuple[str, str], ...] = (
    ("float_charge_voltage", "constant_charge_voltage"),
    ("back_to_grid_voltage", "back_to_battery_voltage"),
    ("back_to_battery_voltage", "constant_charge_voltage"),
)

# Mode-dependent overrides: key -> (min, max) when operating mode is UPS.
UPS_RANGES: dict[str, tuple[float, float]] = {
    "grid_low_voltage": (170.0, 200.0),
    "grid_high_voltage": (264.0, 264.0),
}

# Register blocks that hold the settings above (read so current values show).
SETTINGS_BLOCKS: tuple[tuple[int, int], ...] = (
    (0x4100, 0x10),  # 0x4100 - 0x410F
    (0x4110, 0x10),  # 0x4110 - 0x411F
    (0x4120, 0x10),  # 0x4120 - 0x412F
    (0x4142, 0x02),  # 0x4142 - 0x4143
)
