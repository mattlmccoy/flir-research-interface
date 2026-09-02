import type { ReactNode } from "react";

interface Props { title: string; open: boolean; onToggle: () => void; tag?: string; children: ReactNode; }

export function RailSection({ title, open, onToggle, tag, children }: Props) {
  return (
    <section className="rail-section">
      <button type="button" className="sec-head" aria-expanded={open} onClick={onToggle}>
        <span>{title}</span>
        {tag && <span className="tag">{tag}</span>}
        <span className="chev">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="body">{children}</div>}
    </section>
  );
}
