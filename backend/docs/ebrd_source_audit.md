# EBRD Source Audit

Task: S5.2.1 EBRD Discovery and Metadata Foundation.

## Official Public Source

The official public source for EBRD project procurement opportunities is the
EBRD Client e-Procurement Portal (ECEPP):

- Search/listing: `https://ecepp.ebrd.com/delta/noticeSearchResults.html`
- Notice detail: `https://ecepp.ebrd.com/delta/viewNotice.html?displayNoticeId=...`
- Response/access link pattern observed on public notices: `https://ecepp.ebrd.com/respond/...`

EBRD's project procurement page says procurement, prequalification,
shortlisting, and contract award notices for EBRD-financed goods, works, and
consultancy services are now only published on ECEPP.

## Listing Behavior

The public ECEPP search page renders a large server-side HTML table. The public
HTML includes visible columns for notice title, notice type, procurement
exercise title, publication date, closing date, and state. It also includes
hidden metadata cells containing sortable publication/closing timestamps and a
metadata list with project name, EBRD project ID, country, procurement exercise
name, ECEPP ID, procurement type, procurement method, buyer/client, business
sector, and notice type.

The current connector uses the public HTML table and does not call undocumented
private APIs. It treats the public table as the fallback when detail pages are
slow or missing detail fields.

No listing/search URL is persisted as the official notice URL; each normalized
tender stores a `viewNotice.html` detail URL.

## Stable Identifiers

Preferred source key: ECEPP ID from the public listing metadata or detail page.

Fallback source key: `displayNoticeId` from the public detail URL when no ECEPP
ID is available, such as some General Procurement Notice pages.

Canonical key format: `ebrd:{external_id}`.

## Detail Page Structure

Public detail pages expose a notice title, notice type, and an overview table
with fields including:

- Project Name
- EBRD Project ID
- Country
- Client Name
- ECEPP ID
- Procurement Exercise Name
- Procurement Exercise Description
- Type of Procurement
- Procurement Method
- Business Sector
- Notice Type
- Publication Date
- Closing Date

The free-text notice body may contain client address/contact lines and an
ECEPP response link.

## Mapped Fields

- `external_id`: ECEPP ID, fallback `displayNoticeId`
- `title`: notice title or procurement exercise title
- `buyer`: Client Name / buyer from listing metadata
- `project_id`: EBRD Project ID
- `project_name`: stored in source metadata
- `country`: Country, with `Kyrgyz Republic` normalized to `Kyrgyzstan`
- `region`: `Central Asia` for configured Central Asia countries
- `sector`: Business Sector
- `procurement_category`: Type of Procurement
- `procurement_method`: Procurement Method
- `notice_type`: Notice Type
- `publication_date`: Publication Date, UK-time source value stored as UTC
- `deadline`: Closing Date, UK-time source value stored as UTC
- `contact`: parsed from public client address text when present
- `official notice URL`: `viewNotice.html?...`
- `document/access URL`: public `respond/...` URL when present
- `access instructions`: ECEPP registration and expression of interest required

## Document Access Status

EBRD is metadata-only in S5.2.1:

- `access_required`: public notice has an ECEPP response/access link.
- `no_documents_found`: public notice does not expose a document/access link.
- `metadata_only`: reserved for non-downloaded public metadata; no local file is
  created for EBRD in this task.

The connector does not log in, express interest, download restricted
documents, or parse EBRD documents.

## Terms And Technical Restrictions

ECEPP `robots.txt` does not disallow the public notice pages. The ECEPP Terms
and Conditions state that exporting or extracting BiP data from the website into
other databases is prohibited. This connector is intentionally public-page,
metadata-only and records this terms note in source metadata for hardening
review before any deeper EBRD workflow.

ECEPP pages can be slow or intermittently timeout. The adapter uses public
listing metadata as fallback and fails detail enrichment without fabricating
documents.
