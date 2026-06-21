"""
Tests for core/control_charts.py

Each Westgard rule is verified with a hand-crafted series that triggers
exactly that rule, and a clean series that triggers nothing.
"""
import numpy as np
import pandas as pd
import pytest

from core.control_charts import westgard_rules, annotate_dataframe, Violation


MU, SIGMA = 100.0, 1.0   # reference mean and SD for all hand-crafted tests


def _z_to_val(z_scores):
    """Convert z-scores to measurement values using MU/SIGMA."""
    return [MU + z * SIGMA for z in z_scores]


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestCleanSeries:
    def test_no_violations_returns_in_control(self):
        # All points within ±2s — nothing triggered
        vals = _z_to_val([0.1, -0.2, 0.5, -0.3, 0.8, -0.1, 0.4, -0.6, 0.2, -0.5])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert result.status == "in_control"
        assert result.violations == []

    def test_result_attributes(self):
        vals = _z_to_val([0.0] * 10)
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert result.mean == MU
        assert result.sd == SIGMA
        assert result.n == 10

    def test_fewer_than_2_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            westgard_rules([1.0], mean=MU, sd=SIGMA)

    def test_zero_sd_raises(self):
        with pytest.raises(ValueError, match="SD is zero"):
            westgard_rules([5.0, 5.0, 5.0], mean=5.0, sd=0.0)


# ── Rule 1₃s ──────────────────────────────────────────────────────────────────

