# Camera network setup

## How the A70 is reached

The A70 is a GigE Vision device: control over UDP port 3956 (GVCP), image stream over UDP
(GVSP). Discovery is a UDP broadcast, so a camera on the *wrong* subnet still answers a raw
discovery request, but Spinnaker (like every GenICam stack) only lists cameras whose IP is
inside one of the host adapter's subnets. **"0 cameras detected" while the camera is powered
almost always means a subnet mismatch, not a dead camera.**

`fri-probe` now runs an SDK-independent discovery broadcast whenever Spinnaker finds nothing,
and prints each answering camera, its IP configuration, and the exact host command to fix it.

## The situation found on 2026-09-01 (development Mac)

| Side | Address | Source |
|---|---|---|
| Camera (FLIR A70, fw 42.0.0) | `192.168.7.2/24`, persistent IP on, DHCP off, LLA on, no gateway | GVCP DISCOVERY_ACK |
| Host adapter `en13` ("USB 10/100/1000 LAN") | `169.254.168.103/16` (link-local fallback after DHCP found no server) | `ifconfig`, `networksetup -getinfo` |
| Spinnaker `GetInterfaces()` | listed only Wi-Fi (`10.90.70.74`) and loopback; did **not** list `en13` | probe log |

Result: Spinnaker reported 0 cameras. The camera was reachable the whole time.

## Fix: put the host adapter on the camera's subnet (recommended)

This changes only the host, not the camera, and is reversible.

macOS (needs an administrator password):

```bash
sudo networksetup -setmanual "USB 10/100/1000 LAN" 192.168.7.1 255.255.255.0
```

Revert later with `sudo networksetup -setdhcp "USB 10/100/1000 LAN"`. The service name is the
one shown by `networksetup -listallhardwareports` for the adapter the camera is plugged into.

Linux: `sudo ip addr add 192.168.7.1/24 dev <iface>` (or set a static IPv4 in NetworkManager).

Windows (admin prompt): `netsh interface ip set address "<adapter name>" static 192.168.7.1 255.255.255.0`

Then verify:

```bash
ping -c 2 192.168.7.2
cd backend && uv run fri-probe --output-dir ../probe_output_a70
```

## Alternative: change the camera's IP (not done automatically)

Spinnaker's SpinView "Force IP"/persistent-IP settings, or the camera web UI, can move the
camera to the host's subnet. The application never does this on its own (brief §7); it only
tells the user how.

## Other requirements

* Power: PoE (IEEE 802.3af class 3) or 24/48 V DC.
* Jumbo frames (MTU 9000) on the camera-facing adapter for stable 30 Hz Mono16 streaming
  (Spinnaker README §3.1). Not required for the probe.
* Firewall: allow inbound UDP on the camera adapter (GVCP 3956 replies, GVSP stream). The
  development Mac's application firewall was off.
* A dedicated adapter for the camera is strongly preferred over sharing the campus/Wi-Fi network.
