import type { ReactNode } from "react";

interface Props { title: string; open: boolean; onToggle: () => void; tag?: string; children: ReactNode; }

export function RailSection({ title, open, onToggle, tag, children }: Props) {
  return (
    <section className="rail-section">
      <header onClick={onToggle} role="button" aria-expanded={open}>
        <span>{title}</span>
        {tag && <span className="tag">{tag}</span>}
        <span className="chev">{open ? "▾" : "▸"}</span>
      </header>
      {open && <div className="body">{children}</div>}
    </section>
  );
}
