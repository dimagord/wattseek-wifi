"""DataUpdateCoordinator for WattSeek Wi-Fi."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_ALLOW_WRITES, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .device import WattSeekWifiDevice, WattSeekWifiError
from .registers import READ_BLOCKS
from .settings import SETTINGS_BLOCKS

_LOGGER = logging.getLogger(__name__)

# Spans verified on hardware over BLE (the inverter rejects a read that
# crosses unmapped addresses). Over Wi-Fi every block of a poll goes out in a
# single passthrough message, so merging only saves Modbus round trips inside
# the stick, but it keeps the request list short.
FAST_SPANS: tuple[tuple[int, int], ...] = (
    (0x0042, 0x5C),  # state/fault/alarm + grid/load + battery/BMS + PV1/PV2
    (0x0218, 0x10),  # output
    (0x0260, 0x0F),  # PV totals
)
SLOW_SPANS: tuple[tuple[int, int], ...] = (
    (0x4100, 0x44),  # all settings blocks
)
SLOW_EVERY = 60.0
SPAN_GIVE_UP = 3

Plan = list[tuple[tuple[int, int], list[tuple[int, int]]]]


def build_plans(blocks: tuple[tuple[int, int], ...]) -> tuple[Plan, Plan]:
    """Assign every register block to a fast or slow (span, members) read."""
    def inside(span, block):
        return span[0] <= block[0] and block[0] + block[1] <= span[0] + span[1]

    remaining = sorted(set(blocks))
    plans: list[Plan] = []
    for spans in (FAST_SPANS, SLOW_SPANS):
        plan: Plan = []
        for span in spans:
            members = [b for b in remaining if inside(span, b)]
            if members:
                plan.append((span, members))
                remaining = [b for b in remaining if b not in members]
        plans.append(plan)
    fast, slow = plans
    slow += [(b, [b]) for b in remaining]
    return fast, slow


class WattSeekCoordinator(DataUpdateCoordinator[dict[int, int]]):
    """Polls the inverter registers through the Wi-Fi stick."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: WattSeekWifiDevice) -> None:
        interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.entry = entry
        self.device = device
        device.on_upload = self._on_upload
        self._fast_plan, self._slow_plan = build_plans((*READ_BLOCKS, *SETTINGS_BLOCKS))
        self._span_failures: dict[tuple[int, int], int] = {}
        self._last_slow = 0.0
        self._force_slow = True
        self.timing: dict[str, Any] = {
            "response_time": None,       # mean passthrough RTT this poll, ms
            "response_time_max": None,   # slowest exchange this poll, ms
            "poll_duration": None,       # whole poll, ms
            "write_response_time": None,  # last settings write RTT, ms
            "last_response": None,       # when the inverter last answered
        }

    @property
    def request_errors(self) -> int:
        return self.device.request_errors

    @callback
    def _on_upload(self, words: dict[int, int]) -> None:
        """Merge the stick's own periodic upload into the current data."""
        if self.data is None:
            return
        self.data.update(words)
        self.async_update_listeners()

    def _record_timing(self, started: float) -> None:
        rtts = self.device.rtts
        if rtts:
            self.timing["response_time"] = round(sum(rtts) / len(rtts) * 1000)
            self.timing["response_time_max"] = round(max(rtts) * 1000)
            self.timing["last_response"] = dt_util.utcnow()
        self.timing["poll_duration"] = round((time.monotonic() - started) * 1000)

    async def _read_many(
        self, blocks: list[tuple[int, int]]
    ) -> dict[tuple[int, int], list[int] | None]:
        if not blocks:
            return {}
        try:
            return await self.device.async_read_many(blocks)
        except WattSeekWifiError as err:
            _LOGGER.debug("passthrough failed: %s", err)
            return {b: None for b in blocks}

    async def _async_update_data(self) -> dict[int, int]:
        started = time.monotonic()
        self.device.reset_timing()
        slow = self._force_slow or time.monotonic() - self._last_slow >= SLOW_EVERY
        plan = self._fast_plan + (self._slow_plan if slow else [])

        # One passthrough message for the whole poll.
        request: list[tuple[int, int]] = []
        for span, members in plan:
            if len(members) > 1 and self._span_failures.get(span, 0) < SPAN_GIVE_UP:
                request.append(span)
            else:
                request.extend(members)
        results = await self._read_many(request)

        words: dict[int, int] = {}
        retry: list[tuple[tuple[int, int], list[tuple[int, int]]]] = []
        for span, members in plan:
            if span in results and len(members) > 1:
                regs = results[span]
                if regs is not None:
                    self._span_failures[span] = 0
                    words.update({span[0] + i: v for i, v in enumerate(regs)})
                else:
                    retry.append((span, members))
                continue
            for block in members:
                regs = results.get(block)
                if regs is not None:
                    words.update({block[0] + i: v for i, v in enumerate(regs)})

        # A merged span failed: read its pieces (second message) and remember
        # if the pieces work while the span doesn't.
        if retry and words:
            pieces = await self._read_many([b for _, members in retry for b in members])
            for span, members in retry:
                ok = 0
                for block in members:
                    regs = pieces.get(block)
                    if regs is not None:
                        ok += 1
                        words.update({block[0] + i: v for i, v in enumerate(regs)})
                if ok == len(members):
                    n = self._span_failures.get(span, 0) + 1
                    self._span_failures[span] = n
                    if n == SPAN_GIVE_UP:
                        _LOGGER.info(
                            "merged read %#06x+%d keeps failing; reading its %d blocks separately",
                            span[0], span[1], len(members),
                        )

        if slow and words:
            self._last_slow = time.monotonic()
            self._force_slow = False
        self._record_timing(started)
        if not words:
            raise UpdateFailed(
                "the Wi-Fi stick did not answer (is it connected to the local broker?)"
            )
        return {**(self.data or {}), **words}

    async def async_write_setting(self, addr: int, value: int) -> None:
        """Write one settings register, then refresh."""
        if not self.entry.options.get(CONF_ALLOW_WRITES, False):
            raise HomeAssistantError(
                "Changing inverter settings is disabled. Enable "
                "'Allow changing inverter settings' in the WattSeek Wi-Fi options."
            )
        try:
            await self.device.async_write_register(addr, value)
        except WattSeekWifiError as err:
            raise HomeAssistantError(f"Failed to write {addr:#06x}: {err}") from err
        if self.device.last_rtt is not None:
            self.timing["write_response_time"] = round(self.device.last_rtt * 1000)
            self.timing["last_response"] = dt_util.utcnow()
        self._force_slow = True
        if self.data is not None:
            self.data[addr] = value & 0xFFFF
            self.async_update_listeners()
        await self.async_request_refresh()
