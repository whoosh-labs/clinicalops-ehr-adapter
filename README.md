# clinicalops-ehr-adapter

Turns a raw EHR export (schedule PDF, face sheet, spreadsheet) into the canonical CSV that the VOB import in
`clinicalops-internal-api` expects. It is the service form of PDFTOCSV ("Clinical DataOps Hub"), whose
per-EHR rules it keeps.

```
admin UI ─► S3 ─► gateway /v1/vob/records/import
                    gateway reads tenant pref VOB_ACTION.ehrSource
                    └─► clinicalops-ehr-adapter POST /v1/normalize/{source} ─► canonical CSV
                          └─► internal-api /vob/records/import/csv (existing import, then STDI)
```

Only the gateway calls this service (ClusterIP, no ingress). It is stateless: uploads are parsed in memory,
nothing is stored, and logs carry the source name and row counts only.

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness / readiness |
| `GET /v1/sources` | supported sources: `athena`, `epic`, `meditab`, `modmed`, `modulemd` |
| `POST /v1/normalize/{source}` | multipart `file`, optional `options` (JSON object) |

Response `200`:

```json
{
  "source": "modmed",
  "csv": "Patient Name,DOB,Appt. Provider,Service Date,Insurance,Policy No.\n...",
  "rowCount": 5,
  "dropped": [{ "source": "page 3", "patientName": "BELL TATE, NORA K", "reason": "no insurance on file" }],
  "stats": { "sourceUnits": 5, "rows": 5, "dropped": 4 },
  "warnings": []
}
```

- The CSV uses internal-api's canonical headers: `Patient Name, DOB, Appt. Provider, Service Date, Insurance,
  Policy No.`, plus `Appointment Type, Clinic, Email, Phone` where the source has them.
- Dates are `MM/DD/YYYY`. Policy numbers are kept as text, so leading zeros are preserved.
- A row missing a required field (Patient Name, DOB, Service Date, Insurance, Policy No.) goes to `dropped`,
  not into the CSV.
- Errors:
  - `404`: unknown source.
  - `413`: the file is over `EHR_ADAPTER_MAX_FILE_MB` (default 25).
  - `422`: the file doesn't match the source, or the options are invalid. `detail` says why.
  - `500`: unexpected error. The message is generic and no details are logged.

### Sources

| Source | Files | What it does |
|---|---|---|
| `athena` | `.pdf` | AthenaOne schedule. Service date from the header, provider from department headers (Complete Allergy aliases built in), free slots skipped, wrapped `INS:` lines joined |
| `modmed` | `.pdf`, `.csv` | Face sheet PDF: one page per appointment, `FIRST MIDDLE LAST` → `LAST, FIRST MIDDLE` (titles, suffixes, middle initial, particles), one row per insurance block. PatientDemoGraphicData CSV: the name is built from 3 columns. Copay/support programs, self-pay and placeholder policies are dropped |
| `meditab` | `.csv`, `.txt` | IMS Meditab export: cp1252 fallback, one-line exports rebuilt, primary + secondary insurance as two rows |
| `modulemd` | `.xls` (HTML), `.xlsx`, `.csv` | ModuleMD schedule: header row found under report titles, `Payer[policy]**Payer2[policy2]` split, time removed from the schedule date |
| `epic` | `.csv`, `.xlsx`, `.xls` | EPIC / AAMG: JMPN Anthem IDs 14 → 12 chars, Healthy Employee Plan IDs 11 → 9, day-first files auto-detected. Options: `dateFormat` (`auto`, `mm/dd/yyyy`, `dd/mm/yyyy`), `strictJmpnAnthem` (default `true`), `anthemAliases`, `healthyEmployeeAliases` |

`ecw` (two files: appointments + eligibility) is not exposed yet.

## Layout

| Path | Contents |
|---|---|
| `ehr_adapter/pipelines/` | per-EHR processing, moved unchanged from PDFTOCSV's `app.py` |
| `ehr_adapter/normalize.py` | runs a pipeline and maps its output to the canonical CSV |
| `ehr_adapter/api.py` | FastAPI app |
| `ehr_adapter/exports.py` | ZIP/part-file helpers for the Streamlit UI and the CLI (not used by the API) |
| `app.py` | the Streamlit UI (kept until every tenant is cut over) |
| `facesheet_to_csv.py` | ModMed face sheet CLI |
| `tests/` | pytest suite; `tests/fixtures.py` builds synthetic exports in code |

## Development

Requires [uv](https://docs.astral.sh/uv/) and, for face-sheet PDFs, `pdftotext` (`brew install poppler` /
`apt-get install poppler-utils`). Without it, PDFs are read with pdfplumber, whose column positions can differ.

```bash
uv sync --all-groups --extra ui                     # dependencies, plus Streamlit for app.py
uv run pytest                                       # tests
uv run ruff check .                                 # lint
uv run uvicorn ehr_adapter.api:app --reload         # API on http://localhost:8000
uv run --extra ui streamlit run app.py              # Streamlit UI
uv run python facesheet_to_csv.py in.pdf out/prefix # face sheet CLI
```

```bash
curl -F file=@schedule.pdf http://localhost:8000/v1/normalize/athena
curl -F file=@aamg.csv -F 'options={"dateFormat":"dd/mm/yyyy"}' http://localhost:8000/v1/normalize/epic
```

Never commit real EHR exports. `.gitignore` blocks `*.pdf`, `*.csv`, `*.xls*` and `*.txt`; tests build
synthetic files in code.

## Deployment

- **Image:** built from `Dockerfile` (Python 3.12, poppler, non-root, port 8000) as
  `ragaai/clinicalops-ehr-adapter:<build>` by the shared Jenkins pipeline.
- **Kubernetes:** deployed from `clinicalops-core-infra` (`helm-charts/clinicalops-services`) as the ClusterIP
  Service `clinicalops-ehr-adapter`, port 80 → 8000, with `/health` probes.
