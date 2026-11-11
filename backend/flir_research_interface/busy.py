"""One answer to "is the operator busy?", used before anything that would interrupt it.

A restart, redeploy or drive unmount must not land mid-recording, mid-arm, mid-control-loop, or
while background work (move, export, render) is running. On 2026-10-27 an operator restart killed
post-stop exports that "recording idle" had missed, so background tasks are counted too.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BusyInputs:
    recording: bool
    finalizing: bool
    armed: bool
    control_engaged: bool
    running_jobs: tuple[str, ...]
    background_tasks: int


def busy_reasons(i: BusyInputs) -> list[str]:
    """Human-readable reasons the operator is busy, in a fixed order; empty when idle."""
    reasons: list[str] = []
    if i.recording:
        reasons.append("recording")
    if i.finalizing:
        reasons.append("finishing a recording")
    if i.armed:
        reasons.append("armed trigger")
    if i.control_engaged:
        reasons.append("closed-loop control engaged")
    reasons.extend(i.running_jobs)
    if i.background_tasks > 0:
        reasons.append(f"{i.background_tasks} background task(s)")
    return reasons


def job_labels(jobs: Mapping[str, Mapping[Any, Mapping[str, Any]]]) -> list[str]:
    """Labels for every running job: ``"<kind> <key>"``, or ``"smart <run key> <roi id>"`` for the
    tuple keys of smart_jobs (the roi id is an int, so keys are stringified, not joined)."""
    out: list[str] = []
    for kind, entries in jobs.items():
        for key, job in list(entries.items()):
            if job.get("state") != "running":
                continue
            label = " ".join(str(k) for k in key) if isinstance(key, tuple) else str(key)
            out.append(f"{kind} {label}")
    return out


__all__ = ["BusyInputs", "busy_reasons", "job_labels"]
