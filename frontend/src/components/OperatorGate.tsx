import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { SITE_MODE, api, operatorBase, setOperatorBase, type Health } from "../lib/api.ts";
import { UI_API_VERSION, checkHandshake, type Handshake } from "../lib/operator.ts";
import { detectPlatform, installerFor, type Platform } from "../lib/platform.ts";

const RELEASES = "https://github.com/mattlmccoy/flir-research-interface/releases/latest";
const POLL_MS = 2000;

/**
 * Site mode only (spec §6.2/§6.3): until a local operator answers /api/health, show the
 * first-run page (install the operator for this platform, or point at a running one). Once it
 * answers, check the API handshake and render the normal UI against it.
 */
export function OperatorGate({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [tries, setTries] = useState(0);
  const [base, setBase] = useState(operatorBase());
  const platform: Platform = detectPlatform(navigator.userAgent, navigator.platform);

  useEffect(() => {
    if (!SITE_MODE) return;
    let alive = true;
    const tick = async () => {
      try { const h = await api.health(); if (alive) setHealth(h); }
      catch { if (alive) { setHealth(null); setTries((n) => n + 1); } }
    };
    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, [base]);

  if (!SITE_MODE) return <>{children}</>;

  const hs: Handshake | null = health ? checkHandshake(UI_API_VERSION, health.api_version) : null;
  if (health && hs && hs.level !== "refuse") {
    return (
      <>
        {hs.level === "warn" && <div className="warnbox" role="status">{hs.message}</div>}
        {children}
      </>
    );
  }

  const inst = installerFor(platform);
  return (
    <div className="page-body">
      <div className="card">
        <h2>FLIR Research Interface · operator {health ? "incompatible" : "not detected"}</h2>
        {hs?.level === "refuse" && <div className="errbox">{hs.message}</div>}
        {!health && (
          <div className="muted">
            Looking for the operator at <code>{base}</code>{tries > 0 ? ` (${tries} attempts)` : ""}. The operator is the small local service that
            talks to the camera; this page keeps polling and continues automatically once it answers.
          </div>
        )}
        <div className="row" style={{ marginTop: 10 }}>
          <a className="dl" href={inst.url ?? RELEASES} target="_blank" rel="noreferrer">
            <button className="primary">Install operator · {inst.label}</button>
          </a>
          <a className="dl" href={base} target="_blank" rel="noreferrer">already installed? open the local copy</a>
        </div>
        <div className="hint" style={{ marginTop: 8 }}>{inst.note}</div>
      </div>
      <div className="card">
        <h2>Operator address</h2>
        <div className="row">
          <input type="text" value={base} style={{ width: 260 }} onChange={(e) => setBase(e.target.value)} aria-label="Operator base URL" />
          <button className="secondary" onClick={() => { setOperatorBase(base); setBase(operatorBase()); setTries(0); }}>use</button>
          <span className="muted">default http://localhost:8000</span>
        </div>
      </div>
      <div className="card">
        <h2>Manual route</h2>
        <div className="hint">
          Clone <code>github.com/mattlmccoy/flir-research-interface</code>, then <code>cd backend && uv sync --extra dev --inexact && uv run fri-serve --backend spinnaker</code>.
          The Spinnaker SDK and PySpin come from Teledyne (see docs/installation.md); the setup page checks them.
        </div>
      </div>
    </div>
  );
}
