"""Synthetic demo dataset (no real institutions or persons). Deterministic via random.seed."""
import hashlib
import random
from datetime import timedelta

from . import audit, clock, monitor
from .auth import hash_pw
from .models import Application, Document, EVCVisit, Institution, StageHistory, Undertaking, User
from .workflow import enter_stage, issue_letter, load_rules, priority_for, resolve_pipeline

REGION_LABELS = {
    "SOUTHERN": "Southern RO (Chennai)", "SOUTH_CENTRAL": "South-Central RO (Hyderabad)", "SOUTH_WEST": "South-West RO (Bengaluru)",
    "WESTERN": "Western RO (Mumbai)", "CENTRAL": "Central RO (Bhopal)", "NORTHERN": "Northern RO (Kanpur)",
    "NORTH_WEST": "North-West RO (Chandigarh)", "EASTERN": "Eastern RO (Kolkata)", "NORTH_EAST": "North-East RO (Guwahati)",
}

INSTITUTIONS = [
    ("1-4471", "Nalanda Institute of Technology, Guntur", "Engineering", "Andhra Pradesh", "Guntur", "SOUTH_CENTRAL", 2004),
    ("1-4502", "Coastal Engineering College, Mangaluru", "Engineering", "Karnataka", "Dakshina Kannada", "SOUTH_WEST", 1998),
    ("1-4388", "Chola Institute of Technology, Thanjavur", "Engineering", "Tamil Nadu", "Thanjavur", "SOUTHERN", 2009),
    ("1-4419", "Malabar Institute of Pharmacy, Kozhikode", "Pharmacy", "Kerala", "Kozhikode", "SOUTH_WEST", 2011),
    ("1-4530", "Deccan College of Pharmacy, Hyderabad", "Pharmacy", "Telangana", "Hyderabad", "SOUTH_CENTRAL", 2001),
    ("1-4390", "Sri Vidya Polytechnic, Salem", "Polytechnic", "Tamil Nadu", "Salem", "SOUTHERN", 1995),
    ("1-4611", "Sahyadri Polytechnic, Kolhapur", "Polytechnic", "Maharashtra", "Kolhapur", "WESTERN", 1988),
    ("1-4622", "Saraswati Institute of Management Studies, Pune", "Management", "Maharashtra", "Pune", "WESTERN", 2006),
    ("1-4703", "Vindhya Institute of Management, Bhopal", "Management", "Madhya Pradesh", "Bhopal", "CENTRAL", 2012),
    ("1-4815", "Ganga Valley Engineering College, Kanpur", "Engineering", "Uttar Pradesh", "Kanpur Nagar", "NORTHERN", 2000),
    ("1-4820", "Aravalli School of Architecture, Jaipur", "Architecture", "Rajasthan", "Jaipur", "NORTH_WEST", 2015),
    ("1-4901", "Hooghly College of Engineering, Howrah", "Engineering", "West Bengal", "Howrah", "EASTERN", 2003),
    ("1-4933", "Brahmaputra Institute of Technology, Guwahati", "Engineering", "Assam", "Kamrup", "NORTH_EAST", 2010),
    ("1-4522", "Kaveri College of Engineering, Mysuru", "Engineering", "Karnataka", "Mysuru", "SOUTH_WEST", 2002),
]

