"""Quick smoke test for MIP API endpoints."""
import urllib.request
import json
import sys

BASE = "http://localhost:8004"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.loads(r.read())

errors = []

# /health
h = get("/health")
assert h["status"] == "ok", f"health failed: {h}"
print(f"[OK] /health → {h}")

# /calibration/
cals = get("/calibration/")
assert len(cals) == 5, f"expected 5 instruments, got {len(cals)}"
print(f"[OK] /calibration/ → {len(cals)} instruments")
for c in cals:
    u = c["u_expanded_k2"]
    print(f"     {c['instrument_type']:8} {c['analyte_or_element']:12} "
          f"{c['calibration_status']:15} U(k=2)={u}")

# /calibration/ filter by type
xrf = get("/calibration/?instrument_type=XRF")
assert len(xrf) == 3, f"expected 3 XRF rows, got {len(xrf)}"
print(f"[OK] /calibration/?instrument_type=XRF → {len(xrf)} rows")

# /calibration/{id}
detail = get("/calibration/XRF-001")
assert len(detail) == 3, f"expected 3 elements for XRF-001, got {len(detail)}"
print(f"[OK] /calibration/XRF-001 → {len(detail)} elements")

# /calibration/{id}/chart
chart = get("/calibration/XRF-001/chart?element=Fe")
assert len(chart) == 30, f"expected 30 chart points, got {len(chart)}"
z_scores = [p["z_score"] for p in chart]
print(f"[OK] /calibration/XRF-001/chart?element=Fe → {len(chart)} pts "
      f"z=[{min(z_scores):.2f}, {max(z_scores):.2f}]")

# /alerts/
alerts = get("/alerts/")
assert len(alerts) >= 1, "expected at least 1 alert (Balance is out_of_control)"
print(f"[OK] /alerts/ → {len(alerts)} alerts")
for a in alerts:
    print(f"     [{a['calibration_status']}] {a['instrument_type']} {a['analyte_or_element']}")

# /alerts/summary
s = get("/alerts/summary")
assert s["total_alerts"] >= 1
print(f"[OK] /alerts/summary → total={s['total_alerts']} "
      f"oc={s['out_of_control']} warn={s['warnings']}")

print("\nAll smoke tests passed.")
