"""Deterministic date routing (decision 35). The LLM never decides the regime.

Source of the rule: BNS s.358 (official MHA text in the corpus): the IPC is repealed
but its previous operation and "any penalty ... incurred in respect of any offences
committed against the Code" are saved. Commencement 1 July 2024: PIB; BNS s.1(2)
says the date is set by notification. The notification itself (S.O. 850(E)) has not
been checked against the Gazette."""
import calendar
import re
from datetime import date, timedelta

CUTOVER = date(2024, 7, 1)

LIMITS = [
    "An offence that begins before and continues after 1 July 2024 is routed by the date given; the "
    "transitional position for continuing offences is not analysed.",
    "Procedure (BNSS vs CrPC, investigation, trial) is not covered.",
    "Acts other than the BNS are shown in their current consolidated text; earlier versions as on the "
    "incident date are not available.",
    "The IPC text is not in this corpus: for incidents before 1 July 2024 the IPC section numbers come from "
    "a comparison table (not an official MHA publication) and the BNS text is shown as the equivalent "
    "current provision.",
]

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_NUM = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_DMY_TXT = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?,?\s+(\d{{4}})\b", re.I)
_MDY_TXT = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_MY = re.compile(rf"\b({_MON})\.?,?\s+(\d{{4}})\b", re.I)
_YEAR = re.compile(r"\b(?:in|during|back in|since|of|year)\s+((?:19|20)\d{2})\b", re.I)


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _from_text(text: str, today: date):
    m = _ISO.search(text)
    if m and (d := _mk(int(m[1]), int(m[2]), int(m[3]))):
        return d, "exact", m.group(0)
    m = _DMY_NUM.search(text)
    if m and (d := _mk(int(m[3]), int(m[2]), int(m[1]))):
        return d, "exact", m.group(0)
    m = _DMY_TXT.search(text)
    if m and (d := _mk(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))):
        return d, "exact", m.group(0)
    m = _MDY_TXT.search(text)
    if m and (d := _mk(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))):
        return d, "exact", m.group(0)
    m = _MY.search(text)
    if m:
        return date(int(m[2]), _MONTHS[m[1].lower()], 1), "month", m.group(0)
    low = text.lower()
    if re.search(r"\byesterday\b", low):
        return today - timedelta(days=1), "exact", "yesterday"
    if re.search(r"\blast year\b", low):
        return date(today.year - 1, 1, 1), "year", "last year"
    m = _YEAR.search(text)
    if m and 1950 <= int(m[1]) <= today.year:
        return date(int(m[1]), 1, 1), "year", m.group(0)
    return None, None, None


def resolve_date(text: str, incident_date: str | None = None, today: date | None = None) -> dict:
    """regime: "ipc" | "bns" | "ambiguous" (year 2024 alone: both branches shown)."""
    today = today or date.today()
    d = precision = matched = None
    source = "default"
    if incident_date:
        try:
            d, precision, source = date.fromisoformat(incident_date), "exact", "request_field"
        except ValueError:
            return {"date": today.isoformat(), "precision": "default_today", "source": "invalid",
                    "regime": "bns", "assumed_today": True,
                    "note": f"incident_date {incident_date!r} is not an ISO date; today's date is assumed."}
    if d is None:
        d, precision, matched = _from_text(text, today)
        if d is not None:
            source = "text"
    if d is None:
        return {"date": today.isoformat(), "precision": "default_today", "source": "default",
                "regime": "bns", "assumed_today": True,
                "note": "No incident date given: today's date is assumed, so the BNS applies. "
                        "State the date if the incident was before 1 July 2024."}
    if precision == "exact":
        regime = "ipc" if d < CUTOVER else "bns"
    elif precision == "month":
        regime = "ipc" if (d.year, d.month) < (2024, 7) else "bns"
    else:  # year only
        regime = "ipc" if d.year < 2024 else ("bns" if d.year > 2024 else "ambiguous")
    label = {"ipc": "before 1 July 2024: the IPC applied",
             "bns": "on or after 1 July 2024: the BNS applies",
             "ambiguous": "the year 2024 alone does not say which side of 1 July 2024 it falls on: both branches shown"}[regime]
    return {"date": d.isoformat(), "precision": precision, "source": source, "matched_text": matched,
            "regime": regime, "assumed_today": False, "note": f"Incident date {d.isoformat()} ({precision}): {label}."}
