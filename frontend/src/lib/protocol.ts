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
  const counts = new Uint16Array(expected);
  const off = 4 + n;
  for (let i = 0; i < expected; i++) counts[i] = view.getUint16(off + i * 2, true);
  return { header, counts };
}
