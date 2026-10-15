"""Deterministic injury-severity assessment.

An injury "is described" when the text (or the LLM's facts) shows one. Its severity is
"established" only by an explicit severity cue in the text. Words such as "hurt",
"injury" or "wound" are NOT severity cues, so "stabs someone ... and causes an injury"
stays `unknown` even if the LLM guessed "hurt". This module only decides the harm fact
and whether to ask: it is never an input to section retrieval.

Known limit: regex cues cannot read negation or hypotheticals beyond the few guards
below ("not serious", threats without an outcome verb)."""
import re
from dataclasses import dataclass, field

from src.facts import Facts, Harm

_INJURY = re.compile(
    r"\b(hurt\w*|injur\w*|wound\w*|stab\w*|slash\w*|bleed\w*|beat\w*|assault\w*|attack\w*|hit|hits|hitting|"
    r"struck|strik\w*|punch\w*|kick\w*|slap\w*|smash\w*|fractur\w*|shot|shoot\w*|knock\w*|ran over|run over|"
    r"crush\w*|poison\w*|strangl\w*|chok\w*|acid|harm\w*|burn\w*|blood\w*|died|dead|killed|murder\w*)\b", re.I)
_THREAT = re.compile(r"\bthreat\w*|\bwarn\w*|\bintimidat\w*", re.I)
_OUTCOME_VERB = re.compile(
    r"\b(caused|suffered|sustained|resulted|resulting|stabbed|hit|struck|beaten|wounded|injured|shot|died|killed|"
    r"murdered|bleeding|bled)\b", re.I)

_ATTEMPT = re.compile(r"\b(tried|tries|trying|attempted|attempts|attempting)\s+to\b", re.I)
_NOT_SERIOUS = re.compile(r"\b(not|no|nothing|isn't|wasn't)\s+(a\s+)?(very\s+)?(serious|severe|grave|critical)\w*", re.I)
_MINOR = re.compile(r"\b(minor|slight\w*|superficial|bruis\w*|scratch\w*|small cut|simple hurt)\b", re.I)
_SERIOUS = re.compile(
    r"\b(grievous\w*|serious\w*|severe\w*|critical\w*|permanent\w*|disfigur\w*|fractur\w*|"
    r"broken (bone|arm|leg|jaw|rib|skull)s?|hospitali[sz]ed|icu|intensive care|life-threatening|"
    r"lost (an|his|her|their|the) (eye|limb|arm|leg)|amputat\w*|coma|paraly\w*)\b", re.I)
_DEATH = re.compile(
    r"\b(died|dies|dying|dead|killed|murdered|fatal\w*|passed away|succumbed|suicide|"
    r"(took|takes|taking|taken) (his|her|their) own life|lost (his|her|their) life|"
    r"(resulting|resulted|leading|led) (in|to) (his|her|their|the)? ?death)\b", re.I)


@dataclass
class Severity:
    harm: Harm                      # harm after the deterministic rule
    injury_described: bool
    established: bool               # an explicit severity cue was found
    source: str                     # "text_cue" | "unspecified" | "no_injury" | "attempt"
    cues: list[str] = field(default_factory=list)
    llm_harm: Harm | None = None    # what the LLM said, kept for transparency


def assess_harm(text: str, facts: Facts) -> Severity:
    t = text or ""
    # "tried to stab me": an attempt. Nothing says anyone was hurt, so do not ask "how serious
    # was the injury"; the question is whether anyone was hurt at all.
    if _ATTEMPT.search(t) and not _OUTCOME_VERB.search(t) and not _DEATH.search(t):
        return Severity(harm=Harm.unknown, injury_described=False, established=False,
                        source="attempt", llm_harm=facts.harm)
    llm_says_injury = facts.harm in (Harm.hurt, Harm.grievous_hurt, Harm.death)
    text_injury = bool(_INJURY.search(t))
    # A threat without any outcome verb is not an injury ("threatens to cause serious injury").
    if text_injury and _THREAT.search(t) and not _OUTCOME_VERB.search(t):
        text_injury = False
    described = text_injury or llm_says_injury

    if not described:
        return Severity(harm=facts.harm, injury_described=False, established=False,
                        source="no_injury", llm_harm=facts.harm)

    scrubbed = _NOT_SERIOUS.sub(" minor ", t)
    cues: list[tuple[Harm, str]] = []
    for m in _DEATH.finditer(scrubbed):
        cues.append((Harm.death, m.group(0).lower()))
    for m in _SERIOUS.finditer(scrubbed):
        cues.append((Harm.grievous_hurt, m.group(0).lower()))
    for m in _MINOR.finditer(scrubbed):
        cues.append((Harm.hurt, m.group(0).lower()))

    if not cues:
        # Do not infer severity from "hurt"/"injury": keep it unknown.
        return Severity(harm=Harm.unknown, injury_described=True, established=False,
                        source="unspecified", llm_harm=facts.harm)
    order = {Harm.hurt: 1, Harm.grievous_hurt: 2, Harm.death: 3}
    top = max((h for h, _ in cues), key=order.__getitem__)
    return Severity(harm=top, injury_described=True, established=True, source="text_cue",
                    cues=sorted({c for _, c in cues}), llm_harm=facts.harm)
