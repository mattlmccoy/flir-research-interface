import { useState } from "react";
import type { ReactNode } from "react";

interface Props { label: string; children: ReactNode; defaultOpen?: boolean; icon?: "info" | "chevron"; }

/** Small collapsible block for help text: an ⓘ or ▸ toggle, closed by default so rails stay compact. */
export function Disclosure({ label, children, defaultOpen = false, icon = "chevron" }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`disclosure ${open ? "open" : ""}`}>
      <button type="button" className="disc-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="disc-icon" aria-hidden="true">{icon === "info" ? "ⓘ" : open ? "▾" : "▸"}</span>{label}
      </button>
      {open && <div className="disc-body">{children}</div>}
    </div>
  );
}
