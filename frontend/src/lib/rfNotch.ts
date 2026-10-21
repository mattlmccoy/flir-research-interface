/** What the operator's RF-banding filter did to a frame (header ``display.rf_notch``). */
export type RfNotchInfo =
  | { applied: true; bands: string[]; rms_mk: number; max_mk: number;
      /** Patches seen but left alone because their banding is weaker than the camera noise. */
      below_noise?: string[]; banding_mk?: number; noise_mk?: number }
  | { applied: false; reason: string };

/**
 * The status line under the "remove RF banding" switch. It always says what actually happened
 * (removed how much / found nothing / not available), never just "on".
 */
export function rfNotchStatus(on: boolean, info: RfNotchInfo | undefined): string | null {
  if (!on) return null;
  if (!info) return "waiting for filtered frames…";
  if (!info.applied) return `not available: ${info.reason}`;
  if (info.bands.length === 0) {
    if (info.below_noise?.length && info.banding_mk !== undefined && info.noise_mk !== undefined) {
      return `RF banding below camera noise: not filtered (${Math.round(info.banding_mk)} vs ${Math.round(info.noise_mk)} mK)`;
    }
    return "no RF banding found";
  }
  const n = info.bands.length;
  return `removed RF banding · ${Math.round(info.rms_mk)} mK rms (${n} band${n > 1 ? "s" : ""})`;
}
