"""Institution Compliance Score -> Green Channel / High Risk bands (configurable weights)."""
from .models import Alert, Application, Document, Undertaking


def compute(db, inst, rules):
    w = rules.get("compliance_score", {})
    bands = w.get("bands", {"GREEN": 85, "AMBER": 60})
    score = 100.0
    breakdown = []

    expired = db.query(Document).filter(Document.institution_id == inst.id, Document.status == "EXPIRED").count()
    if expired:
        d = expired * w.get("expired_document", 15)
        score -= d
        breakdown.append({"factor": "Expired prescribed documents", "count": expired, "delta": -d})

    overdue = db.query(Undertaking).filter(Undertaking.institution_id == inst.id, Undertaking.status == "OVERDUE").count()
    if overdue:
        d = overdue * w.get("overdue_undertaking", 8)
        score -= d
        breakdown.append({"factor": "Overdue undertakings", "count": overdue, "delta": -d})

    returns = sum(a.return_count or 0 for a in db.query(Application).filter(Application.institution_id == inst.id).all())
    if returns:
        d = returns * w.get("return_cycle", 5)
        score -= d
        breakdown.append({"factor": "Return-for-deficiency cycles", "count": returns, "delta": -d})

    esc = db.query(Alert).filter(Alert.institution_id == inst.id, Alert.state != "CLOSED", Alert.escalation_level > 0).count()
    if esc:
        d = esc * w.get("open_escalation", 5)
        score -= d
        breakdown.append({"factor": "Open escalations", "count": esc, "delta": -d})

    reuse = db.query(Alert).filter(Alert.institution_id == inst.id, Alert.kind == "DOCUMENT_REUSE", Alert.state != "CLOSED").count()
    if reuse:
        d = reuse * w.get("document_reuse", 20)
        score -= d
        breakdown.append({"factor": "Document fingerprint reused across institutions", "count": reuse, "delta": -d})

    score = max(0.0, min(100.0, score))
    band = "GREEN" if score >= bands.get("GREEN", 85) else ("AMBER" if score >= bands.get("AMBER", 60) else "RED")
    inst.compliance_score = round(score, 1)
    inst.compliance_band = band
    inst.score_breakdown = breakdown
    return score, band
