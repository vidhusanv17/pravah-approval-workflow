from datetime import date, datetime


def jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def row(obj, exclude=()):
    """Serialise a SQLAlchemy row to a plain dict (dates -> ISO strings)."""
    if obj is None:
        return None
    return {c.name: jsonable(getattr(obj, c.name)) for c in obj.__table__.columns if c.name not in exclude}


def days_between(a, b) -> int:
    """Whole days from a to b (b - a). Accepts date or datetime."""
    if isinstance(a, datetime):
        a = a.date()
    if isinstance(b, datetime):
        b = b.date()
    return (b - a).days
