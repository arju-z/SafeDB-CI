"""
engine/reporter.py — Structured Pipeline Report (Phase Output Layer)

PURPOSE:
Accumulates the result of each pipeline phase into a single `PipelineReport`
object, then emits it in the requested format:
  - text:  human-readable console output (replaces ad-hoc print() calls)
  - json:  machine-readable JSON file and GitHub Actions step summary

WHY A SEPARATE REPORTER:
Previously, each phase printed directly to stdout in cli.py. This tightly
coupled output formatting to business logic. The reporter decouples them:
  - Phases set results on the report object.
  - The reporter decides how to display them.
  - Adding a new output format (e.g. Slack webhook) requires only a new
    emit function, not changes to every phase.

GITHUB ACTIONS STEP SUMMARY:
When the env var GITHUB_STEP_SUMMARY is set (always present in GitHub Actions),
the reporter additionally writes a formatted Markdown table to that file.
GitHub renders this table directly in the PR checks UI.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ── Phase status enum ─────────────────────────────────────────────────────────

class PhaseStatus(Enum):
    PASS    = "pass"
    FAIL    = "fail"
    SKIPPED = "skipped"
    PENDING = "pending"


# ── Phase result dataclass ────────────────────────────────────────────────────

@dataclass
class PhaseResult:
    """
    Result of a single pipeline phase.

    Attributes:
        status:  PASS, FAIL, SKIPPED, or PENDING.
        detail:  Optional human-readable summary line (e.g. "6 migrations loaded").
        extras:  Arbitrary key-value data for the JSON report (violations list, etc.)
    """
    status: PhaseStatus = field(default=PhaseStatus.PENDING)
    detail: Optional[str] = field(default=None)
    extras: dict[str, Any] = field(default_factory=dict)


# ── Pipeline report ───────────────────────────────────────────────────────────

@dataclass
class PipelineReport:
    """
    Accumulates the results of all pipeline phases.

    Populated incrementally by cli.py as each phase completes.
    Passed to emit() at the end regardless of exit code.
    """
    db_type: str = ""
    migrations_path: str = ""
    dry_run: bool = False

    ordering:             PhaseResult = field(default_factory=PhaseResult)
    tamper_check:         PhaseResult = field(default_factory=PhaseResult)
    safety:               PhaseResult = field(default_factory=PhaseResult)
    execution:            PhaseResult = field(default_factory=PhaseResult)
    introspection:        PhaseResult = field(default_factory=PhaseResult)
    structural_validation: PhaseResult = field(default_factory=PhaseResult)
    naming_heuristics:    PhaseResult = field(default_factory=PhaseResult)
    lockfile:             PhaseResult = field(default_factory=PhaseResult)

    exit_code: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def phases(self) -> dict[str, PhaseResult]:
        """Return all phases in pipeline order for iteration."""
        return {
            "ordering":              self.ordering,
            "tamper_check":          self.tamper_check,
            "safety":                self.safety,
            "execution":             self.execution,
            "introspection":         self.introspection,
            "structural_validation": self.structural_validation,
            "naming_heuristics":     self.naming_heuristics,
            "lockfile":              self.lockfile,
        }


# ── Emoji helpers ─────────────────────────────────────────────────────────────

_STATUS_EMOJI = {
    PhaseStatus.PASS:    "✅",
    PhaseStatus.FAIL:    "❌",
    PhaseStatus.SKIPPED: "⏭",
    PhaseStatus.PENDING: "⏳",
}

_STATUS_LABEL = {
    PhaseStatus.PASS:    "pass",
    PhaseStatus.FAIL:    "fail",
    PhaseStatus.SKIPPED: "skipped",
    PhaseStatus.PENDING: "pending",
}


# ── JSON emission ─────────────────────────────────────────────────────────────

def _build_json_payload(report: PipelineReport) -> dict:
    """Build the JSON-serialisable dict from the report."""
    phases_dict: dict[str, Any] = {}
    for phase_name, result in report.phases().items():
        phases_dict[phase_name] = {
            "status": _STATUS_LABEL[result.status],
            **({"detail": result.detail} if result.detail else {}),
            **result.extras,
        }

    return {
        "safedb_version": "2.0.0",
        "db_type": report.db_type,
        "migrations_path": report.migrations_path,
        "dry_run": report.dry_run,
        "exit_code": report.exit_code,
        "phases": phases_dict,
        "timestamp": report.timestamp,
    }


def emit_json(report: PipelineReport, output_path: Path) -> None:
    """
    Write the pipeline report as a JSON file at `output_path`.

    WHY ALWAYS WRITE (even on failure): The report is most useful for
    debugging failures. Log shipping tools (Loki, Splunk) need the file
    regardless of exit code.
    """
    payload = _build_json_payload(report)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"Report written to: {output_path}")


# ── GitHub Actions step summary ───────────────────────────────────────────────

def emit_github_summary(report: PipelineReport) -> None:
    """
    Write a Markdown-formatted step summary to $GITHUB_STEP_SUMMARY.

    GitHub Actions renders this as a formatted table directly in the PR
    checks UI — no external log viewer required.

    This function is a no-op when GITHUB_STEP_SUMMARY is not set (i.e.
    outside of GitHub Actions). Safe to call unconditionally.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines: list[str] = [
        "## 🛡️ SafeDB-CI Report\n",
        f"**Database:** `{report.db_type}` | "
        f"**Path:** `{report.migrations_path}` | "
        f"**Dry run:** `{report.dry_run}`\n",
        "",
        "### Pipeline Phases",
        "",
        "| Phase | Status | Detail |",
        "|-------|--------|--------|",
    ]

    phase_labels = {
        "ordering":               "1. Ordering",
        "tamper_check":           "1b. Tamper Check",
        "safety":                 "2. Safety Scan",
        "execution":              "3. Execution",
        "introspection":          "4. Introspection",
        "structural_validation":  "5a. Structural Validation",
        "naming_heuristics":      "5b. Naming Heuristics",
        "lockfile":               "6. Lockfile",
    }

    for phase_key, result in report.phases().items():
        emoji = _STATUS_EMOJI[result.status]
        label = phase_labels.get(phase_key, phase_key)
        detail = result.detail or "—"
        lines.append(f"| {label} | {emoji} {_STATUS_LABEL[result.status]} | {detail} |")

    # Add violations block if any phase failed.
    all_violations: list[dict] = []
    for result in report.phases().values():
        all_violations.extend(result.extras.get("violations", []))

    if all_violations:
        lines += [
            "",
            "### Violations",
            "",
            "| Severity | File | Rule | Detail |",
            "|----------|------|------|--------|",
        ]
        for v in all_violations:
            sev = v.get("severity", "?")
            fname = v.get("file", "?")
            rule = v.get("rule", "?")
            detail = v.get("detail", "—")
            lines.append(f"| `{sev}` | `{fname}` | {rule} | {detail} |")

    overall = "✅ **PASSED**" if report.exit_code == 0 else "❌ **FAILED**"
    lines += ["", f"**Result:** {overall}", ""]

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ── Console emission ──────────────────────────────────────────────────────────

def emit_console_summary(report: PipelineReport) -> None:
    """
    Print a compact phase summary to stdout at the end of a run.
    Only shown when --output json is active (to complement the JSON file).
    In text mode, phases print their own output inline and this is redundant.
    """
    print("\n── SafeDB-CI Phase Summary ──────────────────")
    for phase_key, result in report.phases().items():
        if result.status == PhaseStatus.PENDING:
            continue
        emoji = _STATUS_EMOJI[result.status]
        label = phase_key.replace("_", " ").title()
        detail = f"  {result.detail}" if result.detail else ""
        print(f"  {emoji} {label}{detail}")
    print("─────────────────────────────────────────────")
