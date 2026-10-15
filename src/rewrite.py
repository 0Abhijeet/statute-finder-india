"""Query rewriting (decision 30: OFF by default; used only as an eval baseline so far).

An LLM restates the incident in formal, statute-style vocabulary ("stabs" -> "voluntarily
causes hurt by an instrument for stabbing"). It must not cite laws or section numbers.
The retrieval query becomes the cleaned original plus the rewrite, so the user's own
words are never lost. Any failure falls back to the original query."""
from src.llm_client import LLM_MODEL, create_with_retry, get_llm_client, reasoning_kwargs

PROMPT = """Rewrite the incident below as one or two plain sentences using the formal vocabulary that
criminal and regulatory statutes use (for example: voluntarily causes hurt, grievous hurt, dishonestly,
cheating, criminal intimidation, wrongful restraint, theft, snatching, without a licence, rash or negligent
act, harassment of a woman, electronic record, computer resource).
Rules: keep every fact; do not add facts; do NOT name any Act, law, section number or case; output only the sentences."""


async def rewrite_query(incident: str) -> str:
    try:
        resp = await create_with_retry(
            get_llm_client(), model=LLM_MODEL, temperature=0, max_tokens=1500, **reasoning_kwargs(),
            messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": incident}],
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else ""
    except Exception:
        return ""
