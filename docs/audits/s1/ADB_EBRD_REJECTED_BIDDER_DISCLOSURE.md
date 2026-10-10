# ADB and EBRD: what they publish about losing and rejected bidders

Sprint 1, award ledger v0. Status: research only, no ingestion. Checked 2026-10-10.

## Summary

| | World Bank (in the ledger) | ADB | EBRD |
|---|---|---|---|
| Winner name, country/address, contract price | Yes, per notice | Yes ("Contracts Awarded" pages) | Yes (award notices on ECEPP; periodic Bank list) |
| Names of all firms that bid / were evaluated | Yes (Evaluated sections) | Not published (consulting); only the shortlist | Not in the published minimum |
| Evaluated prices of losing bids | Yes | No | No (tender opening read-outs go to attendees) |
| Rejected firms and the reason | Yes, verbatim | No (reasons only in a private debriefing) | No (reasons only in a private debriefing) |
| Technical scores | Yes for consulting (awarded firm) | Communicated to participating firms through CMS, not a public list | No |
| Machine-readable feed | Procurement API (JSON) | RSS feeds (title, project, country, sector, status only) | ECEPP portal; award notices removed after 12 months |

For a rejected-bidder ledger the World Bank is the only one of the three whose public notices
carry it. ADB and EBRD can add winners and contract values (useful for market size and the
firm list) but not losing or rejected bidders.

## ADB

- Contracts awarded. ADB's executing-agency guidance lists the content of a typical
  "Contracts Awarded" page for consulting: package name, project number, loan number,
  executing agency, consultant's name, consultant's address, contract amount, amount financed
  by ADB (*Frequently Asked Questions on Consulting Services*, Q99). No other proposals,
  prices or reasons.
- For ADB's own consulting selections ADB posts "contracts awarded for consulting services with
  contract value above US$0.1 million" and a "List of Shortlisted Firms" per project.
- "Total scores obtained at technical evaluation shall be made public." In practice this is a
  notification through the Consultant Management System to the firms that submitted
  proposals; debriefing "will not provide information on competitors' proposals".
- The contracts-awarded RSS feed (already read by the competitor lookup) carries only the
  package title, project number, country, sector and status; item pages answered 404 to an
  unauthenticated script in this check.

Possible ingestion later: winners and contract amounts from the Contracts Awarded pages, plus
shortlists (firms that expressed interest and were shortlisted, i.e. participation without a
proposal outcome). Would need an HTML scraper; no rejected-bidder data.

## EBRD

- Procurement Policies and Rules 2022, §3.75: "The Bank will publish on a periodical basis
  information on all awarded contracts, including, as a minimum, the contract title and price,
  the name and nationality of the supplier, contractor or consultant, to whom the contract was
  awarded."
- Client award notices are published only on ECEPP; EBRD's "Contract awards notification" page
  says details "will be removed from this page after 12 months of Publication". The tender
  document's "Notification of Awards" clause (ITT 35) governs their content for goods and
  works; losing tenderers are told the grounds only on request ("debriefing").
- Our EBRD connector already sees "Contract Award Notice" rows on ECEPP and skips them. Next
  step before any ingestion: sample 20 of them for Central Asia and record which fields are
  actually filled (winner only, or all tenderers with read-out prices). Because notices expire
  after 12 months, a 24-month window can never be complete from ECEPP alone.

## Sources

- ADB, How will my company know the status of our consulting proposal? https://www.adb.org/business/how-to/status-consulting-proposal
- ADB, Consulting (operational procurement): https://www.adb.org/business/operational-procurement/consulting
- ADB, Frequently Asked Questions on Consulting Services (Q99): https://www.adb.org/sites/default/files/faqs-consulting-services.pdf
- ADB contracts-awarded RSS: http://feeds.feedburner.com/adb-contracts-awarded
- EBRD, Procurement Policies and Rules 2022 (§3.75): https://www.ebrd.com/content/dam/ebrd_dxp/assets/pdfs/project-procurement/procurement-policies-and-rules/ppr-2022/PPR-2022-English.pdf
- EBRD, Contract awards notification: https://ebrd.com/home/work-with-us/project-procurement/contract-awards-notification.html
