import csv
import hashlib
import io
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import audit, clock, monitor, notify, workflow
from .api_core import _visible_alert, _visible_inst
from .auth import get_current_user, require_roles
from .db import SessionLocal, engine, get_db
from .models import Alert, Application, ApprovalLetter, AuditLog, Document, Institution, Notification, RuleSet, StageHistory, Undertaking, User
from .seed import REGION_LABELS
from .util import row

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ undertakings
@router.get("/undertakings")
def undertakings(status: Optional[str] = None, user: User = Depends(get_current_user), db=Depends(get_db)):
    today = clock.today()
    q = db.query(Undertaking)
    if status:
        q = q.filter(Undertaking.status.in_(status.split(",")))
    out = []
    for u in q.order_by(Undertaking.due_date).all():
        if not _visible_inst(db, u.institution_id, user):
            continue
        i = db.get(Institution, u.institution_id)
        d = row(u)
        d.update({"institution_name": i.name, "institution_pid": i.pid, "region": i.region, "days_to_due": (u.due_date - today).days})
        out.append(d)
    return out


class EvidenceIn(BaseModel):
    filename: str
    note: Optional[str] = None


@router.post("/undertakings/{uid}/submit")
def submit_evidence(uid: int, body: EvidenceIn, user: User = Depends(require_roles("INSTITUTION")), db=Depends(get_db)):
    u = db.get(Undertaking, uid)
    if not u or (user.role == "INSTITUTION" and u.institution_id != user.institution_id):
        raise HTTPException(404)
    u.evidence = {"filename": body.filename, "note": body.note, "submitted_at": clock.now().isoformat(), "sha256": hashlib.sha256(body.filename.encode()).hexdigest()}
    u.status = "SUBMITTED"
    for a in db.query(Alert).filter(Alert.entity_type == "undertaking", Alert.entity_id == u.id, Alert.state != "CLOSED").all():
        a.state = "ACKNOWLEDGED"
    audit.record(db, user.name, "UNDERTAKING_EVIDENCE_SUBMITTED", "undertaking", u.id, {"filename": body.filename}, user.role)
    db.commit()
    return row(u)


class VerifyIn(BaseModel):
    accepted: bool
    remarks: Optional[str] = None


@router.post("/undertakings/{uid}/verify")
def verify_undertaking(uid: int, body: VerifyIn, user: User = Depends(require_roles("REGIONAL_OFFICER", "BUREAU_OFFICER")), db=Depends(get_db)):
    u = db.get(Undertaking, uid)
    if not u:
        raise HTTPException(404)
    if u.status != "SUBMITTED":
        raise HTTPException(409, "No submitted evidence to verify")
    u.status = "VERIFIED" if body.accepted else "REJECTED"
    u.verified_by = user.name
    u.verified_at = clock.now()
    if body.accepted:
        for a in db.query(Alert).filter(Alert.entity_type == "undertaking", Alert.entity_id == u.id, Alert.state != "CLOSED").all():
            a.state = "CLOSED"
            a.closed_at = clock.now()
    else:
        u.status = "PENDING"
        u.evidence = None
        inst = db.get(Institution, u.institution_id)
        al = Alert(dedupe_key=f"UT_REJECTED:{u.id}:{clock.now().isoformat()}", kind="UNDERTAKING_EVIDENCE_REJECTED", severity="WARNING", entity_type="undertaking", entity_id=u.id,
                   institution_id=u.institution_id, region=inst.region, title=f"Evidence not accepted: {u.category.title()}", message=body.remarks or "Evidence insufficient; please resubmit.",
                   created_at=clock.now(), audience={"institution": True, "roles": []})
        db.add(al)
        db.flush()
        notify.dispatch(db, al, workflow.load_rules(db), inst)
    audit.record(db, user.name, "UNDERTAKING_VERIFIED" if body.accepted else "UNDERTAKING_EVIDENCE_REJECTED", "undertaking", u.id, {"remarks": body.remarks}, user.role)
    db.commit()
    return row(u)


