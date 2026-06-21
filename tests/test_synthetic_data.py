"""
Tests for core/synthetic_data.py

Validates that each generator produces correctly shaped, typed, and
statistically consistent output — without hardcoding exact float values.
"""
import numpy as np
import pandas as pd
import pytest

from core.synthetic_data import (
    generate_xrf_calibration,
    generate_hplc_calibration,
    generate_balance_calibration,
    generate_full_dataset,
)


# ── XRF ───────────────────────────────────────────────────────────────────────

class TestXRF:
    def test_shape(self):
        df = generate_xrf_calibration(n_points=30)
        assert len(df) == 30
        assert {"instrument_id", "element", "reading", "nominal_value", "measured_at"} <= set(df.columns)

    def test_reproducible(self):
        df1 = generate_xrf_calibration(seed=0)
        df2 = generate_xrf_calibration(seed=0)
        pd.testing.assert_frame_equal(df1, df2)

    def test_different_seeds_differ(self):
        df1 = generate_xrf_calibration(seed=1)
        df2 = generate_xrf_calibration(seed=2)
        assert not df1["reading"].equals(df2["reading"])

    def test_readings_near_true_value(self):
        df = generate_xrf_calibration(true_value=1000.0, u_rep=5.0, n_points=200,
                                       outlier_fraction=0.0, seed=42)
        # Without outliers, >95% of readings within ±3σ of true value
        within_3s = ((df["reading"] - 1000.0).abs() < 15.0).mean()
        assert within_3s > 0.95

    def test_drift_shifts_mean(self):
        df_nodrift = generate_xrf_calibration(drift_rate=0.0, n_points=50, seed=42)
        df_drift   = generate_xrf_calibration(drift_rate=2.0, n_points=50, seed=42)
        # With drift=2 cps/reading over 50 pts, last half should be higher
        assert df_drift["reading"].iloc[-10:].mean() > df_nodrift["reading"].iloc[-10:].mean()

    def test_instrument_type(self):
        df = generate_xrf_calibration()
        assert (df["instrument_type"] == "XRF").all()

    def test_timestamps_monotonic(self):
        df = generate_xrf_calibration(n_points=10)
        assert df["measured_at"].is_monotonic_increasing


# ── HPLC ──────────────────────────────────────────────────────────────────────

class TestHPLC:
    def test_shape(self):
        df = generate_hplc_calibration(concentrations=[1, 5, 10], n_replicates=3)
        assert len(df) == 9   # 3 levels × 3 replicates
        assert {"concentration_mgL", "peak_area", "replicate"} <= set(df.columns)

    def test_linearity(self):
        # Mean peak area should be approximately linear in concentration
        df = generate_hplc_calibration(
            concentrations=[1, 5, 10, 20], n_replicates=100,
            rsd_pct=0.1, seed=42,
        )
        means = df.groupby("concentration_mgL")["peak_area"].mean()
        # Fit a line; R² must be > 0.999
        conc = means.index.to_numpy()
        area = means.to_numpy()
        coeffs = np.polyfit(conc, area, 1)
        fitted = np.polyval(coeffs, conc)
        ss_res = np.sum((area - fitted) ** 2)
        ss_tot = np.sum((area - area.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot
        assert r2 > 0.999

    def test_replicates_vary(self):
        df = generate_hplc_calibration(concentrations=[10.0], n_replicates=5)
        assert df["peak_area"].std() > 0

    def test_instrument_type(self):
        df = generate_hplc_calibration()
        assert (df["instrument_type"] == "HPLC").all()


# ── Balance ───────────────────────────────────────────────────────────────────

class TestBalance:
    def test_shape(self):
        df = generate_balance_calibration(n_points=25)
        assert len(df) == 25
        assert {"reading_g", "nominal_mass_g", "bias_g"} <= set(df.columns)

    def test_bias_reflected_in_mean(self):
        # With Laplace noise but no outliers, median ≈ nominal + bias
        df = generate_balance_calibration(
            nominal_mass=100.0, bias=0.01,
            u_rep_laplace_b=0.0001, n_points=500,
            outlier_fraction=0.0, seed=42,
        )
        median = df["reading_g"].median()
        assert abs(median - 100.01) < 0.001

    def test_laplace_heavier_tails_than_normal(self):
        # Excess kurtosis of Laplace = 3 (vs. 0 for Normal)
        # With n=1000 and no outliers, excess kurtosis should be clearly > 0.5
        from scipy.stats import kurtosis
        df = generate_balance_calibration(
            n_points=1000, outlier_fraction=0.0, seed=42,
        )
        ek = float(kurtosis(df["reading_g"], fisher=True))
        assert ek > 0.5

    def test_instrument_type(self):
        df = generate_balance_calibration()
        assert (df["instrument_type"] == "Balance").all()


# ── Full dataset ──────────────────────────────────────────────────────────────

class TestFullDataset:
    def test_keys(self):
        ds = generate_full_dataset()
        assert set(ds.keys()) == {"xrf_fe", "xrf_cu", "xrf_pb", "hplc", "balance"}

    def test_all_nonempty(self):
        ds = generate_full_dataset()
        for key, df in ds.items():
            assert len(df) > 0, f"{key} is empty"

    def test_reproducible(self):
        ds1 = generate_full_dataset(seed=99)
        ds2 = generate_full_dataset(seed=99)
        for key in ds1:
            pd.testing.assert_frame_equal(ds1[key], ds2[key])
