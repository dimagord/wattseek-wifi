"""Config flow for WattSeek Wi-Fi."""
from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .const import (
    CONF_ADDRESS,
    CONF_ALLOW_WRITES,
    CONF_INVERTER_ID,
    CONF_PRODUCT_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)


def parse_up_topic(topic: str) -> tuple[str, str] | None:
    """(product_key, stick_id) from /sys/<product_key>/<stick_id>/thing/post."""
    parts = topic.split("/")
    if len(parts) == 6 and parts[0] == "" and parts[1] == "sys" and parts[4:] == ["thing", "post"]:
        return parts[2], parts[3]
    return None


def main_device_id(payload: str | bytes) -> str | None:
    """The inverter id the cloud handed out, if this message carries it."""
    try:
        params = json.loads(payload).get("params") or {}
    except (ValueError, AttributeError, TypeError):
        return None
    found = params.get("mainDeviceId") or (params.get("data") or {}).get("mainDeviceId")
    return str(found) if found else None


def default_inverter_id(stick_id: str) -> str:
    return str(int(stick_id) + 1) if stick_id.isdigit() else f"{stick_id}-inv"


class WattSeekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WattSeek Wi-Fi."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """A stick published on the local broker."""
        parsed = parse_up_topic(discovery_info.topic)
        if parsed is None:
            return self.async_abort(reason="invalid_discovery_info")
        product_key, stick_id = parsed
        await self.async_set_unique_id(stick_id)
        self._abort_if_unique_id_configured()
        self._data = {
            CONF_PRODUCT_KEY: product_key,
            CONF_ADDRESS: stick_id,
            CONF_INVERTER_ID: main_device_id(discovery_info.payload)
            or default_inverter_id(stick_id),
        }
        self.context["title_placeholders"] = {"name": stick_id}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=f"WattSeek Wi-Fi {self._data[CONF_ADDRESS]}", data=self._data
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"stick_id": self._data[CONF_ADDRESS]},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup with the ids seen in the stick's MQTT topic."""
        if user_input is not None:
            stick_id = user_input[CONF_ADDRESS].strip()
            await self.async_set_unique_id(stick_id, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            data = {
                CONF_PRODUCT_KEY: user_input[CONF_PRODUCT_KEY].strip(),
                CONF_ADDRESS: stick_id,
                CONF_INVERTER_ID: (user_input.get(CONF_INVERTER_ID) or "").strip()
                or default_inverter_id(stick_id),
            }
            return self.async_create_entry(title=f"WattSeek Wi-Fi {stick_id}", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PRODUCT_KEY): str,
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_INVERTER_ID): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WattSeekOptionsFlow()


class WattSeekOptionsFlow(OptionsFlow):
    """Options: update interval and write lock."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(
                        cv.positive_int,
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    ),
                    vol.Required(
                        CONF_ALLOW_WRITES,
                        default=self.config_entry.options.get(CONF_ALLOW_WRITES, False),
                    ): bool,
                }
            ),
        )
