# W3 Document Processing Audit

## Durability

The upload transaction creates `PrivateDocument`, immutable `DocumentVersion`, `PrivateDocumentBatch`, and `DocumentProcessingJob` rows before broker publication. Broker acceptance is therefore an optimization, not the durability boundary. Failed publication leaves committed `QUEUED` work discoverable.

Celery Beat runs `dispatch_private_documents` every ten seconds. It leases up to 25 queued jobs or checking/extracting jobs whose three-minute lease expired, increments a dispatch-attempt counter, and republishes to the dedicated `private_documents` queue. Source connectors and heavy source downloads use other queues.

## State transitions

`QUEUED (internal) -> CHECKING -> EXTRACTING -> READY | PARTIAL | FAILED`

The customer maps internal queued work to `CHECKING`. Batch state contains exact `processed_count`, `file_count`, and `failed_count`; there is no synthetic percentage or ETA.

The worker claims a live lease before scanning. A concurrent delivery observes the lease and exits. Terminal redelivery returns the stored state without work. After a clean scan, a parser failure keeps the clean scan result; retry resets the same job to queued and does not rescan or create another version. Missing bytes, malware, scanner failure, parser failure, OCR failure, and unknown DOCX page count use explicit codes and states.

## Result separation

Content identity facts never carry mutable processing fields. Malware status, extracted text, extraction hash, page count, parser identity and errors live in `private_document_processing_results`. PostgreSQL prevents immutable version updates and deletes.

One durable notification is staged per terminal batch outcome. Payloads contain IDs and counts only. Filenames, text, evidence, CV data and storage details are excluded.

