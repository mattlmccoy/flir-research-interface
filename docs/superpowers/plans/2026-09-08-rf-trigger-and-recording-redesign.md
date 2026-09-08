# RF-triggered recording + recording-section redesign

**Decisions (Matt):** Unify RF-start into the armed-trigger panel and retire the Setup §6 auto-start
toggle. UX: split Record-now vs Arm, simplify the trigger form, clearer armed/recording status,
surface RF link state in the panel.

## Phases
- [x] P1 backend trigger: add start kind `rf` + end kind `rf` (rf-off) to `recording/trigger.py`
      (external event, never fires from a frame). `Armer.signal_rf(on)` mirrors `manual_start`. TDD.
- [x] P2 backend wiring (`api/app.py`): route `POST /api/rf-link/event` on→armer.signal_rf(True),
      off→signal_rf(False); RF-start now ONLY via an armed `rf` trigger. Keep the timeline MARK on
      every event. Retire `auto_start_on_rf_on` from rf-link settings. TDD (endpoint).
- [x] P3 frontend model (`lib/trigger.ts` + test): add `rf` start/end kinds, form fields, summary
      text ("start when RF turns on"). TDD.
- [~] P4 frontend UX (partial): ArmPanel adds "on RF signal" start option; RecordPanel splits Record-now vs
      Arm with clear state; RF link status shown in the panel; trigger form simplified (advanced
      behind a toggle). Retire the Setup §6 auto-start checkbox (keep the last-event display).
      Browser-verify against the live operator.

## Notes
- `manual_start()` in arm.py is the pattern for external start injection; `signal_rf` is the same
  under the lock, gated on `spec.start.kind == "rf"` / `spec.end.kind == "rf"`.
- Pre-trigger ring already applies to any start path, so RF-start gets pre-trigger for free.
- rf-link event still marks the timeline while recording (unchanged); only START/STOP move to the
  armer.
