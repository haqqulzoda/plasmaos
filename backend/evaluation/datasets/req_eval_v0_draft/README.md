# req_eval_v0_draft: labelled tender requirements (EN / RU / UZ)

**Status: DRAFT — pending review by a procurement expert.** Do not present scores against
this set as validated accuracy. The manifest records the status as
`DRAFT_PENDING_PROCUREMENT_EXPERT_REVIEW`; change it only after the review below.

## What is in it

35 public tender notices, retrieved on 2026-11-03, with hand labels of the requirements a
bidder must meet or act on.

| Language | Documents | Source | Countries | Required items | Optional items | Required items by script |
| --- | ---: | --- | --- | ---: | ---: | --- |
| English | 12 | World Bank procurement notices | UZ 5, TJ 4, KG 3 | 125 | 19 | Latin 125 |
| Russian | 12 | World Bank procurement notices | TJ 7, KG 2, BY 1, KZ 1, UZ 1 | 133 | 16 | Cyrillic 130, mixed 3 |
| Uzbek | 11 | UzEx e-tender lots | UZ 11 | 207 | 2 | Latin 84, Cyrillic 123 |

Procurement types: consulting (firm and individual), goods, works and services. Per-document
metadata is in `manifest.json`: source id, public URL, API URL, country, notice type,
procurement type, dominant script, SHA-256 of the stored text, and the names redacted.

* `sources/<doc_id>.txt`: the exact text the labels refer to, and the input live mode
  sends to the pipeline.
  * World Bank: the notice's `notice_text` HTML converted to text.
  * UzEx: the lot title, additional description, lot-specific fields and qualification
    fields. Contact persons, customer address and the uploaded tender documents are not
    included.
* `labels/<doc_id>.json`: one entry per requirement: `quote` (verbatim from the source),
  optional `alt_quotes`, `type`, `obligation`, optional `optional` and `note`.

Rebuild or check the texts with `python scripts/eval_requirement_extraction.py build-sources`
(see `../../README.md`). The builder lives in `../../requirements_eval/sources.py`.

## Personal data

E-mail addresses and phone numbers are replaced with `[REDACTED]` by the builder. Named
contact persons and one embedded account identifier were also replaced when the set was
built. The names are not stored in the repository: the manifest records only
`named_redactions` per document. `build-sources` compares a fresh rebuild with the stored
text by treating each `[REDACTED]` as a short wildcard, so it needs no names. Organisation
names (procuring entities, projects) are kept: they are part of the public notice.

## How it was labelled

Each text was read in full and labelled by hand, in the original language. The labeller
was Claude, an AI assistant, working in a repository session. No extraction pipeline or
model output was used to propose, filter or check labels. Labels have not been
cross-checked by a second person.

Guide:

* **Label** every statement that asks something of the bidder or consultant, or decides
  their eligibility or ranking: eligibility and legal status, qualifications and experience
  (firm or individual), staff, financial capacity and securities, documents to submit,
  submission rules (deadline, place, method, format, language), and the selection or
  evaluation method.
* **Do not label** project background or the description of the work to be done (terms of
  reference tasks), contact details, or how to obtain the documents. Exception: borderline
  statements are labelled `optional: true`. These include document-availability notes,
  envelope marking, beneficial-ownership disclosure after award, and contract duration or
  duty station. A pipeline is neither rewarded nor penalised for them.
* **Quote** the shortest verbatim span that states the requirement completely, usually one
  list item or sentence. If the same requirement is stated twice (repeated field, or the
  same rule in Uzbek Latin and Cyrillic), the second statement is an `alt_quote`.
* **type**: ELIGIBILITY, QUALIFICATION, FINANCIAL, TECHNICAL, DOCUMENT, SUBMISSION,
  EVALUATION.
* **obligation**:
  * MANDATORY: must be met; failing it rejects or excludes.
  * SCORED: a shortlisting or evaluation criterion that earns points or rank.
  * PREFERRED: "an advantage", "preferably", "desirable".
  * INFORMATIONAL: states a rule or method but asks nothing.
* **UzEx standard sentences.** UzEx lots repeat a standard list of qualification fields
  (sixteen distinct sentences, e.g. "Шартнома тузиш учун қонуний ҳуқуққа эгалик."). They
  were labelled once, in `uzex_standard_sentences.json`. They are applied to every lot
  that contains the identical sentence, unless the lot's own labels already use it as a
  quote. These items carry a note saying so.

## Known limits (read before drawing conclusions)

* **Language is confounded with source and format.** English and Russian come only from
  World Bank notices (prose); Uzbek comes only from UzEx lots (form fields, standard
  sentences). A language gap measured on this set may be a source or format gap.
  `procurement_type` and item-level `script` give partial separation, not a fix.
* **Uzbek script is confounded with template.** Most Uzbek Cyrillic items are the UzEx
  standard sentences, and most Uzbek Latin items are lot-specific fields.
* **Uzbek required items are 44% of the set** (207 of 465), because UzEx lots list many
  fields. Report per-language results, not only pooled ones.
* **No scanned documents.** All 35 texts are digital. The scanned-versus-digital check
  (`docs/M3_EVAL_READINESS.md`) cannot be measured on this set.
* **No contract values.** `value_band` is `unknown` for every document.
* **Short notices only.** Stored texts are 1.6k to 7.4k characters. Long tender documents
  (60–120 pages), where the pipeline routes differently, are not covered.
* **One labeller, AI, unreviewed.** See above.
* **World Bank language tags are unreliable.** All 12 Russian notices are tagged
  `notice_lang_name: English` by the World Bank API (`api_language_tag` in the manifest).
  Language was assigned by reading the text.
* **Age.** Russian notices date from 2019 to 2026; English notices and Uzbek lots were open in 2026.

## Rights

The texts are public procurement notices published for wide distribution. Their reuse
terms (World Bank site terms; UzEx platform terms) have not been confirmed. Confirming
them, or replacing the stored texts with fetch-on-demand, is an open decision recorded in
`docs/M3_EVAL_READINESS.md`.

## Expert review checklist

A procurement expert reading Russian and Uzbek should, for each document:

1. Confirm nothing that a bidder must do or meet is missing, especially in the UzEx form
   fields.
2. Check each `obligation`, especially items with a `note` (ambiguous UzEx field layout in
   `uz-uzex-519973`), scored versus mandatory shortlisting criteria, and the UzEx standard
   sentences.
3. Check `optional` decisions.
4. Record their name, date and decisions in this README. Then set `status` in
   `manifest.json` and in each label file.
