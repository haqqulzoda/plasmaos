# W6 Confirmation Provenance

Every fact uses one explicit category: `DIRECT_EMAIL`, `CALL`, `MEETING`, `SIGNED_DOCUMENT`, `OPERATOR_RECORDED`, `CUSTOMER_RECORDED`, or `OTHER`. UI copy says the fact was recorded from that source and shows the observed date. It does not label user entered data independently verified.

A supporting W3 DocumentVersion is optional. The write service joins it to its PrivateDocument and accepts it only when both Organization and Pursuit match the participation trail. Responses expose only the version ID. W6 adds no email ingestion, message delivery, or document ingestion channel.

`CONFIRMED` requires an unexpired available or partially available fact. Partial availability requires explicit confirmation conditions. Confirmation remains operational evidence and does not claim a contract or final team compliance.
