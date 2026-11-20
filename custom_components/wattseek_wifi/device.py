"""Local MQTT transport for the WattSeek Wi-Fi stick.

The stick believes it is talking to the vendor cloud broker. We answer the
handful of housekeeping requests it needs before it will work (sub-device
registration, time sync, firmware check) and use the cloud's Modbus
passthrough command to read and write inverter registers whenever we like.

Wire format (all JSON, captured from the real cloud):

  passthrough request, published to .../rpc/request/<request_id>:
    {"traceId": "...", "requestId": "<request_id>",
     "method": "thing.service.down",
     "params": {"cmds": ["<RTU frame hex>", ...], "executeId": "<id>"},
     "needToCache": false}

  answer, published by the stick to .../thing/post:
    {"method": "thing.event.up.post",
     "params": {"mainDeviceId": "...", "localDateTime": "...",
                "content": [{"cmd": "<RTU frame hex>", "data": "<RTU answer hex>"}, ...],
                "executeId": "<id>"}, ...}

The stick also uploads a fixed set of reads every few minutes on its own
(same method, no executeId); those are merged in as a bonus.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    FUNC_OTA,
    FUNC_REGISTER,
    FUNC_STATUS,
    FUNC_TIME_SYNC,
    INVERTER_MODBUS_ID,
    METHOD_DOWN,
    METHOD_STICK_DOWN,
    METHOD_STICK_UP,
    METHOD_UP,
    TOPIC_DOWN,
    TOPIC_UP,
)
from .modbus import (
    ModbusError,
    build_read,
    build_write,
    parse_read,
    parse_read_request,
    parse_write,
)

_LOGGER = logging.getLogger(__name__)

COMMAND_TIMEOUT = 10.0
# The stick counts as online while it has spoken to us this recently (it
# pings the broker every few minutes and uploads every 5 minutes on its own).
ONLINE_WINDOW = 600.0


class WattSeekWifiError(Exception):
    """Transport-level error."""


class WattSeekWifiDevice:
    """Talks to one WattSeek Wi-Fi stick through the local MQTT broker."""

    def __init__(
        self,
        hass: HomeAssistant,
        product_key: str,
        stick_id: str,
        inverter_id: str,
    ) -> None:
        self.hass = hass
        self.product_key = product_key
        self.stick_id = stick_id
        self.inverter_id = inverter_id
        self._up_topic = TOPIC_UP.format(product_key=product_key, stick_id=stick_id)
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[list[dict[str, Any]]]] = {}
        self._unsub: Callable[[], None] | None = None
        self._last_seen: float | None = None
        self.last_seen: datetime | None = None
        self.stick_status: dict[str, Any] = {}
        self.inverter_sn: str | None = None
        # Called with {address: word} for the stick's own periodic uploads.
        self.on_upload: Callable[[dict[int, int]], None] | None = None
        # Round-trip times (s) of passthrough exchanges since reset_timing().
        self.rtts: list[float] = []
        self.last_rtt: float | None = None
        self.request_errors = 0

    # -- lifecycle -------------------------------------------------------------
    async def async_start(self) -> None:
        self._unsub = await mqtt.async_subscribe(
            self.hass, self._up_topic, self._on_message, qos=1
        )

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(WattSeekWifiError("stopped"))
        self._pending.clear()

    # Interface shared with the BLE integration's coordinator.
    @property
    def address(self) -> str:
        return self.stick_id

    @property
    def connected(self) -> bool:
        return self._last_seen is not None and time.monotonic() - self._last_seen < ONLINE_WINDOW

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        return None

    def reset_timing(self) -> None:
        self.rtts = []

    # -- incoming ----------------------------------------------------------------
    @callback
    def _on_message(self, msg: mqtt.ReceiveMessage) -> None:
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.debug("non-JSON message on %s: %r", msg.topic, msg.payload)
            return
        self._last_seen = time.monotonic()
        self.last_seen = dt_util.utcnow()
        method = data.get("method")
        params = data.get("params") or {}
        if method == METHOD_STICK_UP:
            self._handle_stick_up(params, data.get("traceId"))
        elif method == METHOD_UP:
            self._handle_up(params)
        else:
            _LOGGER.debug("unhandled message %s", data)

    def _handle_stick_up(self, params: dict[str, Any], trace_id: str | None) -> None:
        func = params.get("funcKey")
        body = params.get("data") or {}
        if func == FUNC_REGISTER:
            self.inverter_sn = body.get("identifier") or self.inverter_sn
            _LOGGER.debug("stick registers inverter %s", self.inverter_sn)
            self._reply(trace_id, "sub.device.register.response", {
                "msg": "Success",
                "code": "000200",
                "data": {
                    "identifier": body.get("identifier"),
                    "deviceSecret": None,
                    "deviceId": self.inverter_id,
                },
            })
        elif func == FUNC_TIME_SYNC:
            now = dt_util.now().replace(tzinfo=None)
            self._reply(trace_id, "stick.time.sync.response", {
                "data": {"currentTime": now.isoformat(timespec="milliseconds")},
            })
        elif func == FUNC_OTA:
            self._reply(trace_id, "ota.upgrade.response", {"data": {"hasUpdate": False}})
        elif func == FUNC_STATUS:
            self.stick_status = dict(body)
        else:
            _LOGGER.debug("unhandled stickUp %s: %s", func, params)

    def _handle_up(self, params: dict[str, Any]) -> None:
        content = params.get("content") or []
        execute_id = params.get("executeId")
        if execute_id is not None:
            fut = self._pending.get(str(execute_id))
            if fut and not fut.done():
                fut.set_result(content)
            return
        # The stick's own periodic upload: decode the reads it contains.
        words: dict[int, int] = {}
        for item in content:
            try:
                req = parse_read_request(bytes.fromhex(item.get("cmd", "")))
                if req is None:
                    continue
                slave, start, count = req
                regs = parse_read(bytes.fromhex(item.get("data", "")), slave, count)
            except (ValueError, ModbusError):
                continue
            words.update({start + i: v for i, v in enumerate(regs)})
        if words and self.on_upload:
            self.on_upload(words)

    # -- outgoing ----------------------------------------------------------------
    def _publish(self, payload: dict[str, Any]) -> None:
        topic = TOPIC_DOWN.format(
            product_key=self.product_key,
            stick_id=self.stick_id,
            request_id=payload["requestId"],
        )
        self.hass.async_create_task(
            mqtt.async_publish(
                self.hass, topic, json.dumps(payload, separators=(",", ":")), qos=1
            )
        )

    def _reply(self, trace_id: str | None, func_key: str, body: dict[str, Any]) -> None:
        self._publish({
            "traceId": trace_id or str(uuid.uuid4()),
            "requestId": uuid.uuid4().hex,
            "method": METHOD_STICK_DOWN,
            "params": {"funcKey": func_key, "body": body},
            "needToCache": False,
        })

    async def async_execute(
        self, frames: list[bytes], timeout: float = COMMAND_TIMEOUT
    ) -> list[bytes | None]:
        """Send raw RTU frames through the stick; return the raw answers in order."""
        async with self._lock:
            execute_id = str(random.randrange(10**18, 10**19))
            request_id = uuid.uuid4().hex
            hexes = [f.hex().upper() for f in frames]
            fut: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()
            self._pending[execute_id] = fut
            started = time.monotonic()
            try:
                await mqtt.async_publish(
                    self.hass,
                    TOPIC_DOWN.format(
                        product_key=self.product_key,
                        stick_id=self.stick_id,
                        request_id=request_id,
                    ),
                    json.dumps({
                        "traceId": uuid.uuid4().hex,
                        "requestId": request_id,
                        "method": METHOD_DOWN,
                        "params": {"cmds": hexes, "executeId": execute_id},
                        "needToCache": False,
                    }, separators=(",", ":")),
                    qos=1,
                )
                content = await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError as err:
                self.request_errors += 1
                raise WattSeekWifiError(f"no answer within {timeout:.0f} s") from err
            except WattSeekWifiError:
                self.request_errors += 1
                raise
            finally:
                self._pending.pop(execute_id, None)
            rtt = time.monotonic() - started
            self.last_rtt = rtt
            self.rtts.append(rtt)

        answers: dict[str, bytes | None] = {}
        for item in content:
            cmd = str(item.get("cmd", "")).upper()
            raw = item.get("data")
            try:
                answers[cmd] = bytes.fromhex(raw) if raw else None
            except ValueError:
                answers[cmd] = None
        return [answers.get(h) for h in hexes]

    async def async_read_many(
        self, blocks: list[tuple[int, int]]
    ) -> dict[tuple[int, int], list[int] | None]:
        """Read several register blocks in one exchange."""
        frames = [build_read(INVERTER_MODBUS_ID, s, c) for s, c in blocks]
        raw = await self.async_execute(frames)
        out: dict[tuple[int, int], list[int] | None] = {}
        for (start, count), resp in zip(blocks, raw):
            if resp is None:
                out[(start, count)] = None
                continue
            try:
                out[(start, count)] = parse_read(resp, INVERTER_MODBUS_ID, count)
            except ModbusError as err:
                _LOGGER.debug("read %#06x+%d: %s", start, count, err)
                out[(start, count)] = None
        return out

    async def async_read_registers(self, start: int, count: int) -> list[int]:
        regs = (await self.async_read_many([(start, count)]))[(start, count)]
        if regs is None:
            raise WattSeekWifiError(f"read {start:#06x}+{count} failed")
        return regs

    async def async_write_register(self, addr: int, value: int) -> None:
        (resp,) = await self.async_execute([build_write(INVERTER_MODBUS_ID, addr, [value])])
        if resp is None:
            raise WattSeekWifiError(f"no answer to write {addr:#06x}")
        try:
            parse_write(resp, INVERTER_MODBUS_ID, addr, 1)
        except ModbusError as err:
            raise WattSeekWifiError(str(err)) from err
