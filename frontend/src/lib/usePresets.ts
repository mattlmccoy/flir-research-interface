// The operator's preset document (`/api/presets`) held in React state. Every change goes to the
// operator and the returned document replaces the local copy, so the list always shows what is
// stored. Errors are thrown to the caller (the picker shows them).
import { useCallback, useEffect, useState } from "react";
import { api } from "./api.ts";
import type { Preset, PresetsDoc } from "./presets.ts";

export interface PresetsStore {
  /** null until the first load answers (or when it failed: see `loadError`). */
  doc: PresetsDoc | null;
  loadError: string | null;
  /** The stored preset `last_applied` names, or null. */
  lastApplied: Preset | null;
  reload: () => Promise<void>;
  put: (p: Preset) => Promise<void>;
  rename: (name: string, newName: string) => Promise<void>;
  remove: (name: string) => Promise<void>;
  markApplied: (name: string | null) => Promise<void>;
}

export function usePresets(): PresetsStore {
  const [doc, setDoc] = useState<PresetsDoc | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try { setDoc(await api.presets()); setLoadError(null); } catch (e) { setLoadError(String(e)); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  const lastApplied = doc?.presets.find((p) => p.name === doc.last_applied) ?? null;
  return {
    doc,
    loadError,
    lastApplied,
    reload,
    put: async (p) => { setDoc(await api.putPreset(p)); },
    rename: async (name, newName) => { setDoc(await api.renamePreset(name, newName)); },
    remove: async (name) => { setDoc(await api.deletePreset(name)); },
    markApplied: async (name) => { setDoc(await api.setLastAppliedPreset(name)); },
  };
}
