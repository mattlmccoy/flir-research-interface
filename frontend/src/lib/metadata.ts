/** Field parsing for post-hoc metadata edits (mirrors how RecordPanel types values). */

const NUMBER = /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/;

/** Numeric strings become numbers, blank means "delete this key" (null), anything else is text. */
export function parseValue(raw: string): number | string | null {
  const s = raw.trim();
  if (s === "") return null;
  return NUMBER.test(s) ? Number(s) : s;
}
