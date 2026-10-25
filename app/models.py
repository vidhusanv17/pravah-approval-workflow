from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .db import Base


class RuleSet(Base):
    __tablename__ = "rulesets"
    id = Column(Integer, primary_key=True)
    version = Column(String(64), nullable=False)
    rules = Column(JSON, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    created_by = Column(String(64))


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    name = Column(String(128))
    designation = Column(String(128))
    # INSTITUTION | REGIONAL_OFFICER | BUREAU_OFFICER | EVC_MEMBER | MEMBER_SECRETARY | ADMIN
    role = Column(String(32), nullable=False)
    region = Column(String(32), nullable=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=True)
    email = Column(String(128))
    phone = Column(String(32))


class Institution(Base):
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True)
    pid = Column(String(16), unique=True, index=True)  # AICTE Permanent ID (synthetic)
    name = Column(String(200), nullable=False)
    type = Column(String(32))
    state = Column(String(64))
    district = Column(String(64))
    region = Column(String(32), index=True)
    email = Column(String(128))
    phone = Column(String(32))
    established_year = Column(Integer)
    compliance_score = Column(Float, default=100.0)
    compliance_band = Column(String(8), default="GREEN")
    score_breakdown = Column(JSON, default=list)


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    app_no = Column(String(32), unique=True, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    category = Column(String(32), nullable=False)  # EOA | NEW_INSTITUTION | CLOSURE | CHANGE_OF_SITE | CHANGE_OF_NAME
    change_type = Column(String(32), default="NONE")  # NONE | INCREASE_INTAKE | NEW_COURSE | REDUCTION | ...
    academic_year = Column(String(16))
    details = Column(JSON, default=dict)
    pipeline = Column(String(32))
    stage_index = Column(Integer, default=0)
    current_stage = Column(String(32), index=True)
    status = Column(String(16), default="IN_PROGRESS", index=True)  # IN_PROGRESS | RETURNED | APPROVED | REJECTED
    priority = Column(String(16), default="NORMAL")  # NORMAL | GREEN_CHANNEL | HIGH_RISK
    region = Column(String(32), index=True)
    submitted_at = Column(DateTime)
    stage_entered_at = Column(DateTime)
    sla_due_at = Column(DateTime)
    decided_at = Column(DateTime, nullable=True)
    assigned_role = Column(String(32))
    return_reason = Column(Text, nullable=True)
    return_count = Column(Integer, default=0)
    escalation_level = Column(Integer, default=0)
    routing_note = Column(String(200), nullable=True)

    institution = relationship("Institution")


class StageHistory(Base):
    __tablename__ = "stage_history"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    stage = Column(String(32))
    entered_at = Column(DateTime)
    exited_at = Column(DateTime, nullable=True)
    action = Column(String(32))  # ENTERED | ADVANCED | RETURNED | RESUBMITTED | APPROVED
    actor = Column(String(128))
    remarks = Column(Text)
    sla_days = Column(Integer)
    breached = Column(Boolean, default=False)


class EVCVisit(Base):
    __tablename__ = "evc_visits"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), unique=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"))
    status = Column(String(16), default="QUEUED")  # QUEUED | SCHEDULED | COMPLETED
    queued_at = Column(DateTime)
    due_by = Column(DateTime)
    scheduled_on = Column(Date, nullable=True)
    members = Column(JSON, default=list)
    report_submitted_at = Column(DateTime, nullable=True)
    outcome = Column(String(32), nullable=True)  # RECOMMENDED | DEFICIENCIES | NOT_RECOMMENDED
    cluster_key = Column(String(64))
    remarks = Column(Text)


class Undertaking(Base):
    __tablename__ = "undertakings"
    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True)
    category = Column(String(32))  # FACULTY | INFRASTRUCTURE | LAND | LIBRARY | FINANCIAL | OTHER
    condition = Column(Text)
    due_date = Column(Date)
    status = Column(String(16), default="PENDING")  # PENDING | SUBMITTED | VERIFIED | OVERDUE | REJECTED
    evidence = Column(JSON, nullable=True)
    reminders_sent = Column(Integer, default=0)
    escalated = Column(Boolean, default=False)
    verified_by = Column(String(128), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    carried_forward_from = Column(Integer, nullable=True)


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), index=True)
    doc_type = Column(String(32))  # LEASE_DEED | FIRE_NOC | BUILDING_SAFETY | AFFIDAVIT | LAND_DOC | OCCUPANCY_CERT
    title = Column(String(200))
    ref_no = Column(String(64))
    issuing_authority = Column(String(128))
    issued_on = Column(Date)
    valid_till = Column(Date)
    status = Column(String(24), default="VALID")  # VALID | EXPIRING | EXPIRED | RENEWAL_SUBMITTED | RENEWED | SUPERSEDED
    sha256 = Column(String(64), index=True)
    renewal_of_id = Column(Integer, nullable=True)
    renewal = Column(JSON, nullable=True)
    alerts_sent = Column(JSON, default=list)
    verified_by = Column(String(128), nullable=True)
    verified_at = Column(DateTime, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    dedupe_key = Column(String(128), unique=True, index=True)
    kind = Column(String(48), index=True)
    severity = Column(String(16))  # INFO | WARNING | CRITICAL
    entity_type = Column(String(32))
    entity_id = Column(Integer)
    institution_id = Column(Integer, nullable=True)
    application_id = Column(Integer, nullable=True)
    region = Column(String(32), nullable=True)
    title = Column(String(200))
    message = Column(Text)
    created_at = Column(DateTime)
    due_at = Column(DateTime, nullable=True)
    state = Column(String(16), default="OPEN")  # OPEN | ACKNOWLEDGED | CLOSED
    escalation_level = Column(Integer, default=0)
    escalated_to_role = Column(String(32), nullable=True)
    audience = Column(JSON, default=dict)
    acknowledged_by = Column(String(128), nullable=True)
    closed_at = Column(DateTime, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    channel = Column(String(16))  # IN_APP | EMAIL | SMS | WHATSAPP
    recipient = Column(String(128))
    recipient_role = Column(String(32))
    body = Column(Text)
    status = Column(String(16), default="SENT")
    sent_at = Column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime)
    actor = Column(String(128))
    actor_role = Column(String(32))
    action = Column(String(64), index=True)
    entity_type = Column(String(32))
    entity_id = Column(String(32))
    details = Column(JSON, default=dict)
    prev_hash = Column(String(64))
    hash = Column(String(64))


class ApprovalLetter(Base):
    __tablename__ = "approval_letters"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), unique=True)
    letter_no = Column(String(48), unique=True)
    issued_at = Column(DateTime)
    verify_code = Column(String(32), unique=True, index=True)
    academic_year = Column(String(16))
    courses = Column(JSON, default=list)
    qr_path = Column(String(200))
