"""
Levey-Jennings control chart with Westgard rules.

Rules implemented (standard analytical chemistry / ISO 17025 QC)
-----------------------------------------------------------------
1₃s  : 1 point beyond ±3s  → reject (random error or large systematic)
2₂s  : 2 consecutive points beyond ±2s on the same side → reject (systematic)
R₄s  : range between 2 consecutive points > 4s → reject (random error)
4₁s  : 4 consecutive points beyond ±1s on the same side → warning (systematic)
10ₓ  : 10 consecutive points on same side of mean → warning (systematic bias)

Reference: Westgard JO et al., Clin Chem 27:493-501 (1981)
           ISO 17511:2003 §8  (metrological traceability in laboratory medicine)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd


Severity = Literal["reject", "warning"]


@dataclass(frozen=True)
class Violation:
    rule: str          # e.g. "1_3s", "2_2s"
    index: int         # position in the series (0-based)
    value: float
    z_score: float
    severity: Severity
    description: str


@dataclass
class ControlChartResult:
    mean: float
    sd: float
    n: int
    violations: list[Violation] = field(default_factory=list)
    status: Literal["in_control", "warning", "out_of_control"] = "in_control"

    def summary(self) -> dict:
        return {
            "mean": self.mean,
            "sd": self.sd,
            "n": self.n,
            "n_violations": len(self.violations),
            "status": self.status,
            "violations": [
                {"rule": v.rule, "index": v.index, "severity": v.severity}
                for v in self.violations
            ],
        }


def westgard_rules(
    values: list[float] | np.ndarray,
    *,
    mean: float | None = None,
    sd: float | None = None,
) -> ControlChartResult:
    """
    Apply Westgard multi-rules to a sequence of QC measurements.

    Parameters
    ----------
    values : sequence of floats — QC readings in time order
    mean   : target/reference mean (default: sample mean)
    sd     : target/reference SD  (default: sample SD, ddof=1)

    Returns
    -------
    ControlChartResult with all detected violations.
    """
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < 2:
        raise ValueError("Need at least 2 values for control chart analysis.")

    mu = float(mean) if mean is not None else float(np.mean(arr))
    sigma = float(sd) if sd is not None else float(np.std(arr, ddof=1))
    if sigma == 0.0:
        raise ValueError("SD is zero — cannot compute z-scores.")

    z = (arr - mu) / sigma
    violations: list[Violation] = []

    # ── 1₃s: any single point |z| > 3 ────────────────────────────────────────
    for i in range(n):
        if abs(z[i]) > 3.0:
            violations.append(Violation(
                rule="1_3s", index=i, value=float(arr[i]), z_score=float(z[i]),
                severity="reject",
                description=f"Point {i} at z={z[i]:.2f} exceeds ±3s limit",
            ))

    # ── 2₂s: 2 consecutive points on same side beyond ±2s ─────────────────────
    for i in range(n - 1):
        if z[i] > 2.0 and z[i + 1] > 2.0:
            violations.append(Violation(
                rule="2_2s", index=i + 1, value=float(arr[i + 1]), z_score=float(z[i + 1]),
                severity="reject",
                description=f"Points {i}–{i+1} both exceed +2s",
            ))
        elif z[i] < -2.0 and z[i + 1] < -2.0:
            violations.append(Violation(
                rule="2_2s", index=i + 1, value=float(arr[i + 1]), z_score=float(z[i + 1]),
                severity="reject",
                description=f"Points {i}–{i+1} both below −2s",
            ))

    # ── R₄s: range of 2 consecutive points > 4s ───────────────────────────────
    for i in range(n - 1):
        r = abs(z[i + 1] - z[i])
        if r > 4.0:
            violations.append(Violation(
                rule="R_4s", index=i + 1, value=float(arr[i + 1]), z_score=float(z[i + 1]),
                severity="reject",
                description=f"Range z[{i}]→z[{i+1}] = {r:.2f} > 4s",
            ))

    # ── 4₁s: 4 consecutive points beyond ±1s same side ────────────────────────
    for i in range(n - 3):
        window = z[i:i + 4]
        if np.all(window > 1.0) or np.all(window < -1.0):
            side = "+" if window[0] > 0 else "−"
            violations.append(Violation(
                rule="4_1s", index=i + 3, value=float(arr[i + 3]), z_score=float(z[i + 3]),
                severity="warning",
                description=f"Points {i}–{i+3} all beyond {side}1s",
            ))

    # ── 10ₓ: 10 consecutive points on same side of mean ───────────────────────
    for i in range(n - 9):
        window = z[i:i + 10]
        if np.all(window > 0) or np.all(window < 0):
            side = "above" if window[0] > 0 else "below"
            violations.append(Violation(
                rule="10x", index=i + 9, value=float(arr[i + 9]), z_score=float(z[i + 9]),
                severity="warning",
                description=f"Points {i}–{i+9} all {side} mean",
            ))

    # ── Overall status ─────────────────────────────────────────────────────────
    if any(v.severity == "reject" for v in violations):
        status = "out_of_control"
    elif violations:
        status = "warning"
    else:
        status = "in_control"

    return ControlChartResult(mean=mu, sd=sigma, n=n, violations=violations, status=status)


def annotate_dataframe(
    df: pd.DataFrame,
    value_col: str,
    *,
    mean: float | None = None,
    sd: float | None = None,
    group_col: str | None = None,
) -> pd.DataFrame:
    """
    Add Westgard annotation columns to a DataFrame.

    Adds: z_score, violation_rule (first rule triggered, or None), status.
    If group_col is given, runs the analysis independently per group.
    """
    if group_col:
        chunks = []
        for _, g in df.groupby(group_col, sort=False):
            chunks.append(annotate_dataframe(g, value_col, mean=mean, sd=sd))
        return pd.concat(chunks).reset_index(drop=True)

    arr = df[value_col].to_numpy(dtype=float)
    result = westgard_rules(arr, mean=mean, sd=sd)

    z = (arr - result.mean) / result.sd
    violation_map: dict[int, str] = {}
    for v in result.violations:
        if v.index not in violation_map:
            violation_map[v.index] = v.rule

    out = df.copy()
    out["z_score"]       = np.round(z, 4)
    out["violation_rule"] = [violation_map.get(i) for i in range(len(arr))]
    out["qc_status"]     = out["violation_rule"].apply(
        lambda r: "out_of_control" if r in ("1_3s", "2_2s", "R_4s")
        else ("warning" if r in ("4_1s", "10x") else "in_control")
    )
    return out
