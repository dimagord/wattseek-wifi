"""Decoding of the inverter state machine, fault and alarm registers.

Source: JSD Solar Modbus protocol (registers 0x0042, 0x0046-0x0049).
"""
from __future__ import annotations

STATE_ADDR = 0x0042
FAULT1_ADDR, FAULT2_ADDR = 0x0046, 0x0047
ALARM1_ADDR, ALARM2_ADDR = 0x0048, 0x0049

# state value -> translation key (names live in translations/*.json)
STATES: dict[int, str] = {
    0: "power_on",
    1: "initialization",
    2: "standby",
    3: "grid_mode",
    4: "solar_mode",
    5: "battery_mode",
    6: "generator_mode",
    7: "fault",
    8: "power_off",
    9: "factory_mode",
    10: "upgrade",
}

# 0x0176 "Charging status": 0 none, 1 constant voltage/current, 2 float, 3 equalize
CHARGE_STAGE_ADDR = 0x0176
CHARGE_STAGES: dict[int, str] = {0: "not_charging", 1: "constant_voltage", 2: "float", 3: "equalize"}
CHARGE_STAGE_ICONS: dict[str, str] = {
    "not_charging": "mdi:battery-outline",
    "constant_voltage": "mdi:battery-charging-high",
    "float": "mdi:battery-check",
    "equalize": "mdi:battery-sync",
}

STATE_ICONS: dict[str, str] = {
    "power_on": "mdi:power",
    "initialization": "mdi:progress-clock",
    "standby": "mdi:power-sleep",
    "grid_mode": "mdi:transmission-tower",
    "solar_mode": "mdi:solar-power",
    "battery_mode": "mdi:home-battery",
    "generator_mode": "mdi:engine",
    "fault": "mdi:alert-circle",
    "power_off": "mdi:power-off",
    "factory_mode": "mdi:factory",
    "upgrade": "mdi:update",
}

FAULT1 = (
    "Mains soft start failure", "Bus overvoltage", "Bus undervoltage",
    "Battery overcurrent", "Overtemperature", "Battery overvoltage",
    "Battery soft start failure", "Bus short circuit", "Inverter soft start failure",
    "Inverter overvoltage", "Inverter undervoltage", "Inverter short circuit",
    "Negative power protection", "Overload failure",
    "Model/hardware incompatibility", "No bootloader",
)
FAULT2 = (
    "Programming in progress", "PV reverse connection", "Parallel serial number abnormal",
    "Parallel communication abnormal", "Parallel battery voltage difference",
    "Parallel mains voltage difference", "Parallel mains frequency difference",
    "Parallel phase loss", "Parallel output sync lost", "BMS fault", "MCU fault",
    None, "Inverter load abnormal",
)
ALARM1 = (
    "Battery not connected", "Battery undervoltage", "Battery low voltage",
    "Charger short circuit", None, "Battery overcharge", "BMS lost",
    "Overtemperature", "Fan stalled", "EEPROM fault", "Overload",
    "Generator waveform abnormal", "Weak PV energy", "Parallel sync signal lost",
    "Parallel phase loss", "Parallel version incompatible",
)
ALARM2 = (
    "Parallel communication error", "Parallel voltage/frequency difference",
    "Low SOC shutdown", "Low SOC alarm", "Parallel battery difference",
    "Battery short circuit", "Battery below starting voltage", "Generator overload",
    "Generator undervoltage", "Generator overvoltage", "CT reverse connection",
    "Unstable mains power",
)


def active_bits(words: dict[int, int], spec: tuple[tuple[int, tuple], ...]) -> list[str] | None:
    """Return the names of set bits across the given (address, names) pairs."""
    out: list[str] = []
    for addr, names in spec:
        raw = words.get(addr)
        if raw is None:
            return None
        for bit in range(16):
            if raw & (1 << bit):
                name = names[bit] if bit < len(names) and names[bit] else f"bit {bit} @ {addr:#06x}"
                out.append(name)
    return out


FAULT_SPEC = ((FAULT1_ADDR, FAULT1), (FAULT2_ADDR, FAULT2))
ALARM_SPEC = ((ALARM1_ADDR, ALARM1), (ALARM2_ADDR, ALARM2))


UK: dict[str, str] = {
    "Mains soft start failure": "Збій плавного пуску від мережі",
    "Bus overvoltage": "Перенапруга шини DC",
    "Bus undervoltage": "Низька напруга шини DC",
    "Battery overcurrent": "Перевищення струму батареї",
    "Overtemperature": "Перегрів",
    "Battery overvoltage": "Перенапруга батареї",
    "Battery soft start failure": "Збій плавного пуску батареї",
    "Bus short circuit": "Коротке замикання шини DC",
    "Inverter soft start failure": "Збій плавного пуску інвертора",
    "Inverter overvoltage": "Перенапруга на виході інвертора",
    "Inverter undervoltage": "Низька напруга на виході інвертора",
    "Inverter short circuit": "Коротке замикання на виході",
    "Negative power protection": "Захист від зворотної потужності",
    "Overload failure": "Аварія через перевантаження",
    "Model/hardware incompatibility": "Несумісність моделі та заліза",
    "No bootloader": "Відсутній завантажувач",
    "Programming in progress": "Іде прошивка",
    "PV reverse connection": "Переплутана полярність PV",
    "Parallel serial number abnormal": "Паралель: помилка серійного номера",
    "Parallel communication abnormal": "Паралель: збій зв'язку",
    "Parallel battery voltage difference": "Паралель: різниця напруг батарей",
    "Parallel mains voltage difference": "Паралель: різниця напруг мережі",
    "Parallel mains frequency difference": "Паралель: різниця частот мережі",
    "Parallel phase loss": "Паралель: втрата фази",
    "Parallel output sync lost": "Паралель: втрата синхронізації виходу",
    "BMS fault": "Аварія BMS",
    "MCU fault": "Аварія мікроконтролера",
    "Inverter load abnormal": "Аномальне навантаження",
    "Battery not connected": "Батарею не під'єднано",
    "Battery undervoltage": "Глибокий розряд батареї",
    "Battery low voltage": "Низька напруга батареї",
    "Charger short circuit": "Коротке замикання зарядника",
    "Battery overcharge": "Перезаряд батареї",
    "BMS lost": "Втрачено зв'язок з BMS",
    "Fan stalled": "Зупинився вентилятор",
    "EEPROM fault": "Помилка пам'яті EEPROM",
    "Overload": "Перевантаження",
    "Generator waveform abnormal": "Спотворена напруга генератора",
    "Weak PV energy": "Слабка генерація PV",
    "Parallel sync signal lost": "Паралель: втрачено сигнал синхронізації",
    "Parallel version incompatible": "Паралель: несумісні версії",
    "Parallel communication error": "Паралель: помилка зв'язку",
    "Parallel voltage/frequency difference": "Паралель: різниця напруги/частоти",
    "Low SOC shutdown": "Вимкнення через низький заряд",
    "Low SOC alarm": "Низький рівень заряду",
    "Parallel battery difference": "Паралель: різниця батарей",
    "Battery short circuit": "Коротке замикання батареї",
    "Battery below starting voltage": "Напруга батареї нижча за пускову",
    "Generator overload": "Перевантаження генератора",
    "Generator undervoltage": "Низька напруга генератора",
    "Generator overvoltage": "Перенапруга генератора",
    "CT reverse connection": "Трансформатор струму під'єднано навпаки",
    "Unstable mains power": "Нестабільна мережа",
}


def localize(names: list[str], language: str) -> list[str]:
    if language.split("-")[0] == "uk":
        return [UK.get(n, n) for n in names]
    return names
