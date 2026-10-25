"""Configurable approval workflow engine: routing, stage transitions, returns, approval letters."""
import json
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException

from . import audit, clock
from .db import BASE_DIR, DATA_DIR
from .models import Alert, ApprovalLetter, Application, Document, EVCVisit, Institution, RuleSet, StageHistory, Undertaking

RULES_FILE = BASE_DIR / "rules" / "workflow_rules.json"


# ---------------------------------------------------------------- rules
def load_rules(db) -> dict:
    rs = db.query(RuleSet).filter(RuleSet.active == True).order_by(RuleSet.id.desc()).first()  # noqa: E712
    if rs:
        return rs.rules
    data = json.loads(Path(RULES_FILE).read_text(encoding="utf-8"))
    db.add(RuleSet(version=data.get("version", "v1"), rules=data, active=True, created_at=clock.now(), created_by="system"))
    db.commit()
    return data


def save_rules(db, data: dict, actor: str) -> RuleSet:
    for k in ("stages", "pipelines", "routing", "escalation"):
        if k not in data:
            raise HTTPException(422, f"rules.{k} is required")
    for name, stages in data["pipelines"].items():
        for s in stages:
            if s not in data["stages"]:
                raise HTTPException(422, f"pipeline {name} references unknown stage {s}")
    db.query(RuleSet).filter(RuleSet.active == True).update({"active": False})  # noqa: E712
    prev = db.query(RuleSet).count()
    base_v = (data.get("version") or "APH-2026-27").rsplit(".v", 1)[0]
    data["version"] = f"{base_v}.v{prev + 1}"
    rs = RuleSet(version=data["version"], rules=data, active=True, created_at=clock.now(), created_by=actor)
    db.add(rs)
    audit.record(db, actor, "RULES_UPDATED", "ruleset", data["version"], {"stages": list(data["stages"].keys()), "pipelines": list(data["pipelines"].keys())})
    db.commit()
    return rs


def resolve_pipeline(rules, category, change_type):
    for r in rules.get("routing", []):
        cond = r.get("when", {})
        if all(_match(cond, k, category, change_type) for k in cond):
            return r["pipeline"], r.get("note", "")
    return rules.get("default_pipeline", "SCRUTINY_EVC"), "Default pipeline"


def _match(cond, key, category, change_type):
    val = {"category": category, "change_type": change_type}.get(key)
    return cond[key] == val


def stage_sla_days(rules, stage, priority):
    base = rules["stages"][stage]["sla_days"]
    if priority == "GREEN_CHANNEL":
        return max(1, round(base * rules.get("green_channel", {}).get("sla_factor", 0.7)))
    return base


def priority_for(rules, inst: Institution):
    if inst.compliance_score is not None:
        if inst.compliance_score >= rules.get("green_channel", {}).get("min_score", 85):
            return "GREEN_CHANNEL"
        if inst.compliance_score < rules.get("high_risk", {}).get("max_score", 60):
            return "HIGH_RISK"
    return "NORMAL"


# ---------------------------------------------------------------- transitions
def enter_stage(db, app: Application, stage: str, at, rules, actor, action="ENTERED", remarks=None):
    app.current_stage = stage
    app.stage_entered_at = at
    sla = stage_sla_days(rules, stage, app.priority)
    app.sla_due_at = at + timedelta(days=sla)
    app.assigned_role = rules["stages"][stage]["owner_role"]
    app.escalation_level = 0
    db.add(StageHistory(application_id=app.id, stage=stage, entered_at=at, action=action, actor=actor, remarks=remarks, sla_days=sla))
    if stage == "EVC" and not db.query(EVCVisit).filter(EVCVisit.application_id == app.id).first():
        within = rules.get("evc", {}).get("schedule_within_days", 10)
        db.add(EVCVisit(application_id=app.id, institution_id=app.institution_id, status="QUEUED", queued_at=at,
                        due_by=at + timedelta(days=within), cluster_key=app.institution.state if app.institution else None))


def submit(db, inst: Institution, category, change_type, details, actor, academic_year="2026-27"):
    rules = load_rules(db)
    pipeline, note = resolve_pipeline(rules, category, change_type or "NONE")
    now = clock.now()
    seq = db.query(Application).count() + 1
    app = Application(app_no=f"1-{now.year}-{seq:05d}", institution_id=inst.id, category=category, change_type=change_type or "NONE",
                      academic_year=academic_year, details=details or {}, pipeline=pipeline, stage_index=0, status="IN_PROGRESS",
                      priority=priority_for(rules, inst), region=inst.region, submitted_at=now, routing_note=note)
    db.add(app)
    db.flush()
    app.institution = inst
    enter_stage(db, app, rules["pipelines"][pipeline][0], now, rules, actor, remarks=f"Auto-routed: {pipeline} ({note})")
    audit.record(db, actor, "APPLICATION_SUBMITTED", "application", app.app_no,
                 {"institution": inst.name, "category": category, "change_type": change_type, "pipeline": pipeline, "priority": app.priority})
    db.commit()
    return app


