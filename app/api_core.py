from collections import Counter, defaultdict
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func

from . import audit, clock, workflow
from .auth import create_token, get_current_user, hash_pw, require_roles
from .db import get_db
from .models import Alert, Application, ApprovalLetter, Document, EVCVisit, Institution, StageHistory, Undertaking, User
from .seed import REGION_LABELS
from .util import row

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db=Depends(get_db)):
    u = db.query(User).filter(User.username == body.username).first()
    if not u or u.password_hash != hash_pw(body.password):
        raise HTTPException(401, "Invalid credentials")
    audit.record(db, u.name, "LOGIN", "user", u.username, {}, u.role)
    db.commit()
    return {"token": create_token(u), "user": _user(u, db)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user), db=Depends(get_db)):
    return _user(user, db)


@router.get("/auth/demo-users")
def demo_users(db=Depends(get_db)):
    return [{"username": u.username, "name": u.name, "designation": u.designation, "role": u.role, "region": u.region, "password": "demo123"}
            for u in db.query(User).order_by(User.id).all()]


def _user(u, db):
    d = row(u, exclude=("password_hash",))
    d["region_label"] = REGION_LABELS.get(u.region) if u.region else None
    if u.institution_id:
        d["institution"] = row(db.get(Institution, u.institution_id))
    return d


def _scope(q, user, model=Application):
    """Row-level scoping: regional officers see their Region; institutions see themselves."""
    if user.role == "REGIONAL_OFFICER" and user.region:
        q = q.filter(model.region == user.region)
    if user.role == "INSTITUTION":
        q = q.filter(model.institution_id == user.institution_id)
    return q


# ------------------------------------------------------------------ institutions
@router.get("/institutions")
def institutions(user: User = Depends(get_current_user), db=Depends(get_db)):
    q = db.query(Institution)
    if user.role == "REGIONAL_OFFICER" and user.region:
        q = q.filter(Institution.region == user.region)
    if user.role == "INSTITUTION":
        q = q.filter(Institution.id == user.institution_id)
    out = []
    for i in q.order_by(Institution.name).all():
        d = row(i)
        d["region_label"] = REGION_LABELS.get(i.region, i.region)
        d["open_alerts"] = db.query(Alert).filter(Alert.institution_id == i.id, Alert.state == "OPEN").count()
        d["pending_applications"] = db.query(Application).filter(Application.institution_id == i.id, Application.status.in_(["IN_PROGRESS", "RETURNED"])).count()
        out.append(d)
    return out


