"""EPIC / AAMG VOB export: JMPN member-ID cleaner + date normalizer.

Functions moved verbatim from app.py. ``read_epic_frame`` and ``run_epic_pipeline`` hold what was
inline in the EPIC tab (file loading, "PHASE 1" and "PHASE 2" of the unified pipeline).
"""

import io
import re
from dataclasses import dataclass, field

import pandas as pd

from ehr_adapter.pipelines.common import is_html_table, read_html_first_table


def read_epic_frame(file_bytes: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        if is_html_table(file_bytes):
            return read_html_first_table(file_bytes, "No tables found in HTML/Excel file.")
        return pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    try:
        return pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8", dtype=str)
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(file_bytes), encoding="cp1252", dtype=str)


# ── Date normalizer ───────────────────────────────────────────────────────────

def detect_aamg_date_format(sample_strings):
    """
    Checks the first few data rows: if the first date component is > 12,
    the source is treated as dd/mm/yyyy. Otherwise defaults to mm/dd/yyyy.
    """
    for s in sample_strings:
        if not s or pd.isna(s):
            continue
        s_clean = str(s).strip()
        m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s_clean)
        if m:
            first_num = int(m.group(1))
            second_num = int(m.group(2))
            if first_num > 12:
                return "dd/mm/yyyy"
            if second_num > 12:
                return "mm/dd/yyyy"
    return "mm/dd/yyyy"


def normalize_aamg_date(val, source_format="mm/dd/yyyy"):
    """
    Normalizes Visit Date or Patient DOB to MM/DD/YYYY with zero-padded month and day.
    If source_format is 'dd/mm/yyyy', day and month are swapped.
    """
    if val is None or pd.isna(val):
        return ""
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("nan", "nat", "none", "null"):
        return ""

    # Strip any trailing time component if present
    date_part = val_str.split()[0] if " " in val_str else val_str

    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", date_part)
    if m:
        p1, p2, y_str = m.groups()
        y = int(y_str)
        if len(y_str) == 2:
            y = 2000 + y if y < 50 else 1900 + y

        if source_format == "dd/mm/yyyy":
            day = int(p1)
            month = int(p2)
        else:
            month = int(p1)
            day = int(p2)

        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month:02d}/{day:02d}/{y:04d}"

    # Fallback to pandas parser for ISO or other standard dates
    try:
        dt = pd.to_datetime(date_part, dayfirst=(source_format == "dd/mm/yyyy"), errors='coerce')
        if pd.notna(dt):
            return dt.strftime("%m/%d/%Y")
    except Exception:
        pass

    return val_str


def process_aamg_df(df_raw, format_choice="auto"):
    """
    Processes AAMG VOB records:
    1. Identifies Visit Date and Patient DOB columns.
    2. Detects or overrides format ('dd/mm/yyyy' or 'mm/dd/yyyy').
    3. Normalizes them to MM/DD/YYYY with zero-padded month and day.
    4. Generates a spot-check comparison for the first 3 rows.
    """
    df = df_raw.copy()

    visit_col = None
    dob_col = None

    # Priority search for exact or variations of column names
    for col in df.columns:
        col_clean = re.sub(r'[\s_\-\.]+', '', str(col)).lower()
        if col_clean in ('visitdate', 'dateofvisit', 'servicedate', 'dos'):
            visit_col = col
        elif col_clean in ('patientdob', 'dob', 'dateofbirth', 'patientdateofbirth'):
            dob_col = col

    if not visit_col and 'Visit Date' in df.columns:
        visit_col = 'Visit Date'
    if not dob_col and 'Patient DOB' in df.columns:
        dob_col = 'Patient DOB'

    sample_values = []
    if visit_col:
        sample_values.extend(df[visit_col].dropna().astype(str).head(10).tolist())
    if dob_col:
        sample_values.extend(df[dob_col].dropna().astype(str).head(10).tolist())

    if format_choice == "dd/mm/yyyy":
        detected_label = "DD/MM/YYYY (Manual Override)"
        effective_format = "dd/mm/yyyy"
    elif format_choice == "mm/dd/yyyy":
        detected_label = "MM/DD/YYYY (Manual Override)"
        effective_format = "mm/dd/yyyy"
    else:
        detected = detect_aamg_date_format(sample_values)
        if detected == "dd/mm/yyyy":
            detected_label = "DD/MM/YYYY (Auto-detected: day > 12)"
            effective_format = "dd/mm/yyyy"
        else:
            detected_label = "MM/DD/YYYY (Auto-detected / Default)"
            effective_format = "mm/dd/yyyy"

    # Spot-check data for first 3 rows
    spot_rows = []
    first_3 = df.head(3)
    for idx, row in first_3.iterrows():
        orig_visit = str(row[visit_col]) if visit_col and visit_col in row and pd.notna(row[visit_col]) else ""
        norm_visit = normalize_aamg_date(orig_visit, effective_format) if visit_col else "N/A"
        orig_dob = str(row[dob_col]) if dob_col and dob_col in row and pd.notna(row[dob_col]) else ""
        norm_dob = normalize_aamg_date(orig_dob, effective_format) if dob_col else "N/A"

        spot_rows.append({
            "Row #": idx + 1,
            "Original Visit Date": orig_visit,
            "Normalized Visit Date": norm_visit,
            "Original Patient DOB": orig_dob,
            "Normalized Patient DOB": norm_dob
        })
    spot_df = pd.DataFrame(spot_rows)

    # Normalize entire dataframe columns
    if visit_col:
        df[visit_col] = df[visit_col].apply(lambda x: normalize_aamg_date(x, effective_format))
    if dob_col:
        df[dob_col] = df[dob_col].apply(lambda x: normalize_aamg_date(x, effective_format))

    return df, spot_df, detected_label, visit_col, dob_col


