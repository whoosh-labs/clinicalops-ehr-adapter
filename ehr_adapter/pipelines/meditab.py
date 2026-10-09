"""IMS Meditab export (moved verbatim from app.py; loading was inline in the Meditab tab)."""

import io
import re

import pandas as pd

MEDITAB_TARGET_COLUMNS = [
    "office_name", "office_code", "office_id", "schedule_date", "schedule_time", "doctor_name", "room", "procedure_name", "case_no", "case_type",
    "start_date", "insurance_priority", "insurance_name", "priority", "confirm_status", "patient_name", "patient_bdate", "patient_zip", "patient_sex", "created_by_display",
    "created_date", "created_datetime", "duration", "insurance_type", "schedule_note", "p_contact_nos", "patient_type_ids", "patient_type_description", "case_description", "status",
    "doctor_id", "resource_id", "procedure_id", "patient_id", "insurance_no", "patient_balance", "visit_type", "visit_type_description", "need_interpreter", "visit_date",
    "visit_status", "status_code", "status_desc", "visit_status_description", "pos_master_description", "pn_visit_type", "pn_visit_type_description", "phone_mobile", "phone_work", "pat_age",
    "appt_changed_by_display", "appt_response_from", "appt_confirmed_date", "patient_address", "zip", "is_televisit_display", "preferred_phones", "is_website4md_disp", "secondary_procedure_name", "tertiary_procedure_name",
    "other_procedure", "all_procedure", "interaction_desc", "schedule_status_description", "ref_doctor_id", "ref_doctor_name", "npi_number", "ref_doctor_with_address", "ref_phone", "ref_fax",
    "ref_email", "referral_party_id", "referral_source", "case_ref_doctor_id", "case_ref_doctor_name", "c_status", "c_schedule_time", "pat_email", "patient_primary_language", "patient_aka",
    "noshow_probability", "pat_firstname", "pat_lastname", "patient_no"
]

MEDITAB_DATE_COLUMNS = [
    "schedule_date", "start_date", "patient_bdate", "created_date",
    "visit_date", "created_datetime", "appt_confirmed_date"
]


def normalize_meditab_date(val):
    if not val or pd.isna(val):
        return ""
    val_str = str(val).strip()
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})(.*)$", val_str)
    if match:
        m, d, y, trailing = match.groups()
        return f"{int(m):02d}/{int(d):02d}/{y}{trailing}"
    return val_str


def reconstruct_meditab_csv_blob(content):
    lines = content.split('\n')
    header_line = lines[0].strip()
    blob = "\n".join(lines[1:])
    anchor = "office_name,office_code,office_id,"

    parts = blob.split(anchor)
    reconstructed_lines = [header_line]
    for part in parts:
        if not part.strip():
            continue
        reconstructed_lines.append(anchor + part.strip())

    return "\n".join(reconstructed_lines)


def decode_meditab_bytes(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw_bytes.decode('cp1252', errors='replace')


def load_meditab_frame(raw_content: str, as_text: bool = False) -> pd.DataFrame:
    """Raw export text -> DataFrame, rebuilding exports that arrive as one or two very long lines.

    ``as_text`` reads every cell as a string. The Streamlit tab reads with pandas type inference
    (unchanged); the service passes True so numeric policy numbers keep leading zeros and never
    turn into floats like ``123456789.0`` when a column has blanks.
    """
    lines = [l for l in raw_content.split('\n') if l.strip()]
    needs_reconstruct = len(lines) <= 2 and len(raw_content) > 1000
    text = reconstruct_meditab_csv_blob(raw_content) if needs_reconstruct else raw_content
    return pd.read_csv(io.StringIO(text), encoding='cp1252', dtype=str if as_text else None)


def process_meditab_df(df_raw):
    all_transformed = []

    # Pre-compute insurance type lookup from primary entries in raw dataset
    ins_type_lookup = {}
    for _, r in df_raw.iterrows():
        p_name = str(r.get("ins_name") or r.get("insurance_name") or "").strip().upper()
        p_type = str(r.get("insurance_type") or "").strip()
        if p_name and p_type and p_type.lower() != "nan" and p_name not in ins_type_lookup:
            ins_type_lookup[p_name] = p_type

    for _, row in df_raw.iterrows():
        base = {}
        for col in MEDITAB_TARGET_COLUMNS:
            if col in row.index:
                base[col] = row[col]
            else:
                base[col] = ""

        # Normalize dates
        for col in MEDITAB_DATE_COLUMNS:
            if col in base:
                base[col] = normalize_meditab_date(base[col])

        # Primary row
        primary = base.copy()
        primary["insurance_priority"] = "Primary"
        primary["priority"] = "P"
        pri_ins_name = row.get("ins_name") or row.get("insurance_name") or row.get("primary_ins_name") or row.get("Primary Insurance") or base.get("insurance_name", "")
        pri_ins_no = row.get("insurance_no") or row.get("ins_no") or row.get("policy_no") or row.get("Primary Policy") or base.get("insurance_no", "")
        primary["insurance_name"] = "" if pd.isna(pri_ins_name) else str(pri_ins_name).strip()
        primary["insurance_no"] = "" if pd.isna(pri_ins_no) else str(pri_ins_no).strip()

        all_transformed.append(primary)

        # Secondary row
        sec_name = row.get("ins_secondary_name") or row.get("secondary_insurance_name") or row.get("sec_ins_name") or row.get("Secondary Insurance") or ""
        sec_no = row.get("sec_insurance_no") or row.get("secondary_policy_no") or row.get("sec_ins_no") or row.get("Secondary Policy") or ""
        has_secondary = False

        if not pd.isna(sec_name) and str(sec_name).strip() != "":
            has_secondary = True
        if not pd.isna(sec_no) and str(sec_no).strip() != "":
            has_secondary = True

        if has_secondary:
            secondary = base.copy()
            secondary["insurance_priority"] = "Secondary"
            secondary["priority"] = "S"
            sec_clean_name = "" if pd.isna(sec_name) else str(sec_name).strip()
            secondary["insurance_name"] = sec_clean_name
            secondary["insurance_no"] = "" if pd.isna(sec_no) else str(sec_no).strip()

            # Resolve secondary insurance_type correctly instead of inheriting primary insurance_type
            sec_upper = sec_clean_name.upper()
            if sec_upper in ins_type_lookup:
                secondary["insurance_type"] = ins_type_lookup[sec_upper]
            elif any(k in sec_upper for k in ["BC/BS", "BLUE CROSS", "BLUESHIELD"]):
                secondary["insurance_type"] = "BlueShield/Blue Cross"
            elif any(k in sec_upper for k in ["MEDICARE ADV", "MEDICARE ADVANTAGE"]):
                secondary["insurance_type"] = "Preferred Provider Organization (PPO)" if "PPO" in sec_upper else "Medicare"
            elif "MEDICARE" in sec_upper:
                secondary["insurance_type"] = "Medicare"
            elif "MEDICAID" in sec_upper:
                secondary["insurance_type"] = "Medicaid"
            elif any(k in sec_upper for k in ["TRICARE", "CHAMPVA"]):
                secondary["insurance_type"] = "Military / TRICARE"
            elif any(k in sec_upper for k in ["COMMERCIAL", "HEALTH PLAN", "AETNA", "CIGNA", "HUMANA", "UNITED"]):
                secondary["insurance_type"] = "Commercial Insurance Co"
            else:
                secondary["insurance_type"] = ""

            all_transformed.append(secondary)

    return pd.DataFrame(all_transformed, columns=MEDITAB_TARGET_COLUMNS)