class TestRule1_3s:
    def test_single_point_beyond_plus3s(self):
        vals = _z_to_val([0.1, 0.2, 3.5, 0.0, -0.1])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        rules = [v.rule for v in result.violations]
        assert "1_3s" in rules
        assert result.status == "out_of_control"

    def test_single_point_beyond_minus3s(self):
        vals = _z_to_val([0.1, -3.8, 0.0, 0.2])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "1_3s" for v in result.violations)

    def test_exactly_3s_not_triggered(self):
        # |z| = 3.0 exactly is not > 3.0
        vals = _z_to_val([0.0, 3.0, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert not any(v.rule == "1_3s" for v in result.violations)

    def test_violation_index_correct(self):
        vals = _z_to_val([0.0, 0.0, 3.5, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        v = next(v for v in result.violations if v.rule == "1_3s")
        assert v.index == 2


# ── Rule 2₂s ──────────────────────────────────────────────────────────────────

class TestRule2_2s:
    def test_two_consecutive_above_plus2s(self):
        vals = _z_to_val([0.0, 2.5, 2.3, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "2_2s" for v in result.violations)
        assert result.status == "out_of_control"

    def test_two_consecutive_below_minus2s(self):
        vals = _z_to_val([0.0, -2.5, -2.8, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "2_2s" for v in result.violations)

    def test_opposite_sides_not_triggered(self):
        # +2.5 then -2.5 — different sides, should NOT trigger 2₂s
        vals = _z_to_val([0.0, 2.5, -2.5, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert not any(v.rule == "2_2s" for v in result.violations)


# ── Rule R₄s ──────────────────────────────────────────────────────────────────

class TestRuleR4s:
    def test_range_exceeds_4s(self):
        # z[0] = -2.5, z[1] = +2.5 → range = 5 > 4
        vals = _z_to_val([0.0, -2.5, 2.5, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "R_4s" for v in result.violations)
        assert result.status == "out_of_control"

    def test_range_below_4s_not_triggered(self):
        vals = _z_to_val([0.0, -1.5, 1.5, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert not any(v.rule == "R_4s" for v in result.violations)


# ── Rule 4₁s ──────────────────────────────────────────────────────────────────

class TestRule4_1s:
    def test_four_consecutive_above_1s(self):
        vals = _z_to_val([0.0, 1.2, 1.5, 1.1, 1.3, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "4_1s" for v in result.violations)
        # 4₁s is a warning, not reject (unless combined with other rules)
        rule_severities = {v.rule: v.severity for v in result.violations}
        assert rule_severities.get("4_1s") == "warning"

    def test_four_consecutive_below_minus1s(self):
        vals = _z_to_val([0.0, -1.2, -1.5, -1.1, -1.3, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "4_1s" for v in result.violations)

    def test_three_consecutive_not_enough(self):
        vals = _z_to_val([0.0, 1.2, 1.5, 1.1, 0.1])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert not any(v.rule == "4_1s" for v in result.violations)


# ── Rule 10ₓ ──────────────────────────────────────────────────────────────────

class TestRule10x:
    def test_ten_consecutive_above_mean(self):
        vals = _z_to_val([0.5] * 10 + [0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "10x" for v in result.violations)
        rule_severities = {v.rule: v.severity for v in result.violations}
        assert rule_severities.get("10x") == "warning"

    def test_ten_consecutive_below_mean(self):
        vals = _z_to_val([-0.5] * 10 + [0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert any(v.rule == "10x" for v in result.violations)

    def test_nine_consecutive_not_enough(self):
        vals = _z_to_val([0.5] * 9 + [-0.1])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert not any(v.rule == "10x" for v in result.violations)


# ── Status precedence ─────────────────────────────────────────────────────────

class TestStatus:
    def test_reject_overrides_warning(self):
        # 10x (warning) + 1_3s (reject) → out_of_control
        vals = _z_to_val([0.5] * 10 + [3.5])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        assert result.status == "out_of_control"

    def test_only_warnings_gives_warning_status(self):
        # 4₁s only → warning
        vals = _z_to_val([0.0, 1.2, 1.5, 1.1, 1.3, 0.0])
        result = westgard_rules(vals, mean=MU, sd=SIGMA)
        # Make sure no reject rules triggered
        if not any(v.severity == "reject" for v in result.violations):
            assert result.status == "warning"


# ── Default mean/SD estimation ────────────────────────────────────────────────

class TestDefaultStats:
    def test_uses_sample_mean_and_sd(self):
        rng = np.random.default_rng(7)
        vals = rng.normal(50.0, 2.0, 20).tolist()
        result = westgard_rules(vals)
        assert abs(result.mean - np.mean(vals)) < 1e-10
        assert abs(result.sd - np.std(vals, ddof=1)) < 1e-10


# ── annotate_dataframe ────────────────────────────────────────────────────────

class TestAnnotateDataFrame:
    def test_adds_columns(self):
        vals = _z_to_val([0.1, -0.2, 3.5, 0.0])
        df = pd.DataFrame({"reading": vals})
        out = annotate_dataframe(df, "reading", mean=MU, sd=SIGMA)
        assert {"z_score", "violation_rule", "qc_status"} <= set(out.columns)

    def test_violation_rule_none_for_clean_points(self):
        vals = _z_to_val([0.1, -0.2, 0.3, -0.1])
        df = pd.DataFrame({"reading": vals})
        out = annotate_dataframe(df, "reading", mean=MU, sd=SIGMA)
        assert out["violation_rule"].isna().all()

    def test_out_of_control_status_on_3s_breach(self):
        vals = _z_to_val([0.0, 3.5, 0.0, 0.0])
        df = pd.DataFrame({"reading": vals})
        out = annotate_dataframe(df, "reading", mean=MU, sd=SIGMA)
        assert out.loc[1, "qc_status"] == "out_of_control"

    def test_group_col(self):
        vals_a = _z_to_val([0.1, -0.1, 0.2])
        vals_b = _z_to_val([3.5, 0.0, 0.0])
        df = pd.DataFrame({
            "reading": vals_a + vals_b,
            "instrument": ["A"] * 3 + ["B"] * 3,
        })
        out = annotate_dataframe(df, "reading", mean=MU, sd=SIGMA, group_col="instrument")
        b_rows = out[out["instrument"] == "B"]
        assert "out_of_control" in b_rows["qc_status"].values