# ── AAMG / JMPN member-ID cleaner ─────────────────────────────────────────────

def is_anthem_payer(raw_payer, extra_keywords=None, require_jmpn=True):
    """
    Detects if raw_payer matches JMPN Anthem Blue Cross.
    - If require_jmpn=True (Default / Ishartek rule):
      Payer must be affiliated with JMPN/AAMG (contains 'JMPN', 'AAMG', 'JOHN MUIR')
      AND have 'ANTHEM' or 'BLUE CROSS'. Regular commercial Anthem (non-JMPN) is excluded.
    - If require_jmpn=False:
      Matches any Anthem / Blue Cross plan broadly.
    """
    if not raw_payer or pd.isna(raw_payer):
        return False
    s = str(raw_payer).strip().upper()
    # Remove bracketed codes like [1185026] and parentheses like (1185026)
    clean = re.sub(r'\[.*?\]', '', s)
    clean = re.sub(r'\(.*?\)', '', clean).strip()

    # Check extra custom keywords if provided
    if extra_keywords:
        for kw in extra_keywords:
            kw_clean = str(kw).strip().upper()
            if kw_clean and (kw_clean in s or kw_clean in clean):
                return True

    has_network = any(net in s for net in ['JMPN', 'AAMG', 'JOHN MUIR'])
    has_anthem = 'ANTHEM' in s
    has_bc = any(bc in s for bc in ['BLUE CROSS', 'BLUECROSS', 'BCBS', 'BC/BS', 'BC-BS'])

    if require_jmpn:
        # Strictly JMPN Anthem (as specified by Ishartek)
        return has_network and (has_anthem or has_bc)
    else:
        # Broad Anthem match
        return has_anthem or (has_network and has_bc)


def is_healthy_employee_payer(raw_payer, extra_keywords=None):
    """
    Detects if raw_payer matches Healthy Employee Plan family, regardless of name variation.
    Handles:
    - 'JMPN Healthy Employee Plan [1640000026]'
    - 'Healthy Employee Plan [1640000026]'
    - 'Healthy Employee Benefit Plan'
    - 'Healthy Employee'
    - 'Healthy Employees'
    - 'Healthy Emp Plan', 'Healthy Emp'
    - 'HEP', 'JMPN HEP', 'JMPN - HEP'
    """
    if not raw_payer or pd.isna(raw_payer):
        return False
    s = str(raw_payer).strip().upper()
    has_hep_code = '1640000026' in s
    clean = re.sub(r'\[.*?\]', '', s)
    clean = re.sub(r'\(.*?\)', '', clean).strip()

    if extra_keywords:
        for kw in extra_keywords:
            kw_clean = str(kw).strip().upper()
            if kw_clean and (kw_clean in s or kw_clean in clean):
                return True

    if has_hep_code:
        return True

    # Match HEALTHY with EMPLOYEE / EMP / PLAN / BENEFIT
    if 'HEALTHY' in s and any(w in s for w in ['EMPLOYEE', 'EMPLOYEES', 'EMP', 'BENEFIT', 'PLAN']):
        return True

    # Match standalone HEP
    words = re.findall(r'\b[A-Z0-9]+\b', s)
    if 'HEP' in words:
        return True

    return False


