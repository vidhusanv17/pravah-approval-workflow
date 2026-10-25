"""Notification dispatcher. In the prototype every channel is simulated: messages are stored in the
notifications table and appended to data/outbox.log. Production swaps in NIC e-mail, SMS gateway and the
WhatsApp Business API behind the same send() signature."""
from . import clock
from .db import DATA_DIR
from .models import Notification, User

OUTBOX = DATA_DIR / "outbox.log"


def _channels(rules, severity):
    table = (rules.get("notifications") or {}).get("channels_by_severity") or {}
    return table.get(severity, ["IN_APP", "EMAIL"])


def recipients(db, alert, institution=None):
    """Resolve who should receive an alert from its audience spec."""
    aud = alert.audience or {}
    out = []
    for role in aud.get("roles", []):
        q = db.query(User).filter(User.role == role)
        if role == "REGIONAL_OFFICER" and alert.region:
            q = q.filter(User.region == alert.region)
        for u in q.all():
            out.append({"name": u.name, "role": u.role, "email": u.email, "phone": u.phone})
    if aud.get("institution") and institution is not None:
        out.append({"name": institution.name, "role": "INSTITUTION", "email": institution.email, "phone": institution.phone})
    for m in aud.get("members", []):
        out.append({"name": m, "role": "EVC_MEMBER", "email": None, "phone": None})
    return out


def dispatch(db, alert, rules, institution=None):
    sent = 0
    for r in recipients(db, alert, institution):
        for ch in _channels(rules, alert.severity):
            n = Notification(alert_id=alert.id, channel=ch, recipient=r["name"], recipient_role=r["role"],
                             body=f"[{alert.severity}] {alert.title} - {alert.message}", status="SENT", sent_at=clock.now())
            db.add(n)
            sent += 1
            try:
                with OUTBOX.open("a", encoding="utf-8") as fh:
                    fh.write(f"{clock.now().isoformat()} {ch:<8} to={r['name']} ({r['role']}) :: {alert.title}\n")
            except OSError:
                pass
    return sent
