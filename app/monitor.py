"""Deadline scanner: SLA warnings/overdue + escalation ladder, EVC timelines, undertakings, document
validity, cross-institution document reuse, compliance scores. Idempotent (alerts are de-duplicated), so it
can run from the background scheduler (Celery beat in production) or on demand."""
import threading
import time
from collections import defaultdict
from datetime import timedelta

from . import audit, clock, notify, scoring
from .db import SessionLocal
from .models import Alert, Application, Document, EVCVisit, Institution, Undertaking, User
from .workflow import load_rules

_state = {"last_run": None, "last_summary": None, "runs": 0}


def _alert(db, rules, key, kind, severity, entity_type, entity_id, title, message, *, institution=None, application=None,
           region=None, due_at=None, roles=None, to_institution=False, members=None, level=0, escalated_to=None):
    if db.query(Alert).filter(Alert.dedupe_key == key).first():
        return None
    a = Alert(dedupe_key=key, kind=kind, severity=severity, entity_type=entity_type, entity_id=entity_id,
              institution_id=institution.id if institution else None, application_id=application.id if application else None,
              region=region or (institution.region if institution else None), title=title, message=message, created_at=clock.now(),
              due_at=due_at, state="OPEN", escalation_level=level, escalated_to_role=escalated_to,
              audience={"roles": roles or [], "institution": to_institution, "members": members or []})
    db.add(a)
    db.flush()
    notify.dispatch(db, a, rules, institution)
    return a


def _escalation_level(rules, overdue_days):
    lvl, role, label = 0, None, None
    for i, step in enumerate(rules["escalation"]["levels"]):
        if overdue_days >= step["after_overdue_days"]:
            lvl, role, label = i + 1, step["to_role"], step.get("label")
    return lvl, role, label


def scan_applications(db, rules, now, counts):
    warn = rules["escalation"].get("warn_days_before_sla", 2)
    for app in db.query(Application).filter(Application.status == "IN_PROGRESS").all():
        inst = db.get(Institution, app.institution_id)
        if not app.sla_due_at:
            continue
        remaining = (app.sla_due_at - now).days
        stage_key = f"{app.id}:{app.current_stage}:{app.stage_entered_at.isoformat() if app.stage_entered_at else ''}"
        if 0 <= remaining <= warn:
            if _alert(db, rules, f"SLA_WARN:{stage_key}", "SLA_APPROACHING", "WARNING", "application", app.id,
                      f"{app.app_no} approaching timeline at {app.current_stage}",
                      f"{inst.name}: prescribed {app.current_stage} timeline ends in {remaining} day(s) ({app.sla_due_at.date()}).",
                      institution=inst, application=app, due_at=app.sla_due_at, roles=[app.assigned_role]):
                counts["sla_warnings"] += 1
        elif now > app.sla_due_at:
            overdue_days = (now - app.sla_due_at).days
            lvl, role, label = _escalation_level(rules, overdue_days)
            if lvl > (app.escalation_level or 0):
                app.escalation_level = lvl
                if _alert(db, rules, f"SLA_OVERDUE:{stage_key}:L{lvl}", "SLA_OVERDUE", "CRITICAL", "application", app.id,
                          f"{app.app_no} overdue {overdue_days}d at {app.current_stage} - escalated {label}",
                          f"{inst.name}: {app.current_stage} exceeded its prescribed timeline by {overdue_days} day(s). Escalated to {role}.",
                          institution=inst, application=app, due_at=app.sla_due_at, roles=list({app.assigned_role, role}), level=lvl, escalated_to=role):
                    counts["escalations"] += 1
                    audit.record(db, "system", "ESCALATED", "application", app.app_no, {"level": lvl, "to_role": role, "overdue_days": overdue_days})
        if app.status == "RETURNED":
            pass