def clean_jmpn_member_id(raw_id, raw_payer, strip_anthem=True, strip_healthy=True, anthem_extra=None, healthy_extra=None, require_jmpn_anthem=True):
    """
    Cleans Member/Policy IDs according to JMPN/AAMG rules:
    - Rule 1: JMPN Anthem -> Target length 12 characters. If length is 14 (or >12), strip the last 2 digits.
    - Rule 2: JMPN Healthy Employee Plan -> Target length 9 characters. If length is 11 (or >9), strip the last 2 digits.
    - Other payers -> unchanged.

    Returns: (cleaned_id, rule_applied, was_modified)
    """
    if raw_id is None or pd.isna(raw_id):
        return "", "Empty ID", False

    s_id = str(raw_id).strip()
    if s_id.endswith('.0') and s_id[:-2].isdigit():
        s_id = s_id[:-2]

    if not s_id or s_id.lower() in ('nan', 'nat', 'none', 'null'):
        return "", "Empty ID", False

    is_anthem = is_anthem_payer(raw_payer, extra_keywords=anthem_extra, require_jmpn=require_jmpn_anthem)
    is_healthy = is_healthy_employee_payer(raw_payer, extra_keywords=healthy_extra)

    if strip_anthem and is_anthem:
        if len(s_id) == 14:
            return s_id[:-2], "JMPN Anthem (14 -> 12 chars, stripped last 2)", True
        elif len(s_id) > 12:
            return s_id[:12], f"JMPN Anthem ({len(s_id)} -> 12 chars, trimmed)", True
        else:
            return s_id, "JMPN Anthem (<= 12 chars, untouched)", False

    if strip_healthy and is_healthy:
        if len(s_id) == 11:
            return s_id[:-2], "Healthy Employee (11 -> 9 chars, stripped last 2)", True
        elif len(s_id) > 9:
            return s_id[:9], f"Healthy Employee ({len(s_id)} -> 9 chars, trimmed)", True
        else:
            return s_id, "Healthy Employee (<= 9 chars, untouched)", False

    return s_id, "Other Payer (untouched)", False


def auto_detect_jmpn_columns(df):
    """
    Auto-detects the payer, member/policy ID, and patient columns in df.
    """
    payer_candidates = [
        'original payer', 'payer', 'payer name', 'insurance',
        'primary payer', 'plan name', 'plan', 'payer_name'
    ]
    id_candidates = [
        'launch reg - pt id', 'primary mem id', 'policy no.', 'policy no',
        'policy id', 'member id', 'mem id', 'subscriber id',
        'launch reg-pt id', 'member_id', 'policy_no', 'pt id', 'patient id'
    ]
    patient_candidates = [
        'patient', 'patient name', 'patient_name', 'pt name', 'guarantor'
    ]

    detected_payer = None
    detected_id = None
    detected_patient = None

    cols = list(df.columns)
    for c in cols:
        c_clean = str(c).strip().lower()
        if not detected_payer and c_clean in payer_candidates:
            detected_payer = c
        if not detected_id and c_clean in id_candidates:
            detected_id = c
        if not detected_patient and c_clean in patient_candidates:
            detected_patient = c

    if not detected_payer:
        for c in cols:
            c_clean = str(c).strip().lower()
            if any(cand in c_clean for cand in ['payer', 'insurance', 'plan']):
                detected_payer = c
                break

    if not detected_id:
        for c in cols:
            c_clean = str(c).strip().lower()
            if any(cand in c_clean for cand in ['mem id', 'policy', 'member id', 'pt id', 'launch reg']):
                detected_id = c
                break

    if not detected_patient:
        for c in cols:
            c_clean = str(c).strip().lower()
            if 'patient' in c_clean or 'name' in c_clean:
                detected_patient = c
                break

    return detected_payer, detected_id, detected_patient


# ── Unified pipeline (was inline in the EPIC tab) ─────────────────────────────

@dataclass
class EpicPipelineOptions:
    enable_policy_cleaner: bool = True
    payer_col: str | None = None
    id_col: str | None = None
    patient_col: str | None = None
    apply_anthem: bool = True
    strict_jmpn_anthem: bool = True
    apply_healthy: bool = True
    anthem_extra: list = field(default_factory=list)
    healthy_extra: list = field(default_factory=list)
    enable_date_norm: bool = True
    format_choice: str | None = "auto"  # "auto" | "mm/dd/yyyy" | "dd/mm/yyyy"; None = disabled


@dataclass
class EpicPipelineResult:
    df: pd.DataFrame
    total_records: int
    audit_records: list
    anthem_modified_count: int
    healthy_modified_count: int
    total_modified_count: int
    payer_summary: list
    spot_df: pd.DataFrame | None
    detected_label: str
    visit_col: str | None
    dob_col: str | None


