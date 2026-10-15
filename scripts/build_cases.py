"""Builds eval/cases.jsonl from the drafts below (decisions 43, 45).

Every gold/acceptable section is checked against the database: it must exist, be
in force, and its stored text must contain the stated keyword. Section choices were made
by reading the stored statute text (scripts/find_sections.py), NOT from the retriever.
All cases are written with label_status="unreviewed" and drafted_by="agent": a human
must review before they count as labels. Labels are by a non-lawyer, not reviewed by counsel.
Usage: python scripts/build_cases.py   (needs DATABASE_URL pointing at an ingested db)
"""
import asyncio
import json
import re
import sys

sys.path.insert(0, ".")
from sqlalchemy import text  # noqa: E402

from src.database import AsyncSessionLocal  # noqa: E402

B, A, M, I, T = "bns_2023", "arms_act_1959", "mv_act_1988", "it_act_2000", "tn_harassment_women_1998"


def g(act, num, kw):
    return {"act": act, "section": num, "keyword": kw}


# (id, type, incident, incident_date, gold[], acceptable[], expect{}, label_basis)
CASES = [
    # ---- single-act: BNS
    ("s01", "single", "A man on a motorbike grabs a woman's gold chain from her neck and rides away.", None,
     [g(B, "304", "snatching")], [g(B, "303", "theft"), g(B, "309", "robbery")], {},
     "BNS 304 defines theft as snatching when the offender suddenly seizes or grabs from a person."),
    ("s02", "single", "A person takes Rs 50,000 from a villager promising to double it, then disappears.", None,
     [g(B, "318", "cheats")], [], {},
     "BNS 318 punishes whoever deceives a person and thereby dishonestly induces delivery of property."),
    ("s03", "single", "A newspaper publishes a false article saying a local doctor takes bribes, damaging his reputation.", None,
     [g(B, "356", "defame")], [], {},
     "BNS 356 covers imputations published to harm a person's reputation."),
    ("s04", "single", "A man keeps following a woman on her way to work and messaging her even after she tells him to stop.", None,
     [g(B, "78", "follows a woman")], [g(B, "79", "modesty")], {},
     "BNS 78 describes a man who follows a woman and contacts her repeatedly despite a clear indication of disinterest."),
    ("s05", "single", "A man locks his employee in a room for several hours and will not let her leave.", None,
     [g(B, "127", "confine")], [g(B, "126", "obstructs")], {},
     "BNS 127 is the wrongful restraint/confinement section."),
    # ---- single-act: Arms
    ("s06", "single", "A man keeps a country-made pistol and cartridges at home and has no licence for them.", None,
     [g(A, "3", "licence")], [g(A, "25", "Whoever")], {},
     "Arms s.3 requires a licence to acquire, possess or carry a firearm or ammunition."),
    ("s07", "single", "A shopkeeper secretly sells guns and bullets to customers without any licence.", None,
     [g(A, "5", "sell")], [g(A, "25", "sells")], {},
     "Arms s.5 requires a licence to manufacture, sell or transfer arms and ammunition."),
    ("s08", "single", "A man fires a gun in the air at a wedding although he has no licence to use it.", None,
     [g(A, "3", "licence")], [g(A, "25", "Whoever"), g(A, "27", "uses")], {},
     "Arms s.3 licence requirement; s.27 punishes using arms in contravention of s.5 (acceptable)."),
    ("s09", "single", "A gun licence holder takes his weapon to a place his licence does not allow, breaking a condition of the licence.", None,
     [g(A, "30", "condition of a licence")], [], {},
     "Arms s.30 punishes contravention of any condition of a licence."),
    # ---- single-act: MV
    ("s10", "single", "A man rides a motorcycle in the city without wearing a helmet.", None,
     [g(M, "194D", "headgear")], [g(M, "129", "headgear")], {},
     "MV 194D penalises driving a motorcycle without protective headgear; 129 is the requirement."),
    ("s11", "single", "A person drives a car on the highway after drinking alcohol.", None,
     [g(M, "185", "drunken")], [], {},
     "MV 185 covers driving by a drunken person or under the influence of drugs."),
    ("s12", "single", "A teenager drives a scooter on a public road without any driving licence.", None,
     [g(M, "181", "section 3")], [g(M, "3", "driving licence")], {},
     "MV 181 punishes driving in contravention of section 3 (licence requirement)."),
    ("s13", "single", "A driver is stopped by the police and found to be driving a car with no valid insurance.", None,
     [g(M, "196", "insur")], [], {},
     "MV 196 punishes driving an uninsured vehicle."),
    # ---- single-act: IT
    ("s14", "single", "A person secretly gets into a colleague's computer and copies files without permission.", None,
     [g(I, "43", "without permission")], [g(I, "66", "dishonestly")], {},
     "IT 43 covers access/copying without permission of the owner; 66 punishes doing so dishonestly."),
    ("s15", "single", "Someone uses another person's password to log in to their account and transfer money.", None,
     [g(I, "66C", "password")], [g(I, "66", "dishonestly"), g(I, "43", "without permission")], {},
     "IT 66C punishes fraudulent use of another person's password or unique identification."),
    ("s16", "single", "A person uploads obscene videos to a website for anyone to watch.", None,
     [g(I, "67", "obscene")], [g(I, "67A", "sexually explicit")], {},
     "IT 67 punishes publishing or transmitting obscene material in electronic form."),
    ("s17", "single", "A man takes a photo of a woman's private area without her consent and posts it online.", None,
     [g(I, "66E", "private area")], [], {},
     "IT 66E punishes capturing, publishing or transmitting an image of a private area without consent."),
    # ---- single-act: TN
    ("s18", "single", "A group of boys passes obscene remarks at schoolgirls outside a school gate.", None,
     [g(T, "4", "educational institution")], [g(B, "79", "modesty")], {},
     "TN s.4 punishes harassment of women within the precincts of an educational institution."),
    ("s19", "single", "A young woman takes her own life after a man had been harassing her for months.", None,
     [g(T, "4B", "suicide")], [g(T, "4C", "presumption")], {},
     "TN s.4B is harassment suicide."),
    ("s20", "single", "A bus conductor ignores a woman's complaint that a passenger is harassing her on the bus.", None,
     [g(T, "6", "crew")], [], {},
     "TN s.6 is the duty of crew of a public service vehicle to prevent harassment."),
    ("s21", "single", "After a man is sentenced for harassing a woman in a public place, can the court make him pay her compensation?", None,
     [g(T, "7A", "compensation")], [], {},
     "TN s.7A lets the court order compensation when sentencing under s.4, 4A or 4B."),
    # ---- multi-act
    ("m01", "multi_act", "A fraudster sends a fake bank link by SMS, the victim enters card details, and Rs 80,000 is withdrawn from the account.", None,
     [g(B, "318", "cheats"), g(I, "66D", "personation")], [g(I, "66", "dishonestly"), g(I, "66C", "password"), g(B, "319", "personation")], {},
     "Cheating (BNS 318) carried out by a computer resource posing as the bank (IT 66D)."),
    ("m02", "multi_act", "A man keeps monitoring a woman's emails and social media and sends her obscene messages.", None,
     [g(B, "78", "electronic"), g(I, "67", "obscene")], [g(B, "79", "modesty"), g(I, "66E", "private area")], {},
     "BNS 78 stalking includes monitoring internet or email use; IT 67 obscene electronic material."),
    ("m03", "multi_act", "A drunk driver hits a pedestrian and the pedestrian dies.", None,
     [g(M, "185", "drunken"), g(B, "106", "rash or negligent")], [g(B, "105", "culpable homicide")], {},
     "MV 185 drunken driving and BNS 106(1) death by rash or negligent act. NOTE: BNS 106(2) is flagged not in force."),
    ("m04", "multi_act", "A man shoots his neighbour in the arm with a pistol he has no licence for.", None,
     [g(B, "118", "shooting"), g(A, "25", "Whoever")], [g(A, "3", "licence"), g(A, "27", "uses"), g(B, "117", "grievous hurt")],
     {"asks": ["harm"]},
     "BNS 118 hurt by an instrument for shooting; Arms s.25 punishes unlicensed possession offences. "
     "Expectation changed after the first eval run: a shot wound with no stated severity is what the severity rule asks about."),
    ("m05", "multi_act", "A man touches a woman and makes sexual remarks to her on a crowded public bus.", None,
     [g(T, "4", "bus"), g(B, "75", "sexual")], [g(B, "79", "modesty"), g(T, "6", "crew")], {},
     "TN s.4 harassment in a public service vehicle; BNS 75 sexual harassment (unwelcome physical contact, sexual remarks)."),
    # ---- negative (no section should be offered)
    ("n01", "negative", "How much income tax do I owe on my salary and by when must I file the return?", None, [], [],
     {"abstain": True}, "Income tax is out of scope (decision 15)."),
    ("n02", "negative", "My neighbour built a second floor on his house without a municipal building permit.", None, [], [],
     {"abstain": True}, "Planning permission is not governed by the five acts."),
    ("n03", "negative", "My landlord is refusing to return my security deposit after I vacated the flat.", None, [], [],
     {"abstain": True}, "Civil rent dispute."),
    ("n04", "negative", "I want a divorce and custody of my two children.", None, [], [],
     {"abstain": True}, "Family law."),
    ("n05", "negative", "My employer has not paid my salary for three months.", None, [], [],
     {"abstain": True}, "Employment/labour."),
    ("n06", "negative", "A shop sold me a defective refrigerator and refuses to give a refund.", None, [], [],
     {"abstain": True}, "Consumer dispute."),
    ("n07", "negative", "How do I register a private limited company?", None, [], [],
     {"abstain": True}, "Company law."),
    ("n08", "negative", "What is the best recipe for chicken biryani?", None, [], [],
     {"abstain": True}, "Not a legal question."),
    # ---- temporal
    ("t01", "temporal", "In March 2022 a man stole a mobile phone from a shop counter.", None,
     [g(B, "303", "theft")], [], {"regime": "ipc", "ipc_refs": ["378", "379"]},
     "Before 1 Jul 2024: IPC applied; BNS 303 shown as equivalent; mapping rows 303(1)->378, 303(2)->379."),
    ("t02", "temporal", "A man deliberately hit his brother with a stick, causing a small cut.", "2023-08-15",
     [g(B, "115", "hurt")], [g(B, "118", "instrument")], {"regime": "ipc", "ipc_refs": ["321", "323"]},
     "Before 1 Jul 2024 via the request field; mapping 115(1)->321, 115(2)->323."),
    ("t03", "temporal", "On 30 June 2024 a man cheated a trader out of Rs 20,000 by giving a fake cheque.", None,
     [g(B, "318", "cheats")], [], {"regime": "ipc", "ipc_refs": ["415", "417", "420"]},
     "Last day of the IPC regime; mapping 318(1)->415, 318(2)->417, 318(4)->420."),
    ("t04", "temporal", "On 1 July 2024 a man cheated a trader out of Rs 20,000 by giving a fake cheque.", None,
     [g(B, "318", "cheats")], [], {"regime": "bns"},
     "First day of the BNS regime; no IPC equivalents expected."),
    # ---- underspecified (a decisive fact is missing: expect a question, sections still shown)
    ("u01", "underspecified", "A man attacked another man with a knife near the market.", None,
     [g(B, "118", "instrument")], [g(B, "115", "hurt"), g(B, "117", "grievous hurt"), g(B, "101", "murder")],
     {"asks": ["harm"]}, "Injury severity not stated: the answer depends on it (hurt / grievous / death)."),
    ("u02", "underspecified", "A driver hit a cyclist with his car.", None,
     [g(M, "134", "accident")], [g(B, "281", "rash"), g(M, "184", "dangerous")],
     {"asks": ["harm"]}, "Whether the cyclist was injured or died is not stated."),
    ("u03", "underspecified", "In 2024 a man was stabbed in a fight.", None,
     [g(B, "118", "instrument")], [g(B, "115", "hurt"), g(B, "117", "grievous hurt"), g(B, "101", "murder")],
     {"asks": ["harm", "incident_date"], "regime": "ambiguous"},
     "Severity unknown and a bare year 2024 straddles the 1 Jul 2024 cut-over."),
]


