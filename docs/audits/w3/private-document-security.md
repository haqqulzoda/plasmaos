# W3 Private Document Security Audit

## Boundary

Private bytes live under `PRIVATE_DOCUMENT_STORAGE_ROOT`, outside the frontend and backend public roots. Storage keys contain generated UUID components and a `.bin` object name. The storage resolver rejects absolute paths, dot segments, traversal and every path that resolves outside the configured root. User filenames are retained only as bounded metadata and safe download names.

## Intake controls

| Control | Enforcement |
|---|---|
| Formats | Exact `.pdf` or `.docx` allowlist |
| Declared MIME | Must exactly match the extension |
| Signature | `%PDF-` for PDF; ZIP plus required OpenXML entries for DOCX |
| Active content | HTML/script polyglots, DOCM, VBA, ActiveX, embeddings and executable entries rejected |
| Encryption | Encrypted PDF rejected with password-removal guidance |
| Size | 25 MiB per file; 150 MiB per pack and bounded HTTP request |
| DOCX bombs | Entry count, path, per-entry size, total expansion and compression-ratio bounds |
| Malware | ClamAV `INSTREAM`; unavailable, invalid response, or timeout fails closed |
| Parsing | Starts only after a clean scan; isolated subprocess with CPU, memory, file-size and wall-time bounds |
| External retrieval | No link fetching and no network AI in the parser |

Downloads and previews re-resolve active organization membership and the pursuit, document and version relationship. Only a version with a clean malware result can be streamed. Responses use private no-store caching and `nosniff`; storage paths, storage keys and extracted private text are absent from API schemas.

The disposable security suite covers valid PDF, blank/scanned PDF, DOCX, MIME mismatch, encrypted PDF, unsupported DOCM, HTML/polyglot input, oversized file/pack, DOCX compression bomb, parser failure and scanner unavailability.

## External-pilot gate

The security gate fails closed if the scanner is absent. Compose provides a dedicated ClamAV service and the private-document worker depends on it. A release configuration must provide a nonempty scanner host and valid port. Operational readiness still requires current signature availability and scanner health monitoring in the deployment environment.

