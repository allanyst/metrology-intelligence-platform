"""MIP Dashboard — Metrology Intelligence Platform."""
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

API = "http://api:8000"

st.set_page_config(
    page_title="Metrology Intelligence Platform",
    page_icon="🔬",
    layout="wide",
)

st.title("🔬 Metrology Intelligence Platform")
st.caption("Calibration QC · Westgard rules · GUM uncertainty (ISO 17025)")


# ── helpers ──────────────────────────────────────────────────────────────────

def get(path: str, params: dict | None = None):
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error ({path}): {e}")
        return None


STATUS_COLOR = {
    "in_control":    "#2ecc71",
    "warning":       "#f39c12",
    "out_of_control": "#e74c3c",
}

RULE_LABEL = {
    "1_3s":  "1₃s — reject",
    "2_2s":  "2₂s — reject",
    "R_4s":  "R₄s — reject",
    "4_1s":  "4₁s — warning",
    "10x":   "10ₓ — warning",
    None:    "—",
}


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")
    type_filter = st.selectbox(
        "Instrument type", ["All", "XRF", "HPLC", "Balance"]
    )
    status_filter = st.selectbox(
        "Status", ["All", "in_control", "warning", "out_of_control"]
    )
    st.divider()
    if st.button("🔄 Refresh"):
        st.cache_data.clear()


# ── calibration overview ──────────────────────────────────────────────────────

params = {}
if type_filter != "All":
    params["instrument_type"] = type_filter
if status_filter != "All":
    params["status"] = status_filter

cals = get("/calibration/", params)
alerts_summary = get("/alerts/summary")

# KPI row
col1, col2, col3, col4 = st.columns(4)
if cals is not None:
    df_cal = pd.DataFrame(cals)
    col1.metric("Instruments", len(df_cal))
    col2.metric(
        "In control",
        int((df_cal["calibration_status"] == "in_control").sum()),
    )
    col3.metric(
        "Warnings",
        int((df_cal["calibration_status"] == "warning").sum()),
        delta_color="inverse",
    )
    col4.metric(
        "Out of control",
        int((df_cal["calibration_status"] == "out_of_control").sum()),
        delta_color="inverse",
    )

st.divider()

# ── tabs ──────────────────────────────────────────────────────────────────────

tab_overview, tab_chart, tab_alerts, tab_uncertainty = st.tabs(
    ["📋 Overview", "📈 Levey-Jennings", "🚨 Alerts", "📐 Uncertainty"]
)

# ── Tab 1: Overview ───────────────────────────────────────────────────────────

with tab_overview:
    if cals is None:
        st.stop()

    for row in cals:
        status = row["calibration_status"]
        color = STATUS_COLOR.get(status, "#95a5a6")
        u = row.get("u_expanded_k2")
        u_str = f"U(k=2) = {u:.4f}" if u else "U(k=2) = —"
        rule = RULE_LABEL.get(row.get("dominant_rule"), "—")

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
            c1.markdown(
                f"**{row['instrument_id']}**  \n"
                f"`{row['instrument_type']}` · {row.get('analyte_or_element', '—')}"
            )
            c2.markdown(
                f"<span style='color:{color};font-weight:bold'>{status}</span>",
                unsafe_allow_html=True,
            )
            c3.markdown(u_str)
            c4.markdown(f"Rule: `{rule}`")


# ── Tab 2: Levey-Jennings ─────────────────────────────────────────────────────

