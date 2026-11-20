# WattSeek Wi-Fi stick — cloud MQTT protocol

Observed on a JSD Solar J6500HC-48 (ECGSOLAX / Anern clone) with the built-in WattSeek Wi-Fi + BLE stick, firmware reporting product code `SXFN`, model code `16`, November 2026. Everything below was captured between the stick and the real cloud broker, then reproduced locally.

## Transport

| | |
|---|---|
| Broker | `iot-broker-eur.ifpserver.com:8883` (EU), TLS 1.2/1.3 |
| Server certificate | real one is `CN=*.bytello.com` (DigiCert). **The stick does not verify it** — any self-signed certificate is accepted. |
| MQTT | 3.1.1, keepalive 420 s, clean session off |
| Client id / username | stick id (19 digits, e.g. `1235856371187654656`) |
| Password | per-device, 32 hex chars, sent in clear inside TLS |
| DNS | resolved through the DHCP-provided resolver; reconnects re-resolve |

## Topics

| Direction | Topic |
|---|---|
| stick → cloud | `/sys/<product_key>/<stick_id>/thing/post` |
| cloud → stick | `/sys/<product_key>/<stick_id>/rpc/request/<request_id>` (stick subscribes to `.../rpc/request/+`, QoS 1) |

`product_key` looks like `1_18ec3b61229`. `request_id` is any 32-hex string. All payloads are compact JSON. Both sides publish with QoS 1.

## Startup sequence

Until each request is answered the stick repeats it every ~16 s and sends no data.

### 1. Sub-device registration

```json
{"method":"thing.event.stickUp.post",
 "params":{"funcKey":"sub.device.register",
           "data":{"parentDeviceId":"<stick_id>","identifier":"<inverter SN>",
                   "deviceType":"inverter","productCode":"SXFN","modelCode":"16"}},
 "traceId":"<uuid>","deviceId":"<stick_id>","version":"1.0.0","localDateTime":"2026-11-20T21:57:22"}
```

Reply (on `rpc/request/<id>`, same `traceId`):

```json
{"traceId":"<same>","requestId":"<id>","method":"thing.service.stickDownCmd",
 "params":{"funcKey":"sub.device.register.response",
           "body":{"msg":"Success","code":"000200",
                   "data":{"identifier":"<inverter SN>","deviceSecret":null,"deviceId":"<inverter id>"}}},
 "needToCache":false}
```

`deviceId` is the id the stick will use as `mainDeviceId` from now on; the cloud uses a 19-digit snowflake, any string works locally.

### 2. Time sync

```json
{"method":"thing.event.stickUp.post","params":{"funcKey":"stick.time.sync.request"}, ...}
```

Reply `funcKey: "stick.time.sync.response"`, `body: {"data":{"currentTime":"2026-11-20T22:01:45.827"}}` (local time, no zone).

### 3. Firmware check (shortly after)

`funcKey: "ota.upgrade.request"` → reply `funcKey: "ota.upgrade.response"`, `body: {"data":{"hasUpdate":false}}`.

### Status (no reply needed)

```json
{"method":"thing.event.stickUp.post",
 "params":{"funcKey":"stick.status",
           "data":{"networkConnectWay":"WLAN","ssid":"...","signalStrength":-46,
                   "deviceIdentifier":"<inverter SN>","dataCollectionCycle":0.1,"dataUploadCycle":5}}, ...}
```

## Modbus passthrough (the useful part)

Request (`rpc/request/<id>`):

```json
{"traceId":"<hex>","requestId":"<id>","method":"thing.service.down",
 "params":{"cmds":["01034104000A9030","0103411300056030"],"executeId":"1350779813154607104"},
 "needToCache":false}
```

`cmds` are complete Modbus RTU frames (slave 1, CRC included) as upper-case hex. Reads (0x03) and writes (0x10, the app always writes whole blocks) both work. Answer:

```json
{"method":"thing.event.up.post",
 "params":{"mainDeviceId":"<inverter id>","localDateTime":"2026-11-20T22:08:11",
           "content":[{"cmd":"01034104000A9030","data":"010314000000140005000401C601A80244022B01DC02209629"}, ...],
           "executeId":"1350779813154607104"},
 "traceId":"...","deviceId":"<stick_id>","version":"1.0.0"}
```

`data` is the raw RTU answer from the inverter. The stick executes the list sequentially, roughly 0.5 s per frame on the LAN:

| Request | Round trip |
|---|---|
| 1 frame (4 registers) | ~0.8 s |
| 3 frames (92 + 16 + 15 registers) | ~2.2–2.8 s |
| 8 frames (live + settings) | ~4.3 s |

Spans up to at least 92 registers in one frame are accepted (same limits as over BLE: the inverter rejects reads crossing unmapped addresses).

## Periodic upload

Every `dataUploadCycle` minutes (5 by default) the stick publishes `thing.event.up.post` **without** `executeId`, with 17 fixed reads (`0x0000`+10 … `0x0275`+8). After a disconnect it replays buffered uploads with their original `localDateTime`.

## Register map

Same as the BLE project — see [wattseek-ble/PROTOCOL.md](https://github.com/dimagord/wattseek-ble/blob/main/PROTOCOL.md) and `registers.py` / `settings.py` here.
