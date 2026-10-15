"""When to ask (decision 34, hybrid): sections are always shown grouped by condition; up
to two questions are added for decisive facts that are unknown. Deterministic rules.

Severity (user-requested rule): ask ONE targeted question when an injury is described or
strongly implied but no explicit severity cue exists (src/severity.py). The heuristic
only decides what to ask; it never changes which sections are retrieved."""
import re

from src.facts import Facts, Harm, Tri, Weapon
from src.severity import Severity, assess_harm

MAX_QUESTIONS = 2
_SUICIDE = re.compile(r"suicide|(takes?|took|taking) (his|her|their) own life", re.I)


def clarifying_questions(facts: Facts, date_info: dict, incident_text: str = "",
                         severity: Severity | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (questions, open_conditions). open_conditions name the fact and the values
    that Phase 5 groups the sections by."""
    sev = severity or assess_harm(incident_text, facts)
    harm = sev.harm
    qs, conds = [], []
    if sev.source == "attempt":
        qs.append({"fact": "harm", "question": "Was anyone actually hurt, or was it only an attempt? If someone "
                   "was hurt, how seriously: minor, serious or permanent (grievous), or did the person die?"})
        conds.append({"fact": "harm", "values": ["no_injury", "hurt", "grievous_hurt", "death"]})
    elif sev.injury_described and not sev.established:
        qs.append({"fact": "harm", "question": "How serious was the injury: minor, serious or permanent "
                   "(grievous), or did the person die?"})
        conds.append({"fact": "harm", "values": ["hurt", "grievous_hurt", "death"]})
    # A weapon question is meaningless for a vehicle collision or a suicide (found in the eval).
    weapon_relevant = facts.vehicle_involved != Tri.yes and not _SUICIDE.search(incident_text or "")
    if harm in (Harm.hurt, Harm.grievous_hurt, Harm.death) and facts.weapon == Weapon.unknown and weapon_relevant:
        qs.append({"fact": "weapon", "question": "Was a weapon or object used: a sharp object such as a knife, "
                   "a firearm, something else, or none?"})
        conds.append({"fact": "weapon", "values": ["sharp", "firearm", "other", "none"]})
    if date_info.get("regime") == "ambiguous":
        qs.append({"fact": "incident_date", "question": "On what date in 2024 did this happen? The BNS applies "
                   "from 1 July 2024; before that the IPC applied."})
        conds.append({"fact": "incident_date", "values": ["before 1 July 2024", "on or after 1 July 2024"]})
    return qs[:MAX_QUESTIONS], conds[:MAX_QUESTIONS]