# ------------------------------------------------------------------ documents
@router.get("/documents")
def documents(status: Optional[str] = None, user: User = Depends(get_current_user), db=Depends(get_db)):
    today = clock.today()
    q = db.query(Document)
    if status:
        q = q.filter(Document.status.in_(status.split(",")))
    out = []
    for d0 in q.order_by(Document.valid_till).all():
        if not _visible_inst(db, d0.institution_id, user):
            continue
        i = db.get(Institution, d0.institution_id)
        d = row(d0)
        d.update({"institution_name": i.name, "institution_pid": i.pid, "region": i.region, "days_to_expiry": (d0.valid_till - today).days})
        out.append(d)
    return out


class RenewIn(BaseModel):
    ref_no: str
    issued_on: str
    valid_till: str
    filename: Optional[str] = None


@router.post("/documents/{doc_id}/renew")
def renew(doc_id: int, body: RenewIn, user: User = Depends(require_roles("INSTITUTION")), db=Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or (user.role == "INSTITUTION" and d.institution_id != user.institution_id):
        raise HTTPException(404)
    d.renewal = {"ref_no": body.ref_no, "issued_on": body.issued_on, "valid_till": body.valid_till, "filename": body.filename, "submitted_at": clock.now().isoformat(),
                 "sha256": hashlib.sha256(f"{body.ref_no}{body.filename}".encode()).hexdigest()}
    d.status = "RENEWAL_SUBMITTED"
    for a in db.query(Alert).filter(Alert.entity_type == "document", Alert.entity_id == d.id, Alert.state != "CLOSED").all():
        a.state = "ACKNOWLEDGED"
    audit.record(db, user.name, "DOCUMENT_RENEWAL_SUBMITTED", "document", d.id, {"ref_no": body.ref_no, "valid_till": body.valid_till}, user.role)
    db.commit()
    return row(d)


@router.post("/documents/{doc_id}/verify-renewal")
def verify_renewal(doc_id: int, body: VerifyIn, user: User = Depends(require_roles("REGIONAL_OFFICER", "BUREAU_OFFICER")), db=Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or d.status != "RENEWAL_SUBMITTED" or not d.renewal:
        raise HTTPException(409, "No renewal awaiting verification")
    if body.accepted:
        new = Document(institution_id=d.institution_id, doc_type=d.doc_type, title=d.title, ref_no=d.renewal["ref_no"], issuing_authority=d.issuing_authority,
                       issued_on=date.fromisoformat(d.renewal["issued_on"]), valid_till=date.fromisoformat(d.renewal["valid_till"]), status="VALID",
                       sha256=d.renewal.get("sha256"), renewal_of_id=d.id, alerts_sent=[], verified_by=user.name, verified_at=clock.now())
        d.status = "SUPERSEDED"
        db.add(new)
        for a in db.query(Alert).filter(Alert.entity_type == "document", Alert.entity_id == d.id, Alert.state != "CLOSED").all():
            a.state = "CLOSED"
            a.closed_at = clock.now()
        audit.record(db, user.name, "DOCUMENT_RENEWAL_VERIFIED", "document", d.id, {"new_ref": new.ref_no, "valid_till": str(new.valid_till)}, user.role)
        db.commit()
        return row(new)
    d.status = "EXPIRED" if d.valid_till < clock.today() else "VALID"
    d.renewal = None
    audit.record(db, user.name, "DOCUMENT_RENEWAL_REJECTED", "document", d.id, {"remarks": body.remarks}, user.role)
    db.commit()
    return row(d)


# ------------------------------------------------------------------ alerts & notifications
@router.get("/alerts")
def alerts(state: Optional[str] = None, kind: Optional[str] = None, severity: Optional[str] = None, escalated: Optional[bool] = None,
           limit: int = Query(200, le=1000), user: User = Depends(get_current_user), db=Depends(get_db)):
    q = db.query(Alert)
    if state:
        q = q.filter(Alert.state.in_(state.split(",")))
    if kind:
        q = q.filter(Alert.kind == kind)
    if severity:
        q = q.filter(Alert.severity == severity)
    if escalated:
        q = q.filter(Alert.escalation_level > 0)
    out = []
    for a in q.order_by(Alert.id.desc()).all():
        if not _visible_alert(a, user):
            continue
        d = row(a)
        i = db.get(Institution, a.institution_id) if a.institution_id else None
        d["institution_name"] = i.name if i else None
        d["notifications"] = db.query(Notification).filter(Notification.alert_id == a.id).count()
        out.append(d)
        if len(out) >= limit:
            break
    return out


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, user: User = Depends(get_current_user), db=Depends(get_db)):
    a = db.get(Alert, alert_id) or _404()
    a.state = "ACKNOWLEDGED"
    a.acknowledged_by = user.name
    audit.record(db, user.name, "ALERT_ACKNOWLEDGED", "alert", a.id, {"kind": a.kind}, user.role)
    db.commit()
    return row(a)


@router.post("/alerts/{alert_id}/close")
def close(alert_id: int, body: Optional[dict] = None, user: User = Depends(require_roles("REGIONAL_OFFICER", "BUREAU_OFFICER", "MEMBER_SECRETARY")), db=Depends(get_db)):
    a = db.get(Alert, alert_id) or _404()
    a.state = "CLOSED"
    a.closed_at = clock.now()
    audit.record(db, user.name, "ALERT_CLOSED", "alert", a.id, {"kind": a.kind, "remarks": (body or {}).get("remarks")}, user.role)
    db.commit()
    return row(a)


@router.get("/notifications")
def notifications(limit: int = Query(100, le=500), channel: Optional[str] = None, user: User = Depends(get_current_user), db=Depends(get_db)):
    q = db.query(Notification)
    if channel:
        q = q.filter(Notification.channel == channel)
    if user.role == "INSTITUTION":
        i = db.get(Institution, user.institution_id)
        q = q.filter(Notification.recipient == i.name)
    rows = q.order_by(Notification.id.desc()).limit(limit).all()
    stats = {}
    for ch, in db.query(Notification.channel).distinct():
        stats[ch] = db.query(Notification).filter(Notification.channel == ch).count()
    return {"items": [row(n) for n in rows], "by_channel": stats}


def _404():
    raise HTTPException(404)


# ------------------------------------------------------------------ reports
@router.get("/reports/region-performance")
def region_performance(user: User = Depends(require_roles("REGIONAL_OFFICER", "BUREAU_OFFICER", "MEMBER_SECRETARY", "EVC_MEMBER")), db=Depends(get_db)):
    now = clock.now()
    out = []
    regions = sorted({i.region for i in db.query(Institution).all()})
    for r in regions:
        if user.role == "REGIONAL_OFFICER" and user.region and r != user.region:
            continue
        apps = db.query(Application).filter(Application.region == r).all()
        inst_ids = [i.id for i in db.query(Institution).filter(Institution.region == r).all()]
        active = [a for a in apps if a.status in ("IN_PROGRESS", "RETURNED")]
        approved = [a for a in apps if a.status == "APPROVED"]
        pd = [(a.decided_at - a.submitted_at).days for a in approved if a.decided_at]
        out.append({
            "region": r, "label": REGION_LABELS.get(r, r), "institutions": len(inst_ids), "received": len(apps), "pending": len(active),
            "overdue": len([a for a in active if a.status == "IN_PROGRESS" and a.sla_due_at and a.sla_due_at < now]),
            "returned": len([a for a in active if a.status == "RETURNED"]), "approved": len(approved),
            "avg_processing_days": round(sum(pd) / len(pd), 1) if pd else None,
            "sla_breaches": db.query(StageHistory).join(Application, StageHistory.application_id == Application.id).filter(Application.region == r, StageHistory.breached == True).count(),  # noqa: E712
            "undertakings_overdue": db.query(Undertaking).filter(Undertaking.institution_id.in_(inst_ids), Undertaking.status == "OVERDUE").count() if inst_ids else 0,
            "documents_expired": db.query(Document).filter(Document.institution_id.in_(inst_ids), Document.status == "EXPIRED").count() if inst_ids else 0,
            "open_escalations": db.query(Alert).filter(Alert.region == r, Alert.state != "CLOSED", Alert.escalation_level > 0).count(),
        })
    return out


@router.get("/reports/export.csv")
def export_csv(user: User = Depends(require_roles("REGIONAL_OFFICER", "BUREAU_OFFICER", "MEMBER_SECRETARY")), db=Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["App No", "Institution", "PID", "Region", "Category", "Change", "Pipeline", "Stage", "Status", "Priority", "Submitted", "SLA due", "SLA state", "Escalation level"])
    now = clock.now()
    for a in db.query(Application).order_by(Application.id).all():
        if user.role == "REGIONAL_OFFICER" and user.region and a.region != user.region:
            continue
        i = db.get(Institution, a.institution_id)
        s = workflow.sla_status(a, now)
        w.writerow([a.app_no, i.name, i.pid, a.region, a.category, a.change_type, a.pipeline, a.current_stage, a.status, a.priority, a.submitted_at.date() if a.submitted_at else "", a.sla_due_at.date() if a.sla_due_at else "", s["state"], a.escalation_level])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=pravah_pendency.csv"})


# ------------------------------------------------------------------ audit
@router.get("/audit")
def audit_log(limit: int = Query(100, le=1000), action: Optional[str] = None, entity_id: Optional[str] = None, user: User = Depends(get_current_user), db=Depends(get_db)):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if entity_id:
        q = q.filter(AuditLog.entity_id == entity_id)
    rows = q.order_by(AuditLog.id.desc()).limit(limit).all()
    return {"items": [row(e) for e in rows], "chain": audit.verify_chain(db)}


@router.get("/audit/verify")
def audit_verify(user: User = Depends(get_current_user), db=Depends(get_db)):
    return audit.verify_chain(db)


# ------------------------------------------------------------------ rules
@router.get("/rules")
def rules(user: User = Depends(get_current_user), db=Depends(get_db)):
    rs = db.query(RuleSet).filter(RuleSet.active == True).order_by(RuleSet.id.desc()).first()  # noqa: E712
    history = [{"version": r.version, "active": r.active, "created_at": r.created_at.isoformat() if r.created_at else None, "created_by": r.created_by} for r in db.query(RuleSet).order_by(RuleSet.id.desc()).all()]
    return {"rules": rs.rules if rs else workflow.load_rules(db), "history": history}


class RulesIn(BaseModel):
    rules: dict


@router.put("/rules")
def put_rules(body: RulesIn, user: User = Depends(require_roles("ADMIN")), db=Depends(get_db)):
    rs = workflow.save_rules(db, body.rules, user.name)
    return {"version": rs.version}


# ------------------------------------------------------------------ jobs / demo
@router.post("/jobs/run")
def run_jobs(user: User = Depends(get_current_user), db=Depends(get_db)):
    summary = monitor.run_all(db)
    audit.record(db, user.name, "MONITOR_RUN", "system", None, summary, user.role)
    db.commit()
    return summary


@router.get("/jobs/status")
def jobs_status(user: User = Depends(get_current_user)):
    return monitor.status()


class ClockIn(BaseModel):
    days: int


@router.post("/demo/clock")
def demo_clock(body: ClockIn, user: User = Depends(get_current_user), db=Depends(get_db)):
    if not -365 <= body.days <= 365:
        raise HTTPException(422)
    clock.advance(body.days)
    summary = monitor.run_all(db)
    audit.record(db, user.name, "DEMO_CLOCK_ADVANCED", "system", None, {"days": body.days, "offset_days": clock.offset_days()}, user.role)
    db.commit()
    return {"offset_days": clock.offset_days(), "now": clock.now().isoformat(), "monitor": summary}


@router.post("/demo/reset")
def demo_reset(user: User = Depends(require_roles("ADMIN")), db=Depends(get_db)):
    from .db import Base
    from .seed import seed
    db.close()
    clock.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        seed(s)
    finally:
        s.close()
    return {"reset": True}


# ------------------------------------------------------------------ public verification (QR on approval letters)
@router.get("/verify/{code}")
def verify(code: str, db=Depends(get_db)):
    letter = db.query(ApprovalLetter).filter(ApprovalLetter.verify_code == code.upper()).first()
    if not letter:
        return {"valid": False, "code": code, "message": "No approval letter matches this code. Treat the document as unverified and contact AICTE."}
    a = db.get(Application, letter.application_id)
    i = db.get(Institution, a.institution_id)
    return {"valid": True, "code": code.upper(), "letter_no": letter.letter_no, "issued_at": letter.issued_at.isoformat(), "academic_year": letter.academic_year,
            "institution": {"name": i.name, "pid": i.pid, "state": i.state, "district": i.district, "type": i.type},
            "application": {"app_no": a.app_no, "category": a.category, "change_type": a.change_type},
            "courses": letter.courses, "status": "APPROVED", "verified_at": clock.now().isoformat()}


@router.get("/letters/{app_id}/qr.png")
def letter_qr(app_id: int, db=Depends(get_db)):
    letter = db.query(ApprovalLetter).filter(ApprovalLetter.application_id == app_id).first()
    if not letter or not letter.qr_path:
        raise HTTPException(404)
    return FileResponse(letter.qr_path, media_type="image/png")


@router.get("/letters/{app_id}/pdf")
def letter_pdf(app_id: int, db=Depends(get_db)):
    letter = db.query(ApprovalLetter).filter(ApprovalLetter.application_id == app_id).first()
    if not letter:
        raise HTTPException(404)
    a = db.get(Application, letter.application_id)
    i = db.get(Institution, a.institution_id)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w / 2, h - 25 * mm, "ALL INDIA COUNCIL FOR TECHNICAL EDUCATION")
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, h - 30 * mm, "(A Statutory body under Ministry of Education, Govt. of India) - PRAVAH prototype, synthetic data")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(w / 2, h - 42 * mm, f"Extension of Approval (EoA) - Academic Year {letter.academic_year}")
    c.setFont("Helvetica", 10)
    y = h - 55 * mm
    for line in [f"Letter No.: {letter.letter_no}", f"Date: {letter.issued_at.date()}", f"Application No.: {a.app_no}", "",
                 f"To, The Principal/Director, {i.name}", f"Permanent ID: {i.pid}   District: {i.district}   State: {i.state}", "",
                 "Sub: Extension of Approval for the Academic Year " + letter.academic_year, "",
                 "The Council hereby grants approval to the institution for the following programmes:"]:
        c.drawString(25 * mm, y, line)
        y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, y, "Programme")
    c.drawString(150 * mm, y, "Approved intake")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for cr in letter.courses:
        c.drawString(30 * mm, y, str(cr.get("course")))
        c.drawString(150 * mm, y, str(cr.get("proposed_intake") or cr.get("intake")))
        y -= 6 * mm
    y -= 6 * mm
    for line in ["This approval is subject to the conditions of the Approval Process Handbook and the undertakings recorded in PRAVAH.",
                 "Scan the QR code or visit /verify/" + letter.verify_code + " to confirm the authenticity of this letter.", "",
                 "Sd/-", "Director (Approval Bureau)"]:
        c.drawString(25 * mm, y, line)
        y -= 6 * mm
    if letter.qr_path:
        try:
            c.drawImage(letter.qr_path, w - 60 * mm, 25 * mm, 35 * mm, 35 * mm)
            c.setFont("Helvetica", 8)
            c.drawString(w - 60 * mm, 22 * mm, f"Verify code: {letter.verify_code}")
        except Exception:
            pass
    c.showPage()
    c.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f"inline; filename={letter.letter_no.replace('/', '_')}.pdf"})