def _close_current_history(db, app, at, action, actor, remarks):
    h = db.query(StageHistory).filter(StageHistory.application_id == app.id, StageHistory.exited_at == None).order_by(StageHistory.id.desc()).first()  # noqa: E711
    if h:
        h.exited_at = at
        h.action = action
        h.actor = actor
        h.remarks = remarks
        h.breached = bool(app.sla_due_at and at > app.sla_due_at)


def advance(db, app: Application, actor, actor_role, remarks=None):
    rules = load_rules(db)
    if app.status != "IN_PROGRESS":
        raise HTTPException(409, f"Application is {app.status}; it cannot be advanced")
    owner = rules["stages"][app.current_stage]["owner_role"]
    if actor_role not in (owner, "ADMIN"):
        raise HTTPException(403, f"Stage {app.current_stage} must be completed by {owner}")
    if app.current_stage == "EVC":
        v = db.query(EVCVisit).filter(EVCVisit.application_id == app.id).first()
        if not v or v.status != "COMPLETED":
            raise HTTPException(409, "EVC report has not been submitted; the application cannot move past EVC")
    now = clock.now()
    stages = rules["pipelines"][app.pipeline]
    _close_current_history(db, app, now, "ADVANCED", actor, remarks)
    nxt = app.stage_index + 1 if app.current_stage != "RE_SCRUTINY" else app.stage_index + 1
    if nxt >= len(stages):
        return approve(db, app, actor, actor_role, remarks, rules, now)
    app.stage_index = nxt
    enter_stage(db, app, stages[nxt], now, rules, actor)
    _close_alerts_for_entity(db, "application", app.id)
    audit.record(db, actor, "STAGE_ADVANCED", "application", app.app_no, {"to": stages[nxt], "remarks": remarks}, actor_role)
    db.commit()
    return app


def return_to_institution(db, app: Application, actor, actor_role, reason):
    if not reason or len(reason.strip()) < 10:
        raise HTTPException(422, "A recorded reason (>= 10 characters) is mandatory for return/revert")
    rules = load_rules(db)
    owner = rules["stages"][app.current_stage]["owner_role"]
    if actor_role not in (owner, "ADMIN", "BUREAU_OFFICER"):
        raise HTTPException(403, f"Only {owner} may return an application at stage {app.current_stage}")
    now = clock.now()
    _close_current_history(db, app, now, "RETURNED", actor, reason)
    app.status = "RETURNED"
    app.return_reason = reason
    app.return_count = (app.return_count or 0) + 1
    db.add(StageHistory(application_id=app.id, stage="WITH_INSTITUTION", entered_at=now, action="ENTERED", actor=actor, remarks=reason, sla_days=0))
    a = Alert(dedupe_key=f"RETURNED:{app.id}:{app.return_count}", kind="APPLICATION_RETURNED", severity="WARNING", entity_type="application",
              entity_id=app.id, institution_id=app.institution_id, application_id=app.id, region=app.region,
              title=f"Application {app.app_no} returned for deficiencies", message=reason, created_at=now,
              audience={"institution": True, "roles": []})
    db.add(a)
    db.flush()
    from . import notify
    notify.dispatch(db, a, rules, app.institution)
    audit.record(db, actor, "APPLICATION_RETURNED", "application", app.app_no, {"reason": reason, "stage": app.current_stage}, actor_role)
    db.commit()
    return app


def resubmit(db, app: Application, actor, remarks):
    if app.status != "RETURNED":
        raise HTTPException(409, "Only returned applications can be resubmitted")
    rules = load_rules(db)
    now = clock.now()
    _close_current_history(db, app, now, "RESUBMITTED", actor, remarks)
    app.status = "IN_PROGRESS"
    enter_stage(db, app, "RE_SCRUTINY", now, rules, actor, action="ENTERED", remarks=remarks)
    audit.record(db, actor, "APPLICATION_RESUBMITTED", "application", app.app_no, {"remarks": remarks})
    db.commit()
    return app


