# Award ledger: firm-name QA (S1-6)

Ledger: World Bank contract-award notices for Uzbekistan, Kyrgyz Republic, Tajikistan and Kazakhstan, every
procurement category, 24 months from 2024-10-11. Ingested 2026-10-11 into a disposable local database: 3,336
notices, 11,301 bidder rows.

## Rules

- **Joint-venture role markers** are removed before grouping: ", LEAD", "LEAD PARTNER/MEMBER/FIRM/CONSULTANT",
  "MEMBER", "(JV)", "JV", "IN ASSOCIATION WITH", "CONSORTIUM OF" (and a leading "CONSORTIUM"), "JOINT VENTURE (OF)".
  They are removed only in role positions: "LEADER", "PARTNERS" or "PARTNER BUILDING" inside a firm's own name are
  kept ("LEADER HORSE", "ANINVER DEVELOPMENT PARTNERS", "LEAD CONSULTING GROUP" are unchanged). The raw bidder name
  is stored and shown exactly as published; normalization applies on read, so it covers rows already stored in the
  append-only ledger.
- **Non-firm names**, two tiers (`name_flag` in `award_ledger_parser.py`):
  - *Excluded from firm counts*: MINISTRY, PIU, IMPLEMENTATION UNIT (or PROJECT IMPLEMENTATION/MANAGEMENT
    UNIT/GROUP), COMMITTEE, a body "under the Ministry/Agency/Committee/Cabinet/Government", and a bare
    "<sector word> PROJECT" (e.g. IRRIGATION PROJECT).
  - *Review, still counted*: any other name with PROJECT or AGENCY. In Uzbekistan many registered firms carry
    "PROJECT" in their brand ("SILK ROAD PROJECT" bid 49 times, "DIAMOND PROJECT", "GOLD PROJECT SERVICE"), so
    excluding every PROJECT name would drop operating firms. This tier is a deliberate deviation from "exclude all
    flagged names", left for the owner to confirm.
  - A name with a legal form (LLC, LTD, JSC, GMBH, "JOINT STOCK COMPANY", ...) is never flagged.

## OP00449976 "IRRIGATION PROJECT (Uzbekistan)"

**Source as published, not a parser error.** The notice (Agriculture Modernization Project, AMP/C1/CQS/42,
Consultant Qualification Selection, design estimates for a laboratory renovation) lists under "Rejected Firm(s)":

> **IRRIGATION PROJECT (1096666)** — Country: Uzbekistan — Reason for Rejection: Non-compliance

The bold name with its World Bank supplier id is exactly the format of every firm on the notice (the others are
OPTIMAL ARCHITECT GROUP (878063), awarded, and NIIAT (1096660), rejected), so the parser read it correctly. It may be
a registered entity with a generic name, but nothing on the notice says what it is. It is now on the excluded tier.

## Results

| | Firms (whole ledger) | Consulting firms, 24 months: UZ / KG / TJ / KZ / region |
|---|---|---|
| Before (v1 normalizer) | 3,947 | 253 / 126 / 281 / 26 / 666 |
| After (role markers + exclusions) | 3,944 | 251 / 126 / 281 / 26 / 664 |

- Excluded from firm counts: 2 names, both Uzbekistan consulting, one bid each:
  - IRRIGATION PROJECT (OP00449976, rejected);
  - CENTER FOR SCIENTIFIC AND TECHNICAL INFORMATION (CSTI) UNDER THE AGENCY OF INNOVATIVE DEVELOPMENT (a state body).
- Review tier: 41 names with PROJECT in a brand name, still counted (33 bid only in works, goods or non-consulting
  services; 8 also bid in consulting). Full list with notice ids: `private/s1/non_firm_review.csv`.
- Role markers: merge one firm across the whole ledger; none inside the consulting segment.
- Merge candidates: top 50 same-country pairs for owner review, never merged automatically, in
  `private/s1/merge_candidates.csv` (gitignored: firm lists stay private). 11 pairs share a World Bank supplier id
  under two normalized names (strongest evidence, e.g. "TOJIK ENERGIY" / "TOJIK ENERGIYA", a Turkish firm published
  once as "EPTISA MHENDSLK" with the letters dropped by the source); 39 are similar names. 24 pairs are Uzbek, 9
  Turkish, 8 Tajik.
- Recommendation from the merge list (not applied: it changes grouping): several pairs differ only by a legal form
  written out in words — "MAS'ULIYATI CHEKLANGAN JAMIYATI" (Uzbek LLC), "AKSIYADORLIK JAMIYATI" (Uzbek JSC),
  "LIMITED LIABILITY PARTNERSHIP". Adding these to the legal-form list would merge those pairs.

## Re-ingest

A second ingest of the same window (2026-10-11): 3,336 notices seen, **0 snapshots created, 3,336 unchanged, 0 rows
inserted**, no truncated passes: idempotent. Normalization is computed on read, so the name rules change counts
without rewriting stored rows.

## S1-7: legal forms written in words, Cyrillic

The normalizer also removes legal forms written out in words — Uzbek (MAS'ULIYATI CHEKLANGAN JAMIYATI/KORXONASI,
AKSIYADORLIK JAMIYATI, XUSUSIY KORXONA, OILAVIY KORXONA, QO'SHMA KORXONA), Russian (OBSHCHESTVO S OGRANICHENNOY
OTVETSTVENNOSTYU, AKTSIONERNOE OBSHCHESTVO and its open/closed/public forms, TOVARISHCHESTVO S OGRANICHENNOY
OTVETSTVENNOSTYU, CHASTNOE PREDPRIYATIE, INDIVIDUALNYY PREDPRINIMATEL) and English (LIMITED LIABILITY
COMPANY/PARTNERSHIP, JOINT STOCK COMPANY, PRIVATE ENTERPRISE) — and the abbreviations MKK, CHP, PAO. Cyrillic names are
transliterated first (Russian, Uzbek, Kazakh, Kyrgyz and Tajik letters), so the Cyrillic forms (ООО, Общество с
ограниченной ответственностью, Акционерное общество, МЧЖ...) are covered and ООО «X», X MChJ and X LLC group as one
firm. Before, Cyrillic letters were dropped by the ASCII filter. Short words that are also name parts (I, OK, AK, MAS,
VA) are deliberately not treated as legal forms.

| | Before | After |
|---|---|---|
| Firms, whole ledger (validated notices) | 3,925 | 3,915 |
| Consulting firms, 24 months, region | 663 | 663 |
| Merge candidates resolved by the normalizer (left the top 50) | | 4 (e.g. BUXORO MAXSUS SUV QURILISH ±"MAS ULIYATI CHEKLANGAN JAMIYATI", ASPMK-519 TOO / LLP) |

Re-ingest on 2026-10-12: 3,329 notices seen, 3,326 unchanged; 3 Tajikistan goods notices were re-published with
changed text and stored as version 2 (9 rows): append-only by design, not duplicates.
