# W1 evidence-language audit

The product currently stores company profile, certification, license, financial and readiness **claims**. A readiness row may have only metadata; `optional_file_url` is a reference, not a managed verified file version. The current Vault does not attest document authenticity. Compliance verdict logic was not changed by W1.

| Surface | Finding | W1 action |
|---|---|---|
| Strategic drafting prompt and fallback | “Verified credentials” could be generated from unverified company context | Prompt requires recorded information and forbids describing credentials/readiness as verified proof; fallback uses “recorded experience.” |
| Historical Proposal summary | Old root-level generated text can contain outdated verification claims | The editor marks it as historical and warns before reuse. New exports read only the new price-free draft summary; saving unrelated fields does not carry old text forward. |
| Legacy upload-TZ summary | Asserted that a recommendation was backed by verified credentials | Replaced with a request to review recorded company information and delivery assumptions. |
| Compliance English, Uzbek, Russian, Arabic workspace | Readiness support label and evidence heading implied verified proof; matched/critical/obligation descriptions used confirmation or verification language | Changed to linked readiness **records** and assessment language. Historical verdict categories and matching algorithm remain identical. |
| Readiness help | Existing copy states that adding a file reference does not verify the file | Retained in all active catalogs. |
| Compliance source excerpts | “Source evidence” refers to the source Tender quote/document, not company readiness proof | Retained; W1 does not relabel quoted source material as company verification. |
| Backend source extractor | “Verified evidence” refers to source-supported tender requirements | Retained because it describes source traceability, not certification of customer claims. |
| AnalysisVersion integrity DTO | `VERIFIED` denotes matching stored output/evidence/document hashes | Retained because it is an integrity check, not proof of customer credentials. |

Remaining limitation: an existing Compliance `matched` verdict is an algorithmic assessment based on recorded company information. It is not external credential verification. W2/W4 need versioned evidence and explicit assertion/review states before the product can claim proof verification.
