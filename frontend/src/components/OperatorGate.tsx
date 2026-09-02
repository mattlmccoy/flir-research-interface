import { CredentialsHelp } from "./CredentialsHelp.tsx";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { SITE_MODE, api, operatorBase, setOperatorBase, type Health } from "../lib/api.ts";
import { UI_API_VERSION, checkHandshake, type Handshake } from "../lib/operator.ts";
import { TELEDYNE_SDK, detectPlatform, installSteps, type Platform } from "../lib/platform.ts";

const DOCS = "https://github.com/mattlmccoy/flir-research-interface/blob/main/docs/installation.md";
const POLL_MS = 2000;

/**
 * Site mode only (spec §6.2/§6.3): until a local operator answers /api/health, show the
 * first-run page (install the operator for this platform, or point at a running one). Once it
 * answers, check the API handshake and render the normal UI against it.
 */
function CommandBox({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(command); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* selection fallback below */ }
  };
  return (
    <div className="row" style={{ alignItems: "stretch" }}>
      <input type="text" readOnly value={command} onFocus={(e) => e.currentTarget.select()} aria-label="install command"
        style={{ flex: 1, minWidth: 320, fontFamily: "var(--font-mono)", fontSize: 12 }} />
      <button className="primary" onClick={copy}>{copied ? "copied ✓" : "copy"}</button>
    </div>
  );
}

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

  const inst = installSteps(platform);
  return (
    <div className="page-body">
      <div className="card">
        <h2>FLIR Research Interface · {health ? "operator incompatible" : "set up this computer"}</h2>
        {hs?.level === "refuse" && <div className="errbox">{hs.message}</div>}
        <div className="muted">
          This website is the whole user interface. It talks to a small <b>operator</b> service on the computer the camera is plugged into.
          {!health && <> None is answering at <code>{base}</code>{tries > 0 ? ` (checked ${tries}×)` : ""}; this page keeps checking every 2 s and continues by itself.</>}
        </div>
        <div className="hint" style={{ marginTop: 10 }}><b>One command installs everything on this {platform === "windows" ? "PC" : platform === "linux" ? "machine" : "Mac"}</b> — paste it into {inst.shell}:</div>
        {inst.command && <CommandBox command={inst.command} />}
        <ol className="help" style={{ marginTop: 8 }}>
          {inst.steps.map((st, i) => <li key={i}>{st}</li>)}
        </ol>
        <div className="hint" style={{ marginTop: 6 }}>The installer will ask for the camera IP and, for the visible camera, the RTSP user and password. Have them ready:</div>
        <CredentialsHelp />
        <div className="row" style={{ marginTop: 6 }}>
          <a className="dl" href={DOCS} target="_blank" rel="noreferrer">full installation guide</a>
          <a className="dl" href={TELEDYNE_SDK} target="_blank" rel="noreferrer">Spinnaker SDK download page (Teledyne, free account)</a>
          <a className="dl" href={base} target="_blank" rel="noreferrer">already installed? open the local copy</a>
        </div>
      </div>
      <div className="card">
        <h2>Operator address</h2>
        <div className="row">
          <input type="text" value={base} style={{ width: 260 }} onChange={(e) => setBase(e.target.value)} aria-label="Operator base URL" />
          <button className="secondary" onClick={() => { setOperatorBase(base); setBase(operatorBase()); setTries(0); }}>use</button>
          <span className="muted">default http://localhost:8000</span>
        </div>
      </div>
    </div>
  );
}
