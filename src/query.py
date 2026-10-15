"""Deterministic query cleaning for retrieval only (decision 41).

Removes phrasing that describes the *question* rather than the incident ("which law
applies to", "what section", "a person asks") and explicit dates, which only add noise
to BM25 and the embedding. The original text is still used for fact extraction and date
routing. If nothing is removed, or cleaning leaves fewer than 3 words, the original is
returned unchanged."""
import re

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december|"
           "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
# Longest / most specific patterns first.
_PATTERNS = [
    # question framing
    r"\b(a|the)\s+(person|user|someone)\s+asks?\s+(me\s+)?(about\s+)?"
    r"((which|what)\s+(law|laws|section|sections|act|acts|provision|provisions|offence|offences)\s+"
    r"(applies|apply|is applicable|are applicable|would apply|will apply|should apply|can apply)(\s+to)?)?",
    r"\b(which|what)\s+(law|laws|section|sections|act|acts|provision|provisions|offence|offences)\s+"
    r"(applies|apply|is applicable|are applicable|would apply|will apply|should apply|can apply)(\s+(to|when|if))?",
    r"\b(which|what)\s+(law|laws|section|sections|act|acts|provision|provisions)\b",
    r"\bis there (a|any) (law|section|act|provision)\b(\s+(for|about|on|against))?",
    r"\bcan (you|someone) (tell|explain|help)( me)?\b",
    r"\bhow (do|does|can|should) (i|we|the law)\b",
    # dates, with an optional leading preposition
    r"\b(on|in|during|back in|since|of|at)?\s*\d{4}-\d{2}-\d{2}\b",
    r"\b(on|in|during|at)?\s*\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
    rf"\b(on|in|during|at)?\s*\d{{1,2}}(st|nd|rd|th)?\s+(of\s+)?({_MONTHS})\.?,?\s+\d{{4}}\b",
    rf"\b(on|in|during|at)?\s*({_MONTHS})\.?,?\s+\d{{4}}\b",
    r"\b(in|during|back in|since|of|year)\s+(19|20)\d{2}\b",
    # the word "incident" as a container
    r"\b(an?|the)\s+incident\b(\s+(where|that|when|which))?",
]


def clean_query(text: str) -> str:
    t = text
    for pat in _PATTERNS:
        t = re.sub(pat, " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,.;:-?!")
    t = re.sub(r"^(where|that|when|which|to)\s+", "", t, flags=re.I)
    if t == text.strip(" ,.;:-?!") or len(re.findall(r"[A-Za-z]{3,}", t)) < 3:
        return text
    return t
