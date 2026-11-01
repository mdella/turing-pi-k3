# SolarEdge inverter (local Modbus TCP)

A SolarEdge **SE7600A-US** (split-phase, 240 V) on the home LAN, read locally over Modbus TCP (SunSpec). It was a
self-install, so there is no installer account and no SolarEdge cloud site; everything here works without either.

_Added 2026-11-01._

## Network

| | |
|---|---|
| Switch port | `geekstyle-sw1` Ethernet13 (`LINK:: SolarEdge`), access VLAN 10, through a small local switch |
| Address | `192.168.1.213`, a Kea DHCPv4 reservation on OPNsense (hostname `solaredge`) |
| DNS | `solaredge.geekstyle.net` (Unbound on OPNsense registers Kea reservations; PTR included) |
| Cloud | Outbound TCP 22222 to SolarEdge (`167.94.110.1`), already connected; nothing inbound is forwarded |

A second MAC is also seen on Et13 (`a8:f7:e0:63:95:cc`), probably the small switch. It has no IPv4 address and has
never asked for DHCP.

## Inverter setup

The A-series has an LCD and does **not** need SetApp activation (that is only for the newer SetApp inverters).
Configuration is from the LCD menu, using the external **LCD light button**:

1. Turn the inverter **ON/OFF switch to OFF** (leave AC on so the screen stays powered).
2. Press and hold the LCD button until it shows *"Keep holding button for pairing, release to enter menu"*, then
   **release straight away** (holding on starts optimizer pairing).
3. Short press moves to the next item; a long press (~3 s) selects.
4. Modbus TCP: **Communication → LAN Conf → Modbus TCP → Enable** (port **502**, device ID 1).
5. Exit each level and turn the ON/OFF switch back to ON.

Firmware: CPU **3.2537** (shown on the LCD ID screen and in the SunSpec common block). A-series firmware is updated
from a microSD card on the communication board, or pushed remotely by SolarEdge support using the serial number
(the inverter connects to SolarEdge, so remote push works without a cloud site).

## Reading it

Modbus TCP, port 502, unit 1, holding registers from address 40000 (SunSpec). SolarEdge's documentation numbers
registers from 1, so register 40001 is address 40000. Values are scaled by the signed scale-factor register that
follows them (`value × 10^SF`).

| Register (1-based) | Meaning |
|---|---|
| 40001-40002 | `SunS` marker |
| 40005-40020 / 40021-40036 | manufacturer / model (text) |
| 40045-40052 / 40053-40068 | firmware version / serial (text) |
| 40070 | SunSpec model: 101 single-phase, 102 split-phase, 103 three-phase (this one: 102) |
| 40072 (SF 40076) | AC current |
| 40077, 40080 (SF 40083) | AC voltage L1-L2, L1-N |
| 40084 (SF 40085) | AC power, W |
| 40086 (SF 40087) | frequency |
| 40094-40095 (SF 40096) | lifetime energy, Wh (32-bit) |
| 40097 / 40099 / 40101 | DC current / voltage / power (SF 40098 / 40100 / 40102) |
| 40104 (SF 40107) | heatsink temperature |
| 40108 | status: 1 off, 2 sleeping, 3 starting, 4 MPPT (producing), 5 throttled, 6 shutting down, 7 fault, 8 standby |

First read (2026-11-01, evening): status 2 (sleeping), grid 246.3 V L1-L2 / 122.8 V L1-N at 59.99 Hz, lifetime
energy **53,574.6 kWh**, so the inverter has a long production history from before this install. Reading the meter
block at 40122 returns *illegal address*: no SolarEdge energy meter is attached.

Daylight read (2026-11-01, 12:17 local): status **4 (MPPT, producing)**, vendor status 0 (no fault). AC **1,687 W** at
247.6 V L1-L2 / 123.8 V L1-N, 6.84 A, 59.996 Hz; DC **1,713 W** at 375.5 V / 4.56 A (about 98.5 % conversion); heatsink
37.0 °C. Lifetime energy **53,584.68 kWh**, up 10.1 kWh since the evening read, so the inverter is producing and its
ON/OFF switch is back ON after the Modbus setup.

Caveats:

- **No authentication, and one Modbus TCP client at a time.** Keep it LAN-only, and have one poller republish the
  data (MQTT/InfluxDB) rather than several clients polling the inverter.
- Readings are zero while it sleeps; check production in daylight (status 4).

## Monitoring options (not deployed yet)

- [`solaredge_modbus`](https://github.com/nmakel/solaredge_modbus) (Python library, with InfluxDB examples).
- Home Assistant **SolarEdge Modbus Multi** (HACS custom integration).
- Telegraf `modbus` input → InfluxDB → Grafana, alongside the cluster's existing Grafana.
- mbmd (SunSpec → MQTT/InfluxDB); evcc if an EV charger is added.

For consumption as well as production: a SolarEdge energy meter on the inverter's RS485 (it then appears in the
inverter's Modbus map), or a separate CT monitor (IoTaWatt, Shelly Pro EM). CT clamps go inside the electrical panel.

A poller would run on the cluster; that waits until the network baseline is finished.
