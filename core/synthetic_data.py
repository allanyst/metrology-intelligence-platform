"""
Synthetic calibration data generator for MIP.

Instruments modelled
--------------------
XRF      : repeated intensity readings per element, optional linear drift.
HPLC     : peak-area calibration curve (n_levels × n_replicates), Gaussian noise.
Balance  : repeated weighings of a reference mass with bias + Laplace noise
           (robust to shock/vibration outliers, consistent with UQaaS model).

Each function returns a pandas DataFrame ready for Bronze ingestion.
All randomness is seeded for reproducibility.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


# ── XRF ───────────────────────────────────────────────────────────────────────

def generate_xrf_calibration(
    *,
    element: str = "Fe",
    true_value: float = 1000.0,   # counts per second (cps)
    u_rep: float = 5.0,           # repeatability std (normal)
    n_points: int = 30,
    drift_rate: float = 0.0,      # linear drift per measurement (cps/reading)
    outlier_fraction: float = 0.05,
    seed: int = 42,
    start: datetime | None = None,
) -> pd.DataFrame:
    """
    Simulate XRF intensity readings for a single element.

    Drift models detector aging or source decay. Outliers simulate
    sample contamination or detector saturation events.
    """
    rng = np.random.default_rng(seed)
    start = start or datetime(2026, 1, 1, 8, 0)

    idx = np.arange(n_points)
    signal = true_value + drift_rate * idx + rng.normal(0.0, u_rep, n_points)

    # inject outliers (3–5 σ spikes)
    n_out = max(1, int(n_points * outlier_fraction))
    out_idx = rng.choice(n_points, size=n_out, replace=False)
    signal[out_idx] += rng.choice([-1, 1], size=n_out) * rng.uniform(3, 5, n_out) * u_rep

    timestamps = [start + timedelta(minutes=10 * i) for i in range(n_points)]

    return pd.DataFrame({
        "instrument_id": f"XRF-001",
        "instrument_type": "XRF",
        "element": element,
        "reading": np.round(signal, 4),
        "nominal_value": true_value,
        "unit": "cps",
        "measured_at": timestamps,
        "batch_id": f"XRF-{element}-{start.strftime('%Y%m%d')}",
    })


# ── HPLC ──────────────────────────────────────────────────────────────────────

def generate_hplc_calibration(
    *,
    analyte: str = "caffeine",
    concentrations: list[float] | None = None,   # mg/L
    n_replicates: int = 3,
    sensitivity: float = 150.0,   # peak area per mg/L
    intercept: float = 200.0,     # baseline noise area
    rsd_pct: float = 1.5,         # relative std dev (%)
    seed: int = 42,
    start: datetime | None = None,
) -> pd.DataFrame:
    """
    Simulate an HPLC calibration curve: peak area = sensitivity * C + intercept + noise.

    Returns one row per replicate per concentration level.
    """
    rng = np.random.default_rng(seed)
    start = start or datetime(2026, 1, 1, 8, 0)
    concentrations = concentrations or [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0]

    rows = []
    t = start
    for conc in concentrations:
        true_area = sensitivity * conc + intercept
        u_abs = true_area * rsd_pct / 100.0
        for rep in range(n_replicates):
            rows.append({
                "instrument_id": "HPLC-001",
                "instrument_type": "HPLC",
                "analyte": analyte,
                "concentration_mgL": conc,
                "peak_area": round(float(rng.normal(true_area, u_abs)), 2),
                "replicate": rep + 1,
                "unit": "AU",
                "measured_at": t,
                "batch_id": f"HPLC-{analyte}-{start.strftime('%Y%m%d')}",
            })
            t += timedelta(minutes=5)

    return pd.DataFrame(rows)


# ── Balance ───────────────────────────────────────────────────────────────────

def generate_balance_calibration(
    *,
    nominal_mass: float = 100.0,   # g
    bias: float = 0.0002,          # systematic offset (g)
    u_rep_laplace_b: float = 0.0001,  # Laplace scale b = MAD/ln(2), so u = b*sqrt(2)
    n_points: int = 25,
    outlier_fraction: float = 0.04,
    seed: int = 42,
    start: datetime | None = None,
) -> pd.DataFrame:
    """
    Simulate balance repeatability using a Laplace error model.

    Laplace is appropriate for precision balances subject to vibration:
    the error distribution has heavier tails than Normal.
    Scale b = MAD/ln(2) is the MLE estimator → u_rep = b*sqrt(2).
    """
    rng = np.random.default_rng(seed)
    start = start or datetime(2026, 1, 1, 8, 0)

    readings = nominal_mass + bias + rng.laplace(0.0, u_rep_laplace_b, n_points)

    n_out = max(1, int(n_points * outlier_fraction))
    out_idx = rng.choice(n_points, size=n_out, replace=False)
    readings[out_idx] += rng.choice([-1, 1], size=n_out) * rng.uniform(5, 10, n_out) * u_rep_laplace_b

    timestamps = [start + timedelta(minutes=2 * i) for i in range(n_points)]

    return pd.DataFrame({
        "instrument_id": "BAL-001",
        "instrument_type": "Balance",
        "nominal_mass_g": nominal_mass,
        "reading_g": np.round(readings, 6),
        "bias_g": bias,
        "unit": "g",
        "measured_at": timestamps,
        "batch_id": f"BAL-{start.strftime('%Y%m%d')}",
    })


# ── Combined generator ────────────────────────────────────────────────────────

def generate_full_dataset(
    seed: int = 42,
    start: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Generate one batch of synthetic calibration data for all instrument types.
    Returns a dict keyed by instrument type.

    ``start`` sets the batch date: it flows into each instrument's ``batch_id``
    (``…-YYYYMMDD``) and reading timestamps, so distinct days yield distinct,
    non-colliding batches. Defaults to 2026-06-21 08:00 for backward
    compatibility.
    """
    start = start or datetime(2026, 6, 21, 8, 0)
    return {
        "xrf_fe":  generate_xrf_calibration(element="Fe", seed=seed,     start=start),
        "xrf_cu":  generate_xrf_calibration(element="Cu", seed=seed + 1, start=start,
                                             drift_rate=0.5, true_value=450.0),
        "xrf_pb":  generate_xrf_calibration(element="Pb", seed=seed + 2, start=start,
                                             true_value=80.0, u_rep=2.0),
        "hplc":    generate_hplc_calibration(seed=seed, start=start),
        "balance": generate_balance_calibration(seed=seed, start=start),
    }
