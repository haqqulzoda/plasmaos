# Explicit developer probes

These are manually invoked diagnostics, not pytest tests or release gates. Importing
them performs no operational work. Run from the repository root with the backend
development dependencies installed. Live calls below occur only on invocation.

| Previous path | Current invocation | Effect |
| --- | --- | --- |
| `backend/test_ai.py` | `python backend/scripts/probes/ai_probe.py /path/to/input.pdf` | Reads the selected PDF and sends extracted text to the configured model; prints analysis. Optional `--env-file /path/to/development.env`. |
| `backend/test_tender_api.py` | `python backend/scripts/probes/tender_api_probe.py --base-url http://localhost:8000 --timeout 15` | Reads the first Tender from a running development API and prints its text fields. |
| `backend/test_uzbek_nlp.py` | `python backend/scripts/probes/uzbek_nlp_probe.py --base-url http://localhost:8000 --timeout 15` | Reads OpenAPI and prints analysis/Compliance schema names. |
| `backend/scripts/test_extraction.py` | `python backend/scripts/probes/extraction_probe.py` | Sends the retained synthetic procurement fixture to the configured extraction model and prints raw/validated diagnostics. Supports `--text-file`, `--taxonomy-file`, and `--model`. |

`--help` does not invoke the API or model. HTTP probe timeouts must be between zero
and 120 seconds (exclusive of zero). Use explicitly selected development targets
and suitable inputs; these commands are not part of automated collection.

The extraction probe previously imported the removed `MODEL_NAME` constant and
called a prompt builder without its taxonomy argument. Its explicit invocation
now uses the existing model chain and an explicit taxonomy list. Application
extraction behavior is unchanged. No live model probe was run during Sprint 9.2.

Import safety: `cd backend` then `python -m pytest -q test_probe_import_safety.py`.
Broad guarded collection: `python scripts/verify_s9_2_collection.py` with the
normal test dependencies and a synthetic test environment.
