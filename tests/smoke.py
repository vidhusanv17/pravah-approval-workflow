"""API smoke test against a running PRAVAH server: python tests/smoke.py [base_url]"""
import json
import sys

import httpx

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8062"
c = httpx.Client(base_url=B, timeout=30)


def login(u):
    r = c.post("/api/auth/login", json={"username": u, "password": "demo123"})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


out = {}
out["health"] = c.get("/api/health").json()
H = login("bureau")
d = c.get("/api/dashboard/summary", headers=H).json()
out["kpis"] = d["kpis"]
out["stage_pendency"] = d["stage_pendency"]
out["ageing"] = d["ageing"]
apps = c.get("/api/applications?status=IN_PROGRESS", headers=H).json()
out["apps_in_progress"] = len(apps)
out["first_app"] = {k: apps[0][k] for k in ("app_no", "institution_name", "current_stage", "pipeline", "priority", "sla")}
evc = c.get("/api/evc/queue", headers=H).json()
out["evc"] = {"visits": len(evc["visits"]), "queued": sum(1 for v in evc["visits"] if v["status"] == "QUEUED"), "clusters": evc["clusters"]}
alerts = c.get("/api/alerts?limit=500", headers=H).json()
from collections import Counter
out["alert_kinds"] = dict(Counter(a["kind"] for a in alerts))
out["audit_chain"] = c.get("/api/audit/verify", headers=H).json()
out["notifications_by_channel"] = c.get("/api/notifications?limit=1", headers=H).json()["by_channel"]
out["region_perf_first"] = c.get("/api/reports/region-performance", headers=H).json()[0]

# --- workflow actions as the right roles
ro = login("ro.south")
mine = [a for a in c.get("/api/applications?status=IN_PROGRESS&stage=SCRUTINY", headers=ro).json()]
out["ro_south_scrutiny_count"] = len(mine)
if mine:
    a = mine[0]
    r = c.post(f"/api/applications/{a['id']}/advance", json={"remarks": "Scrutiny completed; documents in order"}, headers=ro)
    out["advance"] = {"status": r.status_code, "new_stage": r.json().get("current_stage"), "evc": bool(r.json().get("evc"))}
    # wrong role attempt
    inst = login("inst.nalanda")
    r2 = c.post(f"/api/applications/{a['id']}/advance", json={}, headers=inst)
    out["advance_wrong_role"] = r2.status_code
if len(mine) > 1:
    a = mine[1]
    r = c.post(f"/api/applications/{a['id']}/return", json={"reason": "Fire NOC covers only Block A; upload NOC for all academic blocks."}, headers=ro)
    out["return"] = {"status": r.status_code, "app_status": r.json().get("status")}
    r = c.post(f"/api/applications/{a['id']}/return", json={"reason": "short"}, headers=ro)
    out["return_without_reason"] = r.status_code

# EVC schedule with conflict-of-interest guard
q = c.get("/api/evc/queue", headers=H).json()
queued = [v for v in q["visits"] if v["status"] == "QUEUED"]
if queued:
    v = queued[0]
    same_state = [e["name"] for e in q["experts"] if e["state"] == v["state"]]
    other = [e["name"] for e in q["experts"] if e["state"] != v["state"]][:3]
    if same_state:
        r = c.post(f"/api/evc/{v['id']}/schedule", json={"scheduled_on": "2026-11-05", "members": same_state + other[:2]}, headers=H)
        out["evc_conflict_guard"] = {"status": r.status_code, "detail": r.json().get("detail")}
    r = c.post(f"/api/evc/{v['id']}/schedule", json={"scheduled_on": "2026-11-05", "members": other}, headers=H)
    out["evc_schedule"] = {"status": r.status_code, "state": r.json().get("status")}
    ev = login("evc.iyer")
    r = c.post(f"/api/evc/{v['id']}/complete", json={"outcome": "RECOMMENDED", "remarks": "Infrastructure as per norms"}, headers=ev)
    out["evc_complete"] = {"status": r.status_code, "state": r.json().get("status")}

# undertaking evidence + verification
inst = login("inst.nalanda")
uts = c.get("/api/undertakings?status=PENDING,OVERDUE", headers=inst).json()
if uts:
    r = c.post(f"/api/undertakings/{uts[0]['id']}/submit", json={"filename": "faculty_appointment_orders.pdf", "note": "6 appointment orders"}, headers=inst)
    out["ut_submit"] = {"status": r.status_code, "state": r.json().get("status")}
    ro2 = login("ro.southcentral")
    r = c.post(f"/api/undertakings/{uts[0]['id']}/verify", json={"accepted": True}, headers=ro2)
    out["ut_verify"] = {"status": r.status_code, "state": r.json().get("status")}

# approval letter + public verify
approved = c.get("/api/applications?status=APPROVED", headers=H).json()
if approved:
    det = c.get(f"/api/applications/{approved[0]['id']}", headers=H).json()
    code = det["letter"]["verify_code"]
    out["verify_public"] = c.get(f"/api/verify/{code}").json()["valid"]
    out["verify_bad"] = c.get("/api/verify/NOPE").json()["valid"]
    out["letter_pdf_bytes"] = len(c.get(f"/api/letters/{approved[0]['id']}/pdf").content)
    out["letter_qr_status"] = c.get(f"/api/letters/{approved[0]['id']}/qr.png").status_code

# demo clock: +10 days -> more alerts
r = c.post("/api/demo/clock", json={"days": 10}, headers=H)
out["clock_plus_10"] = r.json()["monitor"]
r = c.post("/api/demo/clock", json={"days": -10}, headers=H)
out["readiness"] = c.get("/api/institutions/1/readiness", headers=H).json()["overall"]
out["rules_version"] = c.get("/api/rules", headers=H).json()["rules"]["version"]
out["audit_chain_after"] = c.get("/api/audit/verify", headers=H).json()
print(json.dumps(out, indent=1, default=str))