USERS = [
    ("admin", "System Administrator", "Admin, Regulation Bureau", "ADMIN", None, None),
    ("ro.south", "Dr. R. Meenakshi", "Dy. Director (Approval), Southern RO", "REGIONAL_OFFICER", "SOUTHERN", None),
    ("ro.southcentral", "Sh. P. Venkat Rao", "Dy. Director (Approval), South-Central RO", "REGIONAL_OFFICER", "SOUTH_CENTRAL", None),
    ("ro.southwest", "Smt. L. Hegde", "Dy. Director (Approval), South-West RO", "REGIONAL_OFFICER", "SOUTH_WEST", None),
    ("ro.west", "Sh. A. Kulkarni", "Dy. Director (Approval), Western RO", "REGIONAL_OFFICER", "WESTERN", None),
    ("ro.north", "Dr. S. Tripathi", "Dy. Director (Approval), Northern RO", "REGIONAL_OFFICER", "NORTHERN", None),
    ("ro.east", "Sh. D. Sen", "Dy. Director (Approval), Eastern RO", "REGIONAL_OFFICER", "EASTERN", None),
    ("bureau", "Sh. A. K. Verma", "Director, Approval Bureau", "BUREAU_OFFICER", None, None),
    ("ms", "Member Secretary", "Member Secretary, AICTE", "MEMBER_SECRETARY", None, None),
    ("evc.iyer", "Prof. S. Iyer", "EVC Expert - Civil / Infrastructure", "EVC_MEMBER", None, None),
    ("inst.nalanda", "Registrar, Nalanda Institute of Technology", "Institution user", "INSTITUTION", None, "1-4471"),
    ("inst.deccan", "Principal, Deccan College of Pharmacy", "Institution user", "INSTITUTION", None, "1-4530"),
    ("inst.coastal", "Registrar, Coastal Engineering College", "Institution user", "INSTITUTION", None, "1-4502"),
]

COURSES = {
    "Engineering": [("B.E./B.Tech - Computer Science & Engineering", 120), ("B.E./B.Tech - Electronics & Communication", 60), ("B.E./B.Tech - Mechanical Engineering", 60), ("B.E./B.Tech - AI & Data Science", 60)],
    "Pharmacy": [("B.Pharm", 100), ("D.Pharm", 60), ("M.Pharm - Pharmaceutics", 15)],
    "Polytechnic": [("Diploma - Civil Engineering", 60), ("Diploma - Mechanical Engineering", 60), ("Diploma - Computer Engineering", 60)],
    "Management": [("MBA", 120), ("PGDM", 60)],
    "Architecture": [("B.Arch", 40)],
}

RETURN_REASONS = [
    "Fire NOC uploaded is for a different building block; submit NOC covering all academic blocks.",
    "Faculty list does not meet the prescribed 1:20 ratio for the proposed intake; upload appointment orders.",
    "Land documents do not show contiguous land as required; submit survey sketch and encumbrance certificate.",
    "Building completion certificate missing for the new block; upload occupancy certificate.",
]

UNDERTAKINGS = [
    ("FACULTY", "Recruit 6 regular faculty in CSE to meet the 1:20 ratio and upload appointment orders"),
    ("INFRASTRUCTURE", "Complete construction of Laboratory Block-B (1,200 sq.m) and submit completion certificate"),
    ("LIBRARY", "Procure 2,000 additional volumes and e-journal subscription; submit invoices"),
    ("LAND", "Register the remaining 1.2 acres in the name of the Trust and submit sale deed"),
    ("FINANCIAL", "Submit audited statements and FDR of Rs 50 lakh as security deposit"),
    ("OTHER", "Appoint a regular Principal with prescribed qualifications and upload appointment order"),
]

DOC_TYPES = [
    ("LEASE_DEED", "Registered lease deed - academic campus", "Sub-Registrar Office", 10 * 365),
    ("FIRE_NOC", "Fire safety NOC", "State Fire & Rescue Services", 365),
    ("BUILDING_SAFETY", "Structural stability certificate", "Chartered Structural Engineer", 3 * 365),
    ("AFFIDAVIT", "Affidavit on prescribed format (Rs 100 stamp paper)", "Notary Public", 365),
    ("OCCUPANCY_CERT", "Building occupancy certificate", "Municipal Corporation", 20 * 365),
]


