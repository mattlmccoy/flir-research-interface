import { useState } from "react";
import type { ConnectHint } from "../lib/connectHint.ts";

/** Why the camera can't connect, in plain words, with the fix command to copy and the raw error. */
export function ConnectHintBox({ hint }: { hint: ConnectHint }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    if (!hint.command) return;
    navigator.clipboard?.writeText(hint.command).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {});
  };
  return (
    <div className={`${hint.level === "err" ? "errbox" : "warnbox"} connect-hint`} role="alert">
      <div className="msg">{hint.message}</div>
      {hint.command && (
        <div className="cmd-row">
          <code className="cmd">{hint.command}</code>
          <button className="secondary" onClick={copy}>{copied ? "copied" : "copy"}</button>
        </div>
      )}
      {hint.raw && <div className="muted raw">Camera SDK said: {hint.raw}</div>}
    </div>
  );
}