@router.get("/institutions/{inst_id}")
def institution(inst_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    i = db.get(Institution, inst_id)
    if not i:
        raise HTTPException(404)
    if user.role == "INSTITUTION" and user.institution_id != i.id:
        raise HTTPException(403)
    d = row(i)
    d["region_label"] = REGION_LABELS.get(i.region, i.region)
    d["applications"] = [row(a) | {"sla": workflow.sla_status(a)} for a in db.query(Application).filter(Application.institution_id == i.id).order_by(Application.submitted_at.desc()).all()]
    d["undertakings"] = [row(u) for u in db.query(Undertaking).filter(Undertaking.institution_id == i.id).order_by(Undertaking.due_date).all()]
    d["documents"] = [row(x) for x in db.query(Document).filter(Document.institution_id == i.id).order_by(Document.valid_till).all()]
    d["alerts"] = [row(a) for a in db.query(Alert).filter(Alert.institution_id == i.id).order_by(Alert.id.desc()).limit(30).all()]
    d["readiness"] = readiness(inst_id, user, db)
    return d


@router.get("/institutions/{inst_id}/readiness")
def readiness(inst_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    """Pre-submission self-scrutiny: red/amber/green readiness before an institution applies."""
    i = db.get(Institution, inst_id)
    if not i:
        raise HTTPException(404)
    today = clock.today()
    items = []
    docs = {d.doc_type: d for d in db.query(Document).filter(Document.institution_id == i.id, Document.status != "SUPERSEDED").order_by(Document.valid_till.desc()).all()}
    for dt, label in (("LEASE_DEED", "Registered lease / land document"), ("FIRE_NOC", "Fire safety NOC"), ("BUILDING_SAFETY", "Structural stability certificate"), ("AFFIDAVIT", "Affidavit on prescribed format")):
        d = docs.get(dt)
        if not d:
            items.append({"item": label, "status": "RED", "detail": "Not on record - upload required"})
        elif d.valid_till < today:
            items.append({"item": label, "status": "RED", "detail": f"Expired on {d.valid_till}"})
        elif (d.valid_till - today).days <= 90:
            items.append({"item": label, "status": "AMBER", "detail": f"Expires in {(d.valid_till - today).days} days - renew before submission"})
        else:
            items.append({"item": label, "status": "GREEN", "detail": f"Valid till {d.valid_till}"})
    uts = db.query(Undertaking).filter(Undertaking.institution_id == i.id).all()
    od = [u for u in uts if u.status == "OVERDUE"]
    pen = [u for u in uts if u.status in ("PENDING", "SUBMITTED")]
    items.append({"item": "Time-bound undertakings", "status": "RED" if od else ("AMBER" if pen else "GREEN"),
                  "detail": f"{len(od)} overdue, {len(pen)} pending verification" if (od or pen) else "All undertakings fulfilled"})
    ret = db.query(Application).filter(Application.institution_id == i.id, Application.status == "RETURNED").count()
    items.append({"item": "Applications returned for deficiencies", "status": "AMBER" if ret else "GREEN", "detail": f"{ret} awaiting rectification" if ret else "None pending"})
    items.append({"item": "Compliance score", "status": i.compliance_band, "detail": f"{i.compliance_score}/100 - {'Green Channel eligible' if i.compliance_band == 'GREEN' else 'standard scrutiny' if i.compliance_band == 'AMBER' else 'deeper scrutiny applies'}"})
    overall = "RED" if any(x["status"] == "RED" for x in items) else ("AMBER" if any(x["status"] == "AMBER" for x in items) else "GREEN")
    return {"overall": overall, "items": items, "generated_at": clock.now().isoformat()}


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard/summary")
def dashboard(user: User = Depends(get_current_user), db=Depends(get_db)):
    rules = workflow.load_rules(db)
    now = clock.now()
    warn = rules["escalation"].get("warn_days_before_sla", 2)
    active = _scope(db.query(Application).filter(Application.status.in_(["IN_PROGRESS", "RETURNED"])), user).all()
    inprog = [a for a in active if a.status == "IN_PROGRESS"]
    overdue = [a for a in inprog if a.sla_due_at and a.sla_due_at < now]
    due_soon = [a for a in inprog if a.sla_due_at and now <= a.sla_due_at <= now + timedelta(days=warn)]
    stage_counts = Counter(a.current_stage if a.status == "IN_PROGRESS" else "RETURNED" for a in active)
    region_counts = Counter(a.region for a in active)
    ageing = Counter()
    for a in active:
        d = (now - a.submitted_at).days
        ageing["0-7 d" if d <= 7 else "8-15 d" if d <= 15 else "16-30 d" if d <= 30 else "30+ d"] += 1
    inst_ids = {a.institution_id for a in active} if user.role == "INSTITUTION" else None

    evc_q = db.query(EVCVisit).filter(EVCVisit.status.in_(["QUEUED", "SCHEDULED"]))
    evc = [v for v in evc_q.all() if _visible_inst(db, v.institution_id, user)]
    evc_week = [v for v in evc if (v.status == "QUEUED" and v.due_by and v.due_by <= now + timedelta(days=7)) or (v.status == "SCHEDULED" and v.scheduled_on and v.scheduled_on <= (now + timedelta(days=7)).date())]

    uts = [u for u in db.query(Undertaking).filter(Undertaking.status.in_(["PENDING", "OVERDUE", "SUBMITTED"])).all() if _visible_inst(db, u.institution_id, user)]
    docs = [d for d in db.query(Document).all() if _visible_inst(db, d.institution_id, user)]

    alerts_q = db.query(Alert).filter(Alert.state != "CLOSED")
    alerts = [a for a in alerts_q.order_by(Alert.id.desc()).all() if _visible_alert(a, user)]
    today_alerts = [a for a in alerts if a.created_at and a.created_at.date() == now.date()]

    approved = _scope(db.query(Application).filter(Application.status == "APPROVED"), user).all()
    proc_days = [(a.decided_at - a.submitted_at).days for a in approved if a.decided_at and a.submitted_at]
    region_perf = defaultdict(lambda: {"pending": 0, "overdue": 0, "approved": 0, "avg_days": None, "_d": []})
    for a in active:
        region_perf[a.region]["pending"] += 1
    for a in overdue:
        region_perf[a.region]["overdue"] += 1
    for a in approved:
        region_perf[a.region]["approved"] += 1
        if a.decided_at:
            region_perf[a.region]["_d"].append((a.decided_at - a.submitted_at).days)
    for r, v in region_perf.items():
        v["avg_days"] = round(sum(v["_d"]) / len(v["_d"]), 1) if v["_d"] else None
        v.pop("_d")
        v["label"] = REGION_LABELS.get(r, r)

    return {
        "as_of": now.isoformat(), "clock_offset_days": clock.offset_days(), "rules_version": rules.get("version"),
        "kpis": {
            "pending": len(active), "overdue": len(overdue), "due_soon": len(due_soon), "returned": stage_counts.get("RETURNED", 0),
            "evc_due_week": len(evc_week), "evc_queue": len(evc),
            "undertakings_due_30": len([u for u in uts if u.status == "PENDING" and 0 <= (u.due_date - now.date()).days <= 30]),
            "undertakings_overdue": len([u for u in uts if u.status == "OVERDUE"]),
            "undertakings_to_verify": len([u for u in uts if u.status == "SUBMITTED"]),
            "docs_expiring_90": len([d for d in docs if d.status == "EXPIRING"]),
            "docs_expired": len([d for d in docs if d.status == "EXPIRED"]),
            "open_alerts": len(alerts), "escalations": len([a for a in alerts if a.escalation_level and a.escalation_level > 0]),
            "approved_total": len(approved), "avg_processing_days": round(sum(proc_days) / len(proc_days), 1) if proc_days else None,
        },
        "stage_pendency": [{"stage": s, "label": rules["stages"].get(s, {}).get("label", s.title()), "count": c} for s, c in sorted(stage_counts.items(), key=lambda x: -x[1])],
        "region_pendency": [{"region": r, "label": REGION_LABELS.get(r, r), "count": c} for r, c in sorted(region_counts.items(), key=lambda x: -x[1])],
        "ageing": [{"bucket": b, "count": ageing.get(b, 0)} for b in ("0-7 d", "8-15 d", "16-30 d", "30+ d")],
        "region_performance": dict(region_perf),
        "attention": [_app_brief(a, db, now) for a in sorted(inprog, key=lambda a: a.sla_due_at or now)[:8]],
        "alerts_today": [row(a) for a in today_alerts[:10]],
        "recent_alerts": [row(a) for a in alerts[:10]],
    }


def _visible_inst(db, inst_id, user):
    if user.role == "INSTITUTION":
        return inst_id == user.institution_id
    if user.role == "REGIONAL_OFFICER" and user.region:
        i = db.get(Institution, inst_id)
        return i is not None and i.region == user.region
    return True


def _visible_alert(a, user):
    if user.role == "INSTITUTION":
        return a.institution_id == user.institution_id and (a.audience or {}).get("institution")
    if user.role == "REGIONAL_OFFICER" and user.region:
        return a.region == user.region or a.region is None
    return True


def _app_brief(a, db, now=None):
    now = now or clock.now()
    inst = db.get(Institution, a.institution_id)
    d = row(a)
    d["institution_name"] = inst.name if inst else None
    d["institution_pid"] = inst.pid if inst else None
    d["ageing_days"] = (now - a.submitted_at).days if a.submitted_at else None
    d["sla"] = workflow.sla_status(a, now)
    return d


# ------------------------------------------------------------------ applications
@router.get("/applications")
def applications(status: Optional[str] = None, stage: Optional[str] = None, region: Optional[str] = None, overdue: Optional[bool] = None,
                 q: Optional[str] = None, institution_id: Optional[int] = None, limit: int = Query(200, le=500),
                 user: User = Depends(get_current_user), db=Depends(get_db)):
    now = clock.now()
    qry = _scope(db.query(Application), user)
    if status:
        qry = qry.filter(Application.status.in_(status.split(",")))
    if stage:
        qry = qry.filter(Application.current_stage == stage)
    if region:
        qry = qry.filter(Application.region == region)
    if institution_id:
        qry = qry.filter(Application.institution_id == institution_id)
    if overdue:
        qry = qry.filter(Application.status == "IN_PROGRESS", Application.sla_due_at < now)
    rows = qry.order_by(Application.sla_due_at.asc().nullslast()).limit(limit).all()
    out = [_app_brief(a, db, now) for a in rows]
    if q:
        ql = q.lower()
        out = [x for x in out if ql in (x["app_no"] or "").lower() or ql in (x["institution_name"] or "").lower() or ql in (x["institution_pid"] or "").lower()]
    return out


class SubmitIn(BaseModel):
    institution_id: Optional[int] = None
    category: str
    change_type: Optional[str] = "NONE"
    details: Optional[dict] = None


@router.post("/applications")
def submit_application(body: SubmitIn, user: User = Depends(require_roles("INSTITUTION", "REGIONAL_OFFICER", "BUREAU_OFFICER")), db=Depends(get_db)):
    inst_id = user.institution_id if user.role == "INSTITUTION" else body.institution_id
    inst = db.get(Institution, inst_id) if inst_id else None
    if not inst:
        raise HTTPException(422, "institution_id required")
    app = workflow.submit(db, inst, body.category, body.change_type, body.details, user.name)
    return application(app.id, user, db)


@router.get("/applications/{app_id}")
def application(app_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404)
    if user.role == "INSTITUTION" and a.institution_id != user.institution_id:
        raise HTTPException(403)
    rules = workflow.load_rules(db)
    d = _app_brief(a, db)
    d["institution"] = row(db.get(Institution, a.institution_id))
    d["pipeline_stages"] = [{"key": s, **rules["stages"][s]} for s in rules["pipelines"].get(a.pipeline, [])]
    d["history"] = [row(h) for h in db.query(StageHistory).filter(StageHistory.application_id == a.id).order_by(StageHistory.id).all()]
    d["evc"] = row(db.query(EVCVisit).filter(EVCVisit.application_id == a.id).first())
    d["alerts"] = [row(x) for x in db.query(Alert).filter(Alert.application_id == a.id).order_by(Alert.id.desc()).all()]
    d["letter"] = row(db.query(ApprovalLetter).filter(ApprovalLetter.application_id == a.id).first())
    d["can_act"] = _can_act(a, user, rules)
    return d


def _can_act(a, user, rules):
    if a.status not in ("IN_PROGRESS", "RETURNED"):
        return {}
    owner = rules["stages"].get(a.current_stage, {}).get("owner_role")
    is_owner = user.role in ("ADMIN", owner)
    return {"advance": a.status == "IN_PROGRESS" and is_owner, "return": a.status == "IN_PROGRESS" and (is_owner or user.role == "BUREAU_OFFICER"),
            "resubmit": a.status == "RETURNED" and (user.role == "INSTITUTION" and user.institution_id == a.institution_id or user.role == "ADMIN"),
            "owner_role": owner}


class ActionIn(BaseModel):
    remarks: Optional[str] = None
    reason: Optional[str] = None


@router.post("/applications/{app_id}/advance")
def advance(app_id: int, body: ActionIn, user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    workflow.advance(db, a, user.name, user.role, body.remarks)
    return application(app_id, user, db)


@router.post("/applications/{app_id}/return")
def return_app(app_id: int, body: ActionIn, user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    workflow.return_to_institution(db, a, user.name, user.role, body.reason or body.remarks)
    return application(app_id, user, db)


@router.post("/applications/{app_id}/resubmit")
def resubmit(app_id: int, body: ActionIn, user: User = Depends(require_roles("INSTITUTION")), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    if user.role == "INSTITUTION" and a.institution_id != user.institution_id:
        raise HTTPException(403)
    workflow.resubmit(db, a, user.name, body.remarks or "Deficiencies rectified and resubmitted")
    return application(app_id, user, db)


@router.get("/applications/{app_id}/summary")
def summary(app_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Application, app_id) or _404()
    if user.role == "INSTITUTION" and a.institution_id != user.institution_id:
        raise HTTPException(403)
    return workflow.case_summary(db, a)


def _404():
    raise HTTPException(404, "Application not found")


# ------------------------------------------------------------------ EVC
@router.get("/evc/queue")
def evc_queue(user: User = Depends(get_current_user), db=Depends(get_db)):
    now = clock.now()
    rules = workflow.load_rules(db)
    out = []
    for v in db.query(EVCVisit).order_by(EVCVisit.status.desc(), EVCVisit.due_by).all():
        if not _visible_inst(db, v.institution_id, user):
            continue
        a = db.get(Application, v.application_id)
        i = db.get(Institution, v.institution_id)
        d = row(v)
        d.update({"app_no": a.app_no if a else None, "app_status": a.status if a else None, "category": a.category if a else None, "institution_name": i.name, "state": i.state, "region": i.region, "institution_type": i.type})
        d["days_to_due"] = (v.due_by - now).days if v.due_by else None
        d["overdue"] = v.status == "QUEUED" and v.due_by is not None and v.due_by < now
        out.append(d)
    # geo-clustering suggestion: queued visits in the same State can share one committee tour
    clusters = defaultdict(list)
    for d in out:
        if d["status"] == "QUEUED":
            clusters[d["state"]].append(d["app_no"])
    return {"visits": out, "clusters": [{"state": s, "count": len(v), "applications": v} for s, v in clusters.items() if len(v) > 1],
            "experts": rules.get("evc", {}).get("experts", []), "min_members": rules.get("evc", {}).get("min_members", 3)}


class ScheduleIn(BaseModel):
    scheduled_on: str
    members: list
    remarks: Optional[str] = None


@router.post("/evc/{visit_id}/schedule")
def schedule(visit_id: int, body: ScheduleIn, user: User = Depends(require_roles("REGIONAL_OFFICER", "BUREAU_OFFICER")), db=Depends(get_db)):
    v = db.get(EVCVisit, visit_id)
    if not v:
        raise HTTPException(404)
    rules = workflow.load_rules(db)
    inst = db.get(Institution, v.institution_id)
    experts = {e["name"]: e for e in rules.get("evc", {}).get("experts", [])}
    names = [m if isinstance(m, str) else m.get("name") for m in body.members]
    if len(names) < rules.get("evc", {}).get("min_members", 3):
        raise HTTPException(422, f"At least {rules.get('evc', {}).get('min_members', 3)} committee members are required")
    conflicts = [n for n in names if experts.get(n, {}).get("state") == inst.state]
    if conflicts:
        raise HTTPException(422, f"Conflict-of-interest guard: {', '.join(conflicts)} belong(s) to the institution's State ({inst.state})")
    from datetime import date
    v.scheduled_on = date.fromisoformat(body.scheduled_on)
    v.members = [{"name": n, "expertise": experts.get(n, {}).get("expertise")} for n in names]
    v.status = "SCHEDULED"
    v.remarks = body.remarks
    a = db.get(Application, v.application_id)
    al = Alert(dedupe_key=f"EVC_SCHEDULED:{v.id}:{v.scheduled_on}", kind="EVC_SCHEDULED", severity="INFO", entity_type="evc", entity_id=v.id, institution_id=inst.id,
               application_id=a.id, region=inst.region, title=f"EVC scheduled for {a.app_no} on {v.scheduled_on}", message=f"Committee: {', '.join(names)}",
               created_at=clock.now(), audience={"institution": True, "roles": [], "members": names})
    db.add(al)
    db.flush()
    from . import notify
    notify.dispatch(db, al, rules, inst)
    audit.record(db, user.name, "EVC_SCHEDULED", "evc", v.id, {"app_no": a.app_no, "scheduled_on": body.scheduled_on, "members": names}, user.role)
    db.commit()
    return row(v)


class CompleteIn(BaseModel):
    outcome: str
    remarks: Optional[str] = None


@router.post("/evc/{visit_id}/complete")
def complete(visit_id: int, body: CompleteIn, user: User = Depends(require_roles("EVC_MEMBER", "REGIONAL_OFFICER")), db=Depends(get_db)):
    v = db.get(EVCVisit, visit_id)
    if not v:
        raise HTTPException(404)
    if v.status != "SCHEDULED":
        raise HTTPException(409, "Visit must be scheduled before a report can be submitted")
    v.status = "COMPLETED"
    v.outcome = body.outcome
    v.report_submitted_at = clock.now()
    v.remarks = body.remarks
    a = db.get(Application, v.application_id)
    for al in db.query(Alert).filter(Alert.entity_type == "evc", Alert.entity_id == v.id, Alert.state != "CLOSED").all():
        al.state = "CLOSED"
        al.closed_at = clock.now()
    audit.record(db, user.name, "EVC_REPORT_SUBMITTED", "evc", v.id, {"app_no": a.app_no, "outcome": body.outcome}, user.role)
    db.commit()
    return row(v)