def scan_evc(db, rules, now, counts):
    ev = rules.get("evc", {})
    remind = ev.get("reminder_days_before", 3)
    for v in db.query(EVCVisit).filter(EVCVisit.status.in_(["QUEUED", "SCHEDULED"])).all():
        app = db.get(Application, v.application_id)
        inst = db.get(Institution, v.institution_id)
        if v.status == "QUEUED" and v.due_by:
            d = (v.due_by - now).days
            if d < 0:
                lvl, role, label = _escalation_level(rules, -d)
                if _alert(db, rules, f"EVC_OVERDUE:{v.id}:L{lvl}", "EVC_OVERDUE", "CRITICAL", "evc", v.id,
                          f"EVC not scheduled for {app.app_no} - {-d}d past due",
                          f"{inst.name}: EVC should have been scheduled by {v.due_by.date()}. Escalated {label}.",
                          institution=inst, application=app, due_at=v.due_by, roles=["REGIONAL_OFFICER", role], level=lvl, escalated_to=role):
                    counts["evc_alerts"] += 1
            elif d <= remind:
                if _alert(db, rules, f"EVC_DUE:{v.id}", "EVC_SCHEDULING_DUE", "WARNING", "evc", v.id,
                          f"Schedule EVC for {app.app_no} within {d} day(s)",
                          f"{inst.name}: EVC scheduling deadline {v.due_by.date()}.", institution=inst, application=app, due_at=v.due_by, roles=["REGIONAL_OFFICER"]):
                    counts["evc_alerts"] += 1
        elif v.status == "SCHEDULED" and v.scheduled_on:
            d = (v.scheduled_on - now.date()).days
            if 0 <= d <= remind:
                if _alert(db, rules, f"EVC_VISIT:{v.id}", "EVC_VISIT_REMINDER", "INFO", "evc", v.id,
                          f"EVC visit to {inst.name} on {v.scheduled_on}",
                          f"Committee: {', '.join(m.get('name', '') for m in (v.members or []))}. Application {app.app_no}.",
                          institution=inst, application=app, roles=[], to_institution=True, members=[m.get("name") for m in (v.members or [])]):
                    counts["evc_alerts"] += 1
            elif d < -1:
                if _alert(db, rules, f"EVC_REPORT:{v.id}", "EVC_REPORT_PENDING", "WARNING", "evc", v.id,
                          f"EVC report pending for {app.app_no}",
                          f"Visit took place on {v.scheduled_on}; report not yet submitted ({-d} days).", institution=inst, application=app, roles=["REGIONAL_OFFICER"], members=[m.get("name") for m in (v.members or [])]):
                    counts["evc_alerts"] += 1


def scan_undertakings(db, rules, now, counts):
    cfg = rules.get("undertakings", {})
    windows = sorted(cfg.get("reminder_days_before", [30, 15, 7, 1]), reverse=True)
    esc_after = cfg.get("escalate_after_overdue_days", 7)
    today = now.date()
    for u in db.query(Undertaking).filter(Undertaking.status.in_(["PENDING", "OVERDUE"])).all():
        inst = db.get(Institution, u.institution_id)
        d = (u.due_date - today).days
        if d >= 0:
            for w in windows:
                if d <= w:
                    if _alert(db, rules, f"UT_REMIND:{u.id}:{w}", "UNDERTAKING_DUE", "WARNING" if w <= 7 else "INFO", "undertaking", u.id,
                              f"Undertaking due in {d} day(s): {u.category.title()}",
                              f"{inst.name}: '{u.condition}' due {u.due_date}. Please upload compliance evidence.",
                              institution=inst, due_at=now + timedelta(days=d), roles=[], to_institution=True):
                        u.reminders_sent = (u.reminders_sent or 0) + 1
                        counts["undertaking_reminders"] += 1
                    break
        else:
            if u.status != "OVERDUE":
                u.status = "OVERDUE"
                audit.record(db, "system", "UNDERTAKING_OVERDUE", "undertaking", u.id, {"institution": inst.name, "due_date": str(u.due_date)})
            overdue = -d
            if _alert(db, rules, f"UT_OVERDUE:{u.id}", "UNDERTAKING_OVERDUE", "CRITICAL", "undertaking", u.id,
                      f"Undertaking overdue {overdue}d: {u.category.title()}",
                      f"{inst.name}: '{u.condition}' was due {u.due_date}; no evidence received.",
                      institution=inst, roles=["REGIONAL_OFFICER"], to_institution=True):
                counts["undertaking_overdue"] += 1
            if overdue >= esc_after and not u.escalated:
                u.escalated = True
                _alert(db, rules, f"UT_ESC:{u.id}", "UNDERTAKING_ESCALATED", "CRITICAL", "undertaking", u.id,
                       f"Unfulfilled undertaking escalated - {inst.name}",
                       f"'{u.condition}' overdue by {overdue} days beyond the stipulated timeline. Escalated to Bureau for action under APH.",
                       institution=inst, roles=["BUREAU_OFFICER"], level=2, escalated_to="BUREAU_OFFICER")
                counts["escalations"] += 1


