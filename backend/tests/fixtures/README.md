# Test fixtures

`discovery_ack_redacted.bin` — a real GigE Vision GVCP DISCOVERY_ACK (256 bytes) captured from a
FLIR A70 (firmware 42.0.0) on 2026-09-01 with a raw UDP broadcast to port 3956. The 16-byte serial
number field (payload offset 216) was overwritten with `00000000`; every other byte is as received.
