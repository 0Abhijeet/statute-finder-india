"""Fixed fact schema (decision 33) and LLM extraction.

The model extracts only what the text states; anything not stated is "unknown". The
schema has no field for legal conclusions or section numbers, and unknown keys or
invalid enum values are rejected, so the LLM cannot smuggle either in. incident_date
is NOT extracted here (see dating.py)."""
import json
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, ValidationError

from src.llm_client import LLM_MODEL, create_with_retry, get_llm_client, reasoning_kwargs


class Harm(str, Enum):
    none = "none"
    hurt = "hurt"                    # minor injury
    grievous_hurt = "grievous_hurt"  # serious / permanent injury
    death = "death"
    unknown = "unknown"


class Weapon(str, Enum):
    none = "none"
    sharp = "sharp"                  # knife, blade, axe...
    firearm = "firearm"
    other = "other"
    unknown = "unknown"


class Tri(str, Enum):
    yes = "yes"
    no = "no"
    unknown = "unknown"


class Intent(str, Enum):
    stated = "stated"
    unknown = "unknown"


class Location(str, Enum):
    home = "home"
    public_place = "public_place"
    workplace = "workplace"
    vehicle_or_road = "vehicle_or_road"
    online = "online"
    other = "other"
    unknown = "unknown"


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    harm: Harm = Harm.unknown
    weapon: Weapon = Weapon.unknown
    intent: Intent = Intent.unknown
    property_taken: Tri = Tri.unknown
    vehicle_involved: Tri = Tri.unknown
    electronic_or_online: Tri = Tri.unknown
    victim_woman_public_place: Tri = Tri.unknown
    location_type: Location = Location.unknown


SYSTEM_PROMPT = """You extract facts from a description of an incident. Output ONE JSON object and nothing else.
Rules:
- Use only what the text states. If a fact is not stated, use "unknown". Never guess.
- Do not name laws, offences or section numbers. Do not give legal conclusions.
Allowed keys and values:
harm: none (no one is described as hurt, e.g. only possession, theft, threats or messages) | hurt (the text says the injury is minor or slight) | grievous_hurt (the text says serious, severe, grievous or permanent injury) | death | unknown (an injury or violence is described but its severity is not stated, e.g. "causes an injury")
weapon: none | sharp (knife, blade, axe) | firearm | other | unknown
intent: stated (the text says the person meant to do it, e.g. "to kill", "intentionally") | unknown
property_taken: yes | no | unknown
vehicle_involved: yes | no | unknown
electronic_or_online: yes | no | unknown (yes only if the act itself is done through messages, the internet or a computer; taking or damaging a phone as an object is not online)
victim_woman_public_place: yes | no | unknown (a woman targeted in a public place)
location_type: home | public_place | workplace | vehicle_or_road | online | other | unknown"""


def _parse(raw: str) -> Facts:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    m = re.search(r"\{.*\}", raw, re.S)
    return Facts.model_validate(json.loads(m.group(0) if m else raw))


async def extract_facts(incident: str) -> tuple[Facts, dict]:
    """Returns (facts, meta). On repeated invalid output: all-unknown facts and
    meta["extraction_failed"] = True (never raises, so retrieval can still run)."""
    client = get_llm_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": incident}]
    last_err = None
    for attempt in range(2):
        try:
            resp = await create_with_retry(
                client, model=LLM_MODEL, messages=messages, temperature=0, max_tokens=1200,
                response_format={"type": "json_object"},
                # gpt-oss is a reasoning model: with a small token budget it can spend it all
                # thinking and return empty content (HTTP 400 json_validate_failed, seen live).
                **reasoning_kwargs(),
            )
            raw = resp.choices[0].message.content or ""
            return _parse(raw), {"extraction_failed": False, "attempts": attempt + 1}
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_err = f"invalid output: {str(e)[:160]}"
        except Exception as e:  # network / API errors must not break retrieval
            last_err = f"{type(e).__name__}: {str(e)[:160]}"
    return Facts(), {"extraction_failed": True, "attempts": 2, "error": last_err}