def scan_documents(db, rules, now, counts):
    cfg = rules.get("documents", {})
    windows = sorted(cfg.get("expiry_alert_days_before", [90, 60, 30, 7]), reverse=True)
    esc_after = cfg.get("escalate_after_expired_days", 15)
    today = now.date()
    for doc in db.query(Document).filter(Document.status.in_(["VALID", "EXPIRING", "EXPIRED"])).all():
        inst = db.get(Institution, doc.institution_id)
        d = (doc.valid_till - today).days
        if d < 0:
            if doc.status != "EXPIRED":
                doc.status = "EXPIRED"
                audit.record(db, "system", "DOCUMENT_EXPIRED", "document", doc.id, {"institution": inst.name, "doc_type": doc.doc_type, "valid_till": str(doc.valid_till)})
            if _alert(db, rules, f"DOC_EXPIRED:{doc.id}", "DOCUMENT_EXPIRED", "CRITICAL", "document", doc.id,
                      f"{doc.doc_type.replace('_', ' ').title()} expired - {inst.name}",
                      f"{doc.title} (ref {doc.ref_no}) expired on {doc.valid_till}. Renewed document must be submitted.",
                      institution=inst, roles=["REGIONAL_OFFICER"], to_institution=True):
                counts["doc_expired"] += 1
            if -d >= esc_after:
                if _alert(db, rules, f"DOC_ESC:{doc.id}", "DOCUMENT_EXPIRY_ESCALATED", "CRITICAL", "document", doc.id,
                          f"Expired {doc.doc_type.replace('_', ' ').lower()} unresolved {-d}d - escalated",
                          f"{inst.name} has not submitted a renewal for {doc.title}. Escalated to Bureau Officer.",
                          institution=inst, roles=["BUREAU_OFFICER"], level=2, escalated_to="BUREAU_OFFICER"):
                    counts["escalations"] += 1
        else:
            for w in windows:
                if d <= w:
                    if doc.status == "VALID" and d <= min(windows + [90]):
                        doc.status = "EXPIRING"
                    if _alert(db, rules, f"DOC_EXPIRING:{doc.id}:{w}", "DOCUMENT_EXPIRING", "WARNING" if w <= 30 else "INFO", "document", doc.id,
                              f"{doc.doc_type.replace('_', ' ').title()} expires in {d} day(s) - {inst.name}",
                              f"{doc.title} (ref {doc.ref_no}) valid till {doc.valid_till}. Submit the renewed document in advance.",
                              institution=inst, due_at=now + timedelta(days=d), roles=["REGIONAL_OFFICER"] if w <= 30 else [], to_institution=True):
                        sent = list(doc.alerts_sent or [])
                        sent.append(w)
                        doc.alerts_sent = sent
                        counts["doc_expiring"] += 1
                    break
            else:
                if doc.status == "EXPIRING":
                    doc.status = "VALID"


def scan_document_reuse(db, rules, now, counts):
    """Document fingerprinting: the same file hash submitted by two different institutions."""
    by_hash = defaultdict(list)
    for doc in db.query(Document).filter(Document.sha256 != None).all():  # noqa: E711
        by_hash[doc.sha256].append(doc)
    for h, docs in by_hash.items():
        insts = {d.institution_id for d in docs}
        if len(insts) > 1:
            for d in docs:
                inst = db.get(Institution, d.institution_id)
                others = [db.get(Institution, o.institution_id).name for o in docs if o.institution_id != d.institution_id]
                if _alert(db, rules, f"DOC_REUSE:{h[:12]}:{d.id}", "DOCUMENT_REUSE", "CRITICAL", "document", d.id,
                          f"Document fingerprint reused across institutions - {d.doc_type.replace('_', ' ').title()}",
                          f"SHA-256 {h[:16]}... of '{d.title}' submitted by {inst.name} also appears in records of: {', '.join(others)}. Manual verification required.",
                          institution=inst, roles=["REGIONAL_OFFICER", "BUREAU_OFFICER"]):
                    counts["document_reuse"] += 1


def run_all(db):
    rules = load_rules(db)
    now = clock.now()
    counts = defaultdict(int)
    scan_applications(db, rules, now, counts)
    scan_evc(db, rules, now, counts)
    scan_undertakings(db, rules, now, counts)
    scan_documents(db, rules, now, counts)
    scan_document_reuse(db, rules, now, counts)
    for inst in db.query(Institution).all():
        scoring.compute(db, inst, rules)
    db.commit()
    summary = {"ran_at": now.isoformat(), "clock_offset_days": clock.offset_days(), **counts}
    _state["last_run"] = now.isoformat()
    _state["last_summary"] = summary
    _state["runs"] += 1
    return summary


def status():
    return dict(_state)


def start_background(interval_seconds: int):
    def loop():
        while True:
            time.sleep(interval_seconds)
            db = SessionLocal()
            try:
                run_all(db)
            except Exception as e:  # pragma: no cover
                print("monitor error:", e)
            finally:
                db.close()
    t = threading.Thread(target=loop, daemon=True, name="pravah-monitor")
    t.start()
    return t