def run_epic_pipeline(df_raw: pd.DataFrame, opts: EpicPipelineOptions) -> EpicPipelineResult:
    df_curr = df_raw.copy()
    total_records = len(df_curr)
    selected_payer_col = opts.payer_col
    selected_id_col = opts.id_col
    selected_patient_col = opts.patient_col
    anthem_extra_list = opts.anthem_extra
    healthy_extra_list = opts.healthy_extra
    strict_jmpn_anthem = opts.strict_jmpn_anthem

    # --- PHASE 1: AAMG / JMPN Policy Formatter ---
    audit_records = []
    anthem_modified_count = 0
    healthy_modified_count = 0
    total_modified_count = 0
    payer_summary = []

    if opts.enable_policy_cleaner and selected_id_col and selected_id_col in df_curr.columns and selected_payer_col and selected_payer_col in df_curr.columns:
        # Payer summary
        unique_payers = [p for p in df_curr[selected_payer_col].dropna().unique()]
        for p in unique_payers:
            p_str = str(p).strip()
            is_a = is_anthem_payer(p_str, anthem_extra_list, require_jmpn=strict_jmpn_anthem)
            is_h = is_healthy_employee_payer(p_str, healthy_extra_list)
            cnt = int((df_curr[selected_payer_col].astype(str).str.strip() == p_str).sum())
            if is_a:
                fam = "🔵 JMPN Anthem Family"
                act = "Rule 1: Strip to 12 digits (strip last 2 if 14)"
            elif is_h:
                fam = "🟢 JMPN Healthy Employee Family"
                act = "Rule 2: Strip to 9 digits (strip last 2 if 11)"
            elif 'ANTHEM' in p_str.upper() and strict_jmpn_anthem:
                fam = "⚪ Commercial Anthem (Non-JMPN)"
                act = "Untouched (preserved as-is because no JMPN keyword)"
            else:
                fam = "⚪ Other Payer"
                act = "Untouched (kept as-is)"
            payer_summary.append({
                "Payer Name Variation in CSV": p_str,
                "Matched Payer Family": fam,
                "Rule": act,
                "Count": cnt
            })

        description_col_values = {}
        for idx, row in df_curr.iterrows():
            raw_id_val = row[selected_id_col]
            raw_payer_val = row[selected_payer_col]

            patient_name_for_desc = ""
            if selected_patient_col and selected_patient_col in df_curr.columns:
                patient_name_for_desc = str(row.get(selected_patient_col, "")).strip()

            cleaned_id, rule_name, was_modified = clean_jmpn_member_id(
                raw_id_val,
                raw_payer_val,
                strip_anthem=opts.apply_anthem,
                strip_healthy=opts.apply_healthy,
                anthem_extra=anthem_extra_list,
                healthy_extra=healthy_extra_list,
                require_jmpn_anthem=strict_jmpn_anthem
            )

            if patient_name_for_desc:
                desc = f"{patient_name_for_desc} | {rule_name}"
            else:
                desc = rule_name
            description_col_values[idx] = desc

            if was_modified:
                df_curr.at[idx, selected_id_col] = cleaned_id
                total_modified_count += 1
                if "Anthem" in rule_name:
                    anthem_modified_count += 1
                elif "Healthy" in rule_name:
                    healthy_modified_count += 1

                audit_record = {
                    "Row #": idx + 1,
                    "Payer": str(raw_payer_val),
                    "Original ID": str(raw_id_val),
                    "Cleaned ID": cleaned_id,
                    "Rule Applied": rule_name,
                    "Description": desc,
                    "Len Before": len(str(raw_id_val).strip()),
                    "Len After": len(cleaned_id)
                }
                if selected_patient_col and selected_patient_col in row:
                    audit_record["Patient"] = str(row[selected_patient_col])
                audit_records.append(audit_record)

        df_curr["Description"] = pd.Series(description_col_values).fillna("")

        if audit_records and "Patient" in audit_records[0]:
            keys = ["Row #", "Patient", "Payer", "Original ID", "Cleaned ID", "Rule Applied", "Description", "Len Before", "Len After"]
            audit_records = [{k: r.get(k, "") for k in keys} for r in audit_records]
        elif audit_records:
            keys = ["Row #", "Payer", "Original ID", "Cleaned ID", "Rule Applied", "Description", "Len Before", "Len After"]
            audit_records = [{k: r.get(k, "") for k in keys} for r in audit_records]

    # --- PHASE 2: Date Normalization ---
    spot_df = None
    detected_label = "Date Normalization Disabled"
    visit_col = None
    dob_col = None
    if opts.enable_date_norm and opts.format_choice:
        df_curr, spot_df, detected_label, visit_col, dob_col = process_aamg_df(df_curr, opts.format_choice)

    return EpicPipelineResult(
        df=df_curr,
        total_records=total_records,
        audit_records=audit_records,
        anthem_modified_count=anthem_modified_count,
        healthy_modified_count=healthy_modified_count,
        total_modified_count=total_modified_count,
        payer_summary=payer_summary,
        spot_df=spot_df,
        detected_label=detected_label,
        visit_col=visit_col,
        dob_col=dob_col,
    )
