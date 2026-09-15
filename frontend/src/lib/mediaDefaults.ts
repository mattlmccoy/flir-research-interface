// Sensible default file-size cap per export format.
//
// A GIF has no inter-frame compression and thermal gradients compress terribly in its 256-colour
// palette, so an uncapped GIF balloons (100+ MB) while the same clip as H.264 MP4 is under a
// megabyte. Default a GIF to a cap it fills toward at the best resolution that fits; leave MP4
// uncapped. Only the paired auto-defaults are swapped, so an explicit user choice is preserved.

export const GIF_DEFAULT_MB = 25; // "even a 25 MB GIF looks great"; fills toward it at best res

export function defaultMaxMbForFormat(fmt: "mp4" | "gif", currentMb: number): number {
  if (fmt === "gif") return currentMb === 0 ? GIF_DEFAULT_MB : currentMb;
  return currentMb === GIF_DEFAULT_MB ? 0 : currentMb;
}