async def main() -> None:
    problems = []
    out = []
    async with AsyncSessionLocal() as db:
        async def check(ref):
            anchor = f"{ref['act']}:s{ref['section']}"
            r = (await db.execute(text("select status, text from sections where anchor = :a"), {"a": anchor})).first()
            if r is None:
                problems.append(f"{anchor}: not in database")
                return None
            body = re.sub(r"\s+", " ", r.text)
            if r.status != "in_force":
                problems.append(f"{anchor}: status {r.status}")
            if ref["keyword"].lower() not in body.lower():
                problems.append(f"{anchor}: keyword {ref['keyword']!r} not in text")
            return {"anchor": anchor, "evidence": body[:200]}

        for cid, typ, inc, date, gold, acc, expect, basis in CASES:
            gold_v = [await check(x) for x in gold]
            acc_v = [await check(x) for x in acc]
            out.append({
                "id": cid, "type": typ, "incident": inc, "incident_date": date,
                "gold": [v["anchor"] for v in gold_v if v], "acceptable": [v["anchor"] for v in acc_v if v],
                "expect": expect, "label_basis": basis,
                "evidence": {v["anchor"]: v["evidence"] for v in gold_v + acc_v if v},
                "label_status": "unreviewed", "drafted_by": "agent",
                "labelled_by": "non-lawyer draft; not reviewed by counsel",
            })
    if problems:
        print("PROBLEMS:"); [print("  ", p) for p in problems]
        sys.exit(1)
    with open("eval/cases.jsonl", "w", encoding="utf-8") as f:
        for c in out:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    from collections import Counter
    print("wrote", len(out), "cases", dict(Counter(c["type"] for c in out)))


asyncio.run(main())
