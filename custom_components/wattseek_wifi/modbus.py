"""Minimal Modbus RTU framing for the stick's passthrough command.

The stick forwards raw RTU frames (hex strings, CRC included) to the inverter
and returns the inverter's raw RTU answers, so we build and check them here.
"""
from __future__ import annotations


class ModbusError(Exception):
    """Bad, truncated or exception response."""


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


def _frame(body: bytes) -> bytes:
    return body + crc16(body)


def build_read(slave: int, start: int, count: int) -> bytes:
    """Function 0x03, read holding registers."""
    return _frame(bytes([slave, 0x03]) + start.to_bytes(2, "big") + count.to_bytes(2, "big"))


def build_write(slave: int, start: int, values: list[int]) -> bytes:
    """Function 0x10, write multiple registers (what the vendor app uses)."""
    payload = b"".join((v & 0xFFFF).to_bytes(2, "big") for v in values)
    body = (
        bytes([slave, 0x10])
        + start.to_bytes(2, "big")
        + len(values).to_bytes(2, "big")
        + bytes([len(payload)])
        + payload
    )
    return _frame(body)


def _check(resp: bytes, slave: int, function: int) -> None:
    if len(resp) < 5:
        raise ModbusError(f"short response {resp.hex()}")
    if crc16(resp[:-2]) != resp[-2:]:
        raise ModbusError(f"bad CRC {resp.hex()}")
    if resp[0] != slave:
        raise ModbusError(f"answer from slave {resp[0]}")
    if resp[1] == function | 0x80:
        raise ModbusError(f"exception code {resp[2]}")
    if resp[1] != function:
        raise ModbusError(f"unexpected function {resp[1]:#x}")


def parse_read(resp: bytes, slave: int, count: int) -> list[int]:
    _check(resp, slave, 0x03)
    n = resp[2]
    if n != count * 2 or len(resp) != 3 + n + 2:
        raise ModbusError(f"expected {count} registers, got {resp.hex()}")
    data = resp[3:3 + n]
    return [int.from_bytes(data[i:i + 2], "big") for i in range(0, n, 2)]


def parse_write(resp: bytes, slave: int, start: int, count: int) -> None:
    _check(resp, slave, 0x10)
    if len(resp) != 8 or resp[2:6] != start.to_bytes(2, "big") + count.to_bytes(2, "big"):
        raise ModbusError(f"unexpected write echo {resp.hex()}")


def parse_read_request(req: bytes) -> tuple[int, int, int] | None:
    """(slave, start, count) of a 0x03 request frame, else None."""
    if len(req) != 8 or req[1] != 0x03 or crc16(req[:-2]) != req[-2:]:
        return None
    return req[0], int.from_bytes(req[2:4], "big"), int.from_bytes(req[4:6], "big")