with tab_chart:
    if cals is None:
        st.stop()

    df_cal = pd.DataFrame(cals)
    xrf_df = df_cal[df_cal["instrument_type"] == "XRF"]

    if xrf_df.empty:
        st.info("Levey-Jennings charts are available for XRF instruments only.")
        st.stop()

    col_a, col_b = st.columns(2)
    inst_id = col_a.selectbox("Instrument (XRF)", xrf_df["instrument_id"].unique())

    detail = get(f"/calibration/{inst_id}")
    if not detail:
        st.stop()

    analytes = list({r.get("analyte_or_element") for r in detail if r.get("analyte_or_element")})
    analyte = col_b.selectbox("Element", analytes)

    chart_data = get(f"/calibration/{inst_id}/chart", {"element": analyte})
    if not chart_data:
        st.stop()

    df = pd.DataFrame(chart_data)
    df["measured_at"] = pd.to_datetime(df["measured_at"])

    mean_val = df["reading"].mean() if "reading" in df.columns else 0
    sd_val   = df["z_score"].std() if len(df) > 1 else 1

    fig = go.Figure()

    # control limit bands
    for mult, label, color in [
        (3, "±3σ", "rgba(231,76,60,0.08)"),
        (2, "±2σ", "rgba(243,156,18,0.10)"),
    ]:
        fig.add_hrect(
            y0=mult * -1, y1=mult,
            fillcolor=color, line_width=0,
            annotation_text=f"±{mult}σ", annotation_position="top right",
        )

    # centre line
    fig.add_hline(y=0, line_dash="dash", line_color="grey", line_width=1)

    # all points
    mask_ok = df["violation_rule"].isna()
    fig.add_trace(go.Scatter(
        x=df.loc[mask_ok, "measured_at"],
        y=df.loc[mask_ok, "z_score"],
        mode="markers+lines",
        name="In control",
        marker=dict(color="#2ecc71", size=7),
        line=dict(color="#2ecc71", width=1),
    ))

    # violation points
    if (~mask_ok).any():
        df_viol = df[~mask_ok]
        reject_mask = df_viol["violation_rule"].isin(["1_3s", "2_2s", "R_4s"])
        for is_reject, grp in [(True, df_viol[reject_mask]), (False, df_viol[~reject_mask])]:
            if grp.empty:
                continue
            fig.add_trace(go.Scatter(
                x=grp["measured_at"],
                y=grp["z_score"],
                mode="markers",
                name="Reject" if is_reject else "Warning",
                marker=dict(
                    color="#e74c3c" if is_reject else "#f39c12",
                    size=11,
                    symbol="x" if is_reject else "diamond",
                ),
                text=grp["violation_rule"],
                hovertemplate="%{x}<br>z=%{y:.2f}<br>Rule: %{text}",
            ))

    fig.update_layout(
        title=f"Levey-Jennings — {inst_id} / {analyte}",
        xaxis_title="Date",
        yaxis_title="z-score",
        yaxis=dict(range=[-4, 4]),
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(df, use_container_width=True)


# ── Tab 3: Alerts ─────────────────────────────────────────────────────────────

with tab_alerts:
    alerts = get("/alerts/")
    summary = get("/alerts/summary")

    if summary:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total alerts", summary["total_alerts"])
        c2.metric("Out of control", summary["out_of_control"])
        c3.metric("Warnings", summary["warnings"])

    if alerts:
        df_a = pd.DataFrame(alerts)
        df_a["status_label"] = df_a["calibration_status"].map(
            lambda s: f"🔴 {s}" if s == "out_of_control" else f"🟡 {s}"
        )
        st.dataframe(
            df_a[["instrument_id", "instrument_type", "analyte_or_element",
                  "status_label", "calibration_status"]].rename(columns={
                "instrument_id": "ID",
                "instrument_type": "Type",
                "analyte_or_element": "Analyte/Element",
                "status_label": "Status",
                "calibration_status": "_status",
            }).drop(columns=["_status"]),
            use_container_width=True,
            hide_index=True,
        )

        if summary and summary.get("by_rule"):
            st.subheader("Violations by Westgard rule")
            df_rules = pd.DataFrame(
                [{"Rule": k, "Count": v} for k, v in summary["by_rule"].items()]
            ).sort_values("Count", ascending=False)
            fig_r = go.Figure(go.Bar(
                x=df_rules["Rule"], y=df_rules["Count"],
                marker_color=["#e74c3c" if r in ("1_3s", "2_2s", "R_4s") else "#f39c12"
                               for r in df_rules["Rule"]],
            ))
            fig_r.update_layout(height=280, margin=dict(t=20, b=40))
            st.plotly_chart(fig_r, use_container_width=True)
    else:
        st.success("No active alerts.")


# ── Tab 4: Uncertainty ────────────────────────────────────────────────────────

with tab_uncertainty:
    if cals is None:
        st.stop()

    df_u = pd.DataFrame(cals)
    has_u = df_u["u_expanded_k2"].notna()

    if not has_u.any():
        st.info("No uncertainty data yet — run the uncertainty_enrichment DAG.")
        st.stop()

    df_u = df_u[has_u].copy()
    df_u["label"] = df_u["instrument_id"] + " / " + df_u["analyte_or_element"].fillna("")

    fig_u = go.Figure()
    fig_u.add_trace(go.Bar(
        name="U(k=2)",
        x=df_u["label"],
        y=df_u["u_expanded_k2"],
        marker_color=[STATUS_COLOR.get(s, "#95a5a6") for s in df_u["calibration_status"]],
        error_y=dict(
            type="data",
            array=(df_u["u_expanded_k2"] - df_u.get("u_combined", df_u["u_expanded_k2"] / 2)).tolist(),
            visible=True,
        ),
    ))
    fig_u.update_layout(
        title="Expanded uncertainty U(k=2) by instrument",
        yaxis_title="U(k=2)",
        xaxis_tickangle=-30,
        height=380,
        margin=dict(t=60, b=80),
    )
    st.plotly_chart(fig_u, use_container_width=True)

    cols_show = ["instrument_id", "instrument_type", "analyte_or_element",
                 "u_combined", "u_expanded_k2", "coverage_lower", "coverage_upper",
                 "calibration_status"]
    cols_show = [c for c in cols_show if c in df_u.columns]
    st.dataframe(df_u[cols_show], use_container_width=True, hide_index=True)
