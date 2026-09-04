/** Decoder for the backend's frame message (see backend api/frames.py). */
export interface FrameHeader {
  type: "frame";
  frame_id: number;
  device_timestamp_ns: number;
  host_timestamp_ns: number;
  width: number;
  height: number;
  dtype: "uint16";
  byte_order: "little";
  pixel_format: string;
  ir_format: string;
  kelvin_per_count: number | null;
  kelvin_offset: number;
  min_c: number | null;
  max_c: number | null;
  mean_c: number | null;
  center_c: number | null;
  /** Number of over-range (saturated / wrapped) pixels excluded from the stats, if any. */
  over_range?: number;
  incomplete: boolean;
  camera_fps?: number | null;
  viz_dropped?: number;
  frames_received?: number;
  state?: string;
}

export interface FrameMessage {
  header: FrameHeader;
  counts: Uint16Array;
}

export function decodeFrameMessage(buf: ArrayBuffer): FrameMessage {
  const view = new DataView(buf);
  const n = view.getUint32(0, false);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, n))) as FrameHeader;
  const expected = header.width * header.height;
  const bytes = buf.byteLength - 4 - n;
  if (bytes !== expected * 2) {
    throw new Error(`payload size ${bytes} does not match ${header.width}x${header.height} uint16`);
  }
  const off = 4 + n;
  // Little-endian on every platform this runs on: view the payload as Uint16 directly.
  // Typed-array views need 2-byte alignment, so copy when the header length makes `off` odd.
  const counts = off % 2 === 0
    ? new Uint16Array(buf.slice(off, off + expected * 2))
    : new Uint16Array(new Uint8Array(buf, off, expected * 2).slice().buffer);
  return { header, counts };
}

/** Split a block body of repeated [uint32 length][frame message] into decoded frames. */
export function decodeFrameBlock(buf: ArrayBuffer): FrameMessage[] {
  const view = new DataView(buf);
  const out: FrameMessage[] = [];
  let off = 0;
  while (off + 4 <= buf.byteLength) {
    const len = view.getUint32(off, false);
    off += 4;
    out.push(decodeFrameMessage(buf.slice(off, off + len)));
    off += len;
  }
  return out;
}
