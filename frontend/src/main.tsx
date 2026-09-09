import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { OperatorGate } from "./components/OperatorGate.tsx";
import { SITE_MODE } from "./lib/api.ts";
import "./theme.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <OperatorGate>
      <App />
    </OperatorGate>
  </React.StrictMode>,
);

// Offline fallback (spec §6.4): on the Pages copy, a service worker serves a branded offline.html
// (pointing at the local operator) when a navigation fails with no internet. Only the site build
// registers it (SITE_MODE); the operator-served copy is already local. The browser only allows SW
// registration in a secure context (https or localhost), so no explicit protocol check is needed.
if (SITE_MODE && "serviceWorker" in navigator) {
  navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => undefined);
}
