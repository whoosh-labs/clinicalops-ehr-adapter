"""Service layer: raw EHR export -> canonical VOB import CSV.

Runs the existing pipeline for a source, renames its output to internal-api's canonical columns
(``VobCsvColumnDefinition``) and moves rows that can't be imported into ``dropped``. Nothing here
writes to disk or logs row contents.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd
from pdfminer.psparser import PSException
from pdfplumber.utils.exceptions import PdfminerException

from ehr_adapter.pipelines import athena, epic, meditab, modmed, modulemd

PATIENT_NAME = "Patient Name"
DOB = "DOB"
APPT_PROVIDER = "Appt. Provider"
SERVICE_DATE = "Service Date"
INSURANCE = "Insurance"
POLICY_NO = "Policy No."
APPOINTMENT_TYPE = "Appointment Type"
CLINIC = "Clinic"
EMAIL = "Email"
PHONE = "Phone"

REQUIRED = [PATIENT_NAME, DOB, SERVICE_DATE, INSURANCE, POLICY_NO]
DATE_COLUMNS = (DOB, SERVICE_DATE)

# Exceptions the pipelines raise on a file that isn't the expected export (bad CSV, not a PDF, ...).
UNREADABLE_FILE_ERRORS = (ValueError, PSException, PdfminerException)


class InputFormatError(ValueError):
    """The upload doesn't match the source's export format. Messages describe the file, never PHI."""


@dataclass
class Dropped:
    source: str
    reason: str
    patient_name: str = ""


@dataclass
class NormalizeResult:
    source: str
    columns: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_units: int = 0

    def to_csv(self) -> str:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=self.columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        return out.getvalue()


@dataclass(frozen=True)
class Source:
    name: str
    extensions: tuple[str, ...]
    columns: list[str]
    run: Callable[[bytes, str, dict[str, Any]], NormalizeResult]


# ── shared value clean-up ────────────────────────────────────────────────────

_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_FLOAT_ID = re.compile(r"^\d+\.0$")


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    s = str(value).strip()
    return "" if s.lower() in ("nan", "nat", "none") else s


def us_date(value: str) -> str:
    """MM/DD/YYYY without a time part; values in another shape are returned unchanged for internal-api."""
    head = re.split(r"[\sT]", value, maxsplit=1)[0] if value else value
    if m := _US_DATE.match(head):
        month, day, year = m.groups()
        return f"{int(month):02d}/{int(day):02d}/{year}"
    if m := _ISO_DATE.match(head):
        year, month, day = m.groups()
        return f"{int(month):02d}/{int(day):02d}/{year}"
    return value


def _add_row(result: NormalizeResult, ref: str, values: dict[str, Any]) -> None:
    row = {col: text(values.get(col)) for col in result.columns}
    for col in DATE_COLUMNS:
        row[col] = us_date(row[col])
    if _FLOAT_ID.match(row[POLICY_NO]):
        row[POLICY_NO] = row[POLICY_NO][:-2]

    missing = [col for col in REQUIRED if not row[col]]
    if missing:
        result.dropped.append(Dropped(ref, f"missing {', '.join(missing)}", row[PATIENT_NAME]))
        return
    result.rows.append(row)


def _rename(frame: pd.DataFrame, mapping: dict[str, str]) -> list[dict[str, Any]]:
    """Rows of ``frame`` keyed by canonical column, using ``{source column: canonical column}``."""
    present = {src: dst for src, dst in mapping.items() if src in frame.columns}
    return [{dst: rec[src] for src, dst in present.items()} for rec in frame.to_dict("records")]


# ── sources ──────────────────────────────────────────────────────────────────

ATHENA_COLUMNS = [PATIENT_NAME, DOB, APPT_PROVIDER, SERVICE_DATE, INSURANCE, POLICY_NO]


def run_athena(content: bytes, filename: str, options: dict[str, Any]) -> NormalizeResult:
    records, _ = athena.process_athena_pdf(io.BytesIO(content))
    if not records:
        raise InputFormatError("No valid appointment records found in the PDF (is this an AthenaOne schedule?)")
    result = NormalizeResult("athena", ATHENA_COLUMNS, source_units=len(records))
    for n, rec in enumerate(records, 1):
        _add_row(result, f"appointment {n}", rec)
    return result


MODMED_COLUMNS = [PATIENT_NAME, DOB, APPT_PROVIDER, SERVICE_DATE, INSURANCE, POLICY_NO]


def run_modmed(content: bytes, filename: str, options: dict[str, Any]) -> NormalizeResult:
    try:
        rows, dropped, src_count, fmt, _, _ = modmed.parse_facesheet_file(content, filename, require_csv_columns=True)
    except ValueError as exc:
        if "Missing required columns" in str(exc):
            raise InputFormatError(str(exc)) from None
        raise
    if src_count == 0:
        raise InputFormatError("The file has no pages or rows")

    unit = "page" if fmt == modmed.FORMAT_A else "line"
    result = NormalizeResult("modmed", MODMED_COLUMNS, source_units=src_count)
    for ref, name, reason in dropped:
        result.dropped.append(Dropped(f"{unit} {ref}", reason, name))
    for ref, (name, dos, dob, provider, carrier, policy) in rows:
        _add_row(result, f"{unit} {ref}", {PATIENT_NAME: name, DOB: dob, APPT_PROVIDER: provider,
                                           SERVICE_DATE: dos, INSURANCE: carrier, POLICY_NO: policy})
    return result


MEDITAB_COLUMNS = [PATIENT_NAME, DOB, APPT_PROVIDER, SERVICE_DATE, INSURANCE, POLICY_NO, APPOINTMENT_TYPE, EMAIL,
                   PHONE]
MEDITAB_MAP = {
    "patient_name": PATIENT_NAME, "patient_bdate": DOB, "doctor_name": APPT_PROVIDER, "schedule_date": SERVICE_DATE,
    "insurance_name": INSURANCE, "insurance_no": POLICY_NO, "procedure_name": APPOINTMENT_TYPE, "pat_email": EMAIL,
    "phone_mobile": PHONE,
}
MEDITAB_INPUT_COLUMNS = ["patient_name", "patient_bdate", "schedule_date"]


def run_meditab(content: bytes, filename: str, options: dict[str, Any]) -> NormalizeResult:
    raw = meditab.load_meditab_frame(meditab.decode_meditab_bytes(content), as_text=True)
    missing = [c for c in MEDITAB_INPUT_COLUMNS if c not in raw.columns]
    if missing:
        raise InputFormatError(f"Meditab export unrecognized. Missing required columns: {missing}")

    result = NormalizeResult("meditab", MEDITAB_COLUMNS, source_units=len(raw))
    for n, values in enumerate(_rename(meditab.process_meditab_df(raw), MEDITAB_MAP), 1):
        _add_row(result, f"record {n}", values)
    return result


MODULEMD_COLUMNS = [PATIENT_NAME, DOB, APPT_PROVIDER, SERVICE_DATE, INSURANCE, POLICY_NO, APPOINTMENT_TYPE, CLINIC,
                    EMAIL, PHONE]
MODULEMD_MAP = {
    "Patient Name": PATIENT_NAME, "Date of Birth": DOB, "Provider": APPT_PROVIDER, "Service Date": SERVICE_DATE,
    "Insurance Payer": INSURANCE, "Policy Number": POLICY_NO, "Appointment Type": APPOINTMENT_TYPE,
    "Clinic Location": CLINIC, "Email": EMAIL, "Cell Phone": PHONE,
}


def run_modulemd(content: bytes, filename: str, options: dict[str, Any]) -> NormalizeResult:
    out = modulemd.process_modulemd_df(modulemd.read_modulemd_frame(content, filename))
    if out.empty or not out["Patient Name"].str.strip().any():
        raise InputFormatError("ModuleMD header row not found (looked for 'Account #' in the first 15 rows)")

    result = NormalizeResult("modulemd", MODULEMD_COLUMNS, source_units=len(out))
    for n, values in enumerate(_rename(out, MODULEMD_MAP), 1):
        _add_row(result, f"record {n}", values)
    return result


EPIC_COLUMNS = [PATIENT_NAME, DOB, APPT_PROVIDER, SERVICE_DATE, INSURANCE, POLICY_NO]
EPIC_PROVIDER_COLUMNS = ("provider", "visit provider", "appt provider", "appointment provider", "provider name")
EPIC_DATE_FORMATS = ("auto", "mm/dd/yyyy", "dd/mm/yyyy")


def run_epic(content: bytes, filename: str, options: dict[str, Any]) -> NormalizeResult:
    date_format = options.get("dateFormat", "auto")
    if date_format not in EPIC_DATE_FORMATS:
        raise InputFormatError(f"options.dateFormat must be one of {list(EPIC_DATE_FORMATS)}")
    for key in ("anthemAliases", "healthyEmployeeAliases"):
        value = options.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise InputFormatError(f"options.{key} must be a list of strings")

    raw = epic.read_epic_frame(content, filename)
    payer_col, id_col, patient_col = epic.auto_detect_jmpn_columns(raw)
    result_df = epic.run_epic_pipeline(raw, epic.EpicPipelineOptions(
        payer_col=payer_col,
        id_col=id_col,
        patient_col=patient_col,
        strict_jmpn_anthem=bool(options.get("strictJmpnAnthem", True)),
        anthem_extra=list(options.get("anthemAliases", [])),
        healthy_extra=list(options.get("healthyEmployeeAliases", [])),
        format_choice=date_format,
    ))
    detected = {PATIENT_NAME: patient_col, DOB: result_df.dob_col, SERVICE_DATE: result_df.visit_col,
                INSURANCE: payer_col, POLICY_NO: id_col}
    missing = [canonical for canonical, col in detected.items() if not col]
    if missing:
        raise InputFormatError(f"EPIC export unrecognized. Could not find columns for: {missing}")
    provider_col = next((c for c in raw.columns if str(c).strip().lower() in EPIC_PROVIDER_COLUMNS), None)
    if provider_col:
        detected[APPT_PROVIDER] = provider_col

    result = NormalizeResult("epic", EPIC_COLUMNS, source_units=len(raw))
    for n, values in enumerate(_rename(result_df.df, {col: canonical for canonical, col in detected.items()}), 1):
        _add_row(result, f"row {n}", values)
    return result


SOURCES: dict[str, Source] = {
    s.name: s for s in (
        Source("athena", ("pdf",), ATHENA_COLUMNS, run_athena),
        Source("modmed", ("pdf", "csv"), MODMED_COLUMNS, run_modmed),
        Source("meditab", ("csv", "txt"), MEDITAB_COLUMNS, run_meditab),
        Source("modulemd", ("xls", "xlsx", "csv"), MODULEMD_COLUMNS, run_modulemd),
        Source("epic", ("csv", "xlsx", "xls"), EPIC_COLUMNS, run_epic),
    )
}
PENDING_SOURCES = {"ecw": "ecw needs the two-file upload (appointments + eligibility), which is not supported yet"}


def normalize(source: str, filename: str, content: bytes, options: dict[str, Any]) -> NormalizeResult:
    spec = SOURCES[source]
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension not in spec.extensions:
        allowed = ", ".join(f".{e}" for e in spec.extensions)
        raise InputFormatError(f"{source} expects {allowed}; got '.{extension}'")
    if not content:
        raise InputFormatError("The uploaded file is empty")
    try:
        return spec.run(content, filename, options)
    except InputFormatError:
        raise
    except UNREADABLE_FILE_ERRORS as exc:
        raise InputFormatError(f"Could not read the file as a {source} export ({type(exc).__name__})") from None
