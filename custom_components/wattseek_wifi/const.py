"""Constants for the WattSeek Wi-Fi integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "wattseek_wifi"

# --- MQTT topics ------------------------------------------------------------
# The WattSeek Wi-Fi stick talks MQTT (over TLS, without checking the server
# certificate) to the vendor cloud broker. Pointing its broker hostname at a
# local Mosquitto makes it talk to Home Assistant instead. Topics:
#   up   (stick -> us): /sys/<product_key>/<stick_id>/thing/post
#   down (us -> stick): /sys/<product_key>/<stick_id>/rpc/request/<request_id>
TOPIC_UP: Final = "/sys/{product_key}/{stick_id}/thing/post"
TOPIC_DOWN: Final = "/sys/{product_key}/{stick_id}/rpc/request/{request_id}"
TOPIC_UP_DISCOVERY: Final = "/sys/+/+/thing/post"

# Message methods
METHOD_STICK_UP: Final = "thing.event.stickUp.post"   # stick status/requests
METHOD_UP: Final = "thing.event.up.post"             # Modbus results
METHOD_STICK_DOWN: Final = "thing.service.stickDownCmd"  # replies to stickUp
METHOD_DOWN: Final = "thing.service.down"            # Modbus passthrough

# stickUp function keys we answer (the stick retries until it gets a reply)
FUNC_REGISTER: Final = "sub.device.register"
FUNC_TIME_SYNC: Final = "stick.time.sync.request"
FUNC_OTA: Final = "ota.upgrade.request"
FUNC_STATUS: Final = "stick.status"

# Inverter Modbus slave address
INVERTER_MODBUS_ID: Final = 0x01

# --- Config entry -------------------------------------------------------------
CONF_ADDRESS: Final = "address"          # stick id, also the device identifier
CONF_PRODUCT_KEY: Final = "product_key"
CONF_INVERTER_ID: Final = "inverter_id"  # id we hand out at sub-device register
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_ALLOW_WRITES: Final = "allow_writes"
DEFAULT_UPDATE_INTERVAL: Final = 5
MIN_UPDATE_INTERVAL: Final = 1
MAX_UPDATE_INTERVAL: Final = 600
