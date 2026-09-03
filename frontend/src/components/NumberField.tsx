import { useState, type InputHTMLAttributes } from "react";
import { commitDraft } from "../lib/numfield.ts";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
  value: number | null | undefined;
  /** Called only when the field holds a valid number; a cleared field does not force a value. */
  onChange: (n: number) => void;
  /** Shown when value is null/undefined (e.g. "camera"). */
  placeholder?: string;
};

/** A controlled numeric input that can be fully cleared while typing (fixes the "stuck 0" bug).
 * While focused it shows exactly what you type; on blur it snaps back to the canonical value. */
export function NumberField({ value, onChange, onBlur, ...rest }: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value === null || value === undefined || !Number.isFinite(value) ? "" : String(value));
  return (
    <input
      type="number"
      {...rest}
      value={shown}
      onChange={(e) => { setDraft(e.target.value); const n = commitDraft(e.target.value); if (n !== null) onChange(n); }}
      onBlur={(e) => { setDraft(null); onBlur?.(e); }}
    />
  );
}
