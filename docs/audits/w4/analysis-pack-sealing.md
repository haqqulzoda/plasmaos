# W4 Analysis Pack Sealing

## Authority

The passive W3 candidate is review material. The submitted selection, candidate SHA, and language are revalidated in one admission transaction. No GET creates a pack or run.

'pursuit_analysis_packs' stores organization, pursuit, requester Membership, candidate and selected-pack hashes, language, admission, page truth, both limits, disclosure, and creation time. 'pursuit_analysis_pack_items' stores copied analyzed text and its SHA plus exact private or source identities. PostgreSQL rejects update/delete.

## Admission outcomes

- Active Membership and exact organization/pursuit are mandatory.
- Private selection requires the reviewed current exact version, identical content and processing-result hashes, READY, CLEAN, and complete nonempty text.
- Source selection requires the reviewed TenderDocument and identical analyzed-text snapshot hash.
- Known pages total at most 500.
- Unknown rendered pages use at most 1,500,000 extracted characters across the selected pack and retain a truthful disclosure.
- PARTIAL input fails closed because W4 offers FULL analysis only.

The permanent tests cover explicit subset selection, private/source races, 501-page rejection, accepted and rejected unknown-page DOCX input, PARTIAL rejection, source replay after refresh, tenant boundaries, revoked Membership, and database immutability.