def seed(db):
    if db.query(Institution).count():
        return False
    rnd = random.Random(26262)
    rules = load_rules(db)
    now = clock.now()

    insts = {}
    for pid, name, typ, state, district, region, year in INSTITUTIONS:
        inst = Institution(pid=pid, name=name, type=typ, state=state, district=district, region=region, established_year=year,
                           email=f"principal@{pid.replace('-', '')}.edu.in", phone=f"+91-98{rnd.randint(10000000, 99999999)}",
                           compliance_score=100.0, compliance_band="GREEN", score_breakdown=[])
        db.add(inst)
        insts[pid] = inst
    db.flush()

    for uname, name, desig, role, region, inst_pid in USERS:
        db.add(User(username=uname, password_hash=hash_pw("demo123"), name=name, designation=desig, role=role, region=region,
                    institution_id=insts[inst_pid].id if inst_pid else None,
                    email=f"{uname}@{'aicte-demo.gov.in' if role != 'INSTITUTION' else 'institution-demo.edu.in'}",
                    phone=f"+91-99{rnd.randint(10000000, 99999999)}"))
    db.flush()

    # ---- documents (validity spread: expired, expiring, valid) + one deliberate cross-institution reuse
    for pid, inst in insts.items():
        for dt, title, auth, life in DOC_TYPES:
            if dt == "OCCUPANCY_CERT" and rnd.random() < 0.5:
                continue
            offset = rnd.choice([-40, -12, 5, 18, 25, 45, 80, 140, 300, 600, 900])
            valid_till = now.date() + timedelta(days=offset)
            issued = valid_till - timedelta(days=life)
            ref = f"{dt[:3]}/{inst.state[:2].upper()}/{rnd.randint(1000, 9999)}/{issued.year}"
            db.add(Document(institution_id=inst.id, doc_type=dt, title=title, ref_no=ref, issuing_authority=auth, issued_on=issued,
                            valid_till=valid_till, status="VALID", sha256=hashlib.sha256(f"{pid}:{dt}:{ref}".encode()).hexdigest(), alerts_sent=[]))
    db.flush()
    reused = hashlib.sha256(b"same-fire-noc-scan.pdf").hexdigest()
    for pid in ("1-4390", "1-4611"):
        d = db.query(Document).filter(Document.institution_id == insts[pid].id, Document.doc_type == "FIRE_NOC").first()
        d.sha256 = reused

    # ---- undertakings
    for pid, inst in insts.items():
        for cat, cond in rnd.sample(UNDERTAKINGS, rnd.randint(1, 3)):
            due = now.date() + timedelta(days=rnd.choice([-25, -9, -3, 2, 6, 12, 20, 28, 45, 75, 120]))
            st = "PENDING"
            ev = None
            if due < now.date() and rnd.random() < 0.35:
                st = "SUBMITTED"
                ev = {"filename": f"{cat.lower()}_evidence.pdf", "note": "Uploaded by institution", "submitted_at": (now - timedelta(days=1)).isoformat()}
            db.add(Undertaking(institution_id=inst.id, category=cat, condition=cond, due_date=due, status=st, evidence=ev, reminders_sent=0))
    db.flush()

    # ---- applications across stages / ages
    cats = [("EOA", "NONE")] * 5 + [("EOA", "INCREASE_INTAKE")] * 3 + [("EOA", "NEW_COURSE")] * 3 + [("NEW_INSTITUTION", "NONE")] * 2 + [("CLOSURE", "NONE"), ("CHANGE_OF_SITE", "NONE"), ("CHANGE_OF_NAME", "NONE")]
    seq = 0
    inst_list = list(insts.values())
    for i in range(46):
        inst = inst_list[i % len(inst_list)]
        cat, chg = rnd.choice(cats)
        pipeline, note = resolve_pipeline(rules, cat, chg)
        stages = rules["pipelines"][pipeline]
        seq += 1
        courses = [{"course": c, "intake": n} for c, n in rnd.sample(COURSES[inst.type], min(2, len(COURSES[inst.type])))]
        if chg == "INCREASE_INTAKE":
            courses[0]["proposed_intake"] = courses[0]["intake"] + 60
        total_age = rnd.choice([rnd.randint(1, 12), rnd.randint(5, 25), rnd.randint(10, 45), rnd.randint(20, 70)])
        submitted = now - timedelta(days=total_age, hours=rnd.randint(0, 9))
        app = Application(app_no=f"1-{submitted.year}-{4400 + seq:05d}", institution_id=inst.id, category=cat, change_type=chg, academic_year="2026-27",
                          details={"courses": courses, "remarks": "Synthetic demo record"}, pipeline=pipeline, stage_index=0, status="IN_PROGRESS",
                          priority=rnd.choice(["NORMAL", "NORMAL", "NORMAL", "GREEN_CHANNEL"]), region=inst.region, submitted_at=submitted, routing_note=note)
        db.add(app)
        db.flush()
        app.institution = inst
        # walk through stages
        # weight toward early stages; len(stages) => approved
        target = min(len(stages), rnd.choice([0, 0, 0, 1, 1, 1, 2, 2, 3, len(stages), len(stages), len(stages)]))
        t = submitted
        remaining = total_age
        for k, st in enumerate(stages):
            if k == target:
                enter_stage(db, app, st, t, rules, "system")
                app.stage_index = k
                break
            sla_here = rules["stages"][st]["sla_days"]
            dur = max(1, min(remaining - 1, rnd.randint(max(1, sla_here - 3), sla_here + 4))) if remaining > 2 else 1
            sla = rules["stages"][st]["sla_days"]
            db.add(StageHistory(application_id=app.id, stage=st, entered_at=t, exited_at=t + timedelta(days=dur), action="ADVANCED",
                                actor="officer", remarks="Stage completed", sla_days=sla, breached=dur > sla))
            if st == "EVC":
                db.add(EVCVisit(application_id=app.id, institution_id=inst.id, status="COMPLETED", queued_at=t, due_by=t + timedelta(days=10),
                                scheduled_on=(t + timedelta(days=dur - 1)).date(), members=[{"name": "Prof. S. Iyer"}, {"name": "Dr. K. Bhattacharya"}, {"name": "Dr. P. Nair"}],
                                report_submitted_at=t + timedelta(days=dur), outcome="RECOMMENDED", cluster_key=inst.state))
            t += timedelta(days=dur)
            remaining -= dur
        else:
            app.status = "APPROVED"
            app.current_stage = "APPROVED"
            app.decided_at = t
            app.stage_index = len(stages) - 1
            db.add(StageHistory(application_id=app.id, stage="APPROVED", entered_at=t, exited_at=t, action="APPROVED", actor="Sh. A. K. Verma", remarks="EoA granted", sla_days=0))
            issue_letter(db, app, t)
        # some returned
        if app.status == "IN_PROGRESS" and rnd.random() < 0.15:
            app.status = "RETURNED"
            app.return_reason = rnd.choice(RETURN_REASONS)
            app.return_count = 1
            db.add(StageHistory(application_id=app.id, stage="WITH_INSTITUTION", entered_at=now - timedelta(days=rnd.randint(1, 8)), action="ENTERED", actor="officer", remarks=app.return_reason, sla_days=0))
        # mark some EVC visits scheduled / overdue
        if app.status == "IN_PROGRESS" and app.current_stage == "EVC":
            v = db.query(EVCVisit).filter(EVCVisit.application_id == app.id).first()
            if v and rnd.random() < 0.5:
                v.status = "SCHEDULED"
                v.scheduled_on = (now + timedelta(days=rnd.randint(-4, 9))).date()
                v.members = [{"name": "Prof. S. Iyer", "expertise": "Civil / Infrastructure"}, {"name": "Dr. K. Bhattacharya", "expertise": "Computer Science"}, {"name": "Dr. L. Reddy", "expertise": "Electronics"}]
    db.flush()

    audit.record(db, "system", "SEED", "system", None, {"institutions": len(insts), "applications": db.query(Application).count(), "note": "synthetic demo data"})
    db.commit()
    monitor.run_all(db)
    # priority re-evaluation after scores are known
    for app in db.query(Application).filter(Application.status == "IN_PROGRESS").all():
        p = priority_for(rules, db.get(Institution, app.institution_id))
        if p == "HIGH_RISK":
            app.priority = "HIGH_RISK"
    db.commit()
    return True
