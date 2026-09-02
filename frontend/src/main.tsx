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

// Offline mode (spec §6.4): the site caches its own shell so a machine that visited once can
// load the UI without internet; it still needs the local operator. The operator-served copy
// does not register a worker (it is already local).
if (SITE_MODE && "serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => undefined);
}
