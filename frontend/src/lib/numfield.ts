/** The number to commit for a raw input string, or null to leave the value unchanged
 * (empty field, a lone sign, or junk). Lets a controlled number input be fully cleared. */
export function commitDraft(raw: string): number | null {
  const s = raw.trim();
  if (s === "" || s === "-" || s === "+" || s === "." || s === "-." ) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}