def approve(db, app, actor, actor_role, remarks, rules=None, now=None):
    rules = rules or load_rules(db)
    now = now or clock.now()
    app.status = "APPROVED"
    app.decided_at = now
    app.current_stage = "APPROVED"
    db.add(StageHistory(application_id=app.id, stage="APPROVED", entered_at=now, exited_at=now, action="APPROVED", actor=actor, remarks=remarks, sla_days=0))
    letter = issue_letter(db, app, now)
    _close_alerts_for_entity(db, "application", app.id)
    audit.record(db, actor, "APPLICATION_APPROVED", "application", app.app_no, {"letter_no": letter.letter_no, "verify_code": letter.verify_code}, actor_role)
    db.commit()
    return app


def issue_letter(db, app, now=None):
    now = now or clock.now()
    existing = db.query(ApprovalLetter).filter(ApprovalLetter.application_id == app.id).first()
    if existing:
        return existing
    code = secrets.token_hex(5).upper()
    letter_no = f"AICTE/{app.region}/{app.academic_year}/{app.id:05d}"
    courses = (app.details or {}).get("courses") or [{"course": "B.E./B.Tech - Computer Science & Engineering", "intake": 120}]
    letter = ApprovalLetter(application_id=app.id, letter_no=letter_no, issued_at=now, verify_code=code, academic_year=app.academic_year, courses=courses)
    letters_dir = DATA_DIR / "letters"
    letters_dir.mkdir(exist_ok=True)
    try:
        import qrcode
        img = qrcode.make(f"https://pravah.aicte.gov.in/verify/{code}")
        p = letters_dir / f"{code}.png"
        img.save(p)
        letter.qr_path = str(p)
    except Exception:
        letter.qr_path = None
    db.add(letter)
    db.flush()
    return letter


def _close_alerts_for_entity(db, entity_type, entity_id):
    for a in db.query(Alert).filter(Alert.entity_type == entity_type, Alert.entity_id == entity_id, Alert.state != "CLOSED").all():
        a.state = "CLOSED"
        a.closed_at = clock.now()


# ---------------------------------------------------------------- electronic case summary
def case_summary(db, app: Application):
    from .util import row
    inst = app.institution
    hist = db.query(StageHistory).filter(StageHistory.application_id == app.id).order_by(StageHistory.id).all()
    evc = db.query(EVCVisit).filter(EVCVisit.application_id == app.id).first()
    uts = db.query(Undertaking).filter(Undertaking.institution_id == app.institution_id).all()
    docs = db.query(Document).filter(Document.institution_id == app.institution_id).all()
    alerts = db.query(Alert).filter(Alert.application_id == app.id).order_by(Alert.id.desc()).all()
    now = clock.now()
    return {
        "generated_at": now.isoformat(),
        "application": row(app),
        "institution": row(inst),
        "timeline": [row(h) for h in hist],
        "evc": row(evc),
        "pending_items": {
            "undertakings_overdue": [row(u) for u in uts if u.status == "OVERDUE"],
            "undertakings_pending": [row(u) for u in uts if u.status in ("PENDING", "SUBMITTED")],
            "documents_expired": [row(d) for d in docs if d.status == "EXPIRED"],
            "documents_expiring": [row(d) for d in docs if d.status == "EXPIRING"],
        },
        "alerts": [row(a) for a in alerts],
        "ageing_days": (now - app.submitted_at).days if app.submitted_at else None,
        "sla_status": sla_status(app, now),
        "recommendation": _recommend(app, uts, docs),
    }


def sla_status(app, now=None):
    now = now or clock.now()
    if app.status != "IN_PROGRESS" or not app.sla_due_at:
        return {"state": app.status, "days": 0}
    d = (app.sla_due_at - now).days
    if d < 0:
        return {"state": "OVERDUE", "days": -d}
    if d <= 2:
        return {"state": "DUE_SOON", "days": d}
    return {"state": "ON_TRACK", "days": d}


def _recommend(app, uts, docs):
    issues = []
    if any(d.status == "EXPIRED" for d in docs):
        issues.append("Expired prescribed document(s) on record - renewal required before approval")
    if any(u.status == "OVERDUE" for u in uts):
        issues.append("Overdue undertaking(s) - compliance evidence awaited")
    if app.priority == "GREEN_CHANNEL" and not issues:
        return {"text": "Green Channel: no outstanding compliance items; eligible for fast-track processing", "level": "GREEN"}
    if issues:
        return {"text": "; ".join(issues), "level": "RED"}
    return {"text": "No outstanding compliance items found by the system; proceed with statutory scrutiny", "level": "AMBER"}
