"""Calendario comercial local, independiente de la UI y del almacenamiento."""
from datetime import date, timedelta

BRANCHES = ("corrientes", "resistencia")
DAY_NAMES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def week_bounds(value):
    day = as_date(value)
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def week_id(value):
    year, number, _ = week_bounds(value)[0].isocalendar()
    return f"{year}-W{number:02d}"


def week_days(value):
    monday, _ = week_bounds(value)
    return [monday + timedelta(days=n) for n in range(7)]


def calendar_weeks(today=None, before=12, after=1):
    monday, _ = week_bounds(today or date.today())
    return [monday + timedelta(weeks=n) for n in range(after, -before - 1, -1)]
