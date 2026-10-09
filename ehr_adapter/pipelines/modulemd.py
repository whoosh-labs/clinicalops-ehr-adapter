"""ModuleMD schedule export (moved verbatim from app.py; file reading was inline in the ModuleMD tab)."""

import io
import re

import pandas as pd

from ehr_adapter.pipelines.common import is_html_table, read_html_first_table

MODULEMD_OUTPUT_COLUMNS = [
    "Account Number", "Patient Name", "Date of Birth", "Email", "Gender", "Primary Language",
    "Provider", "Provider NPI", "Visit Slip", "Appointment Type", "Clinic Location",
    "Service Date", "Service Time", "Return Visit", "Last Visit", "Last Injection",
    "Address", "Home Phone", "Cell Phone", "Insurance Payer", "Policy Number",
    "Type", "Patient Balance", "Insurance Balance", "Copay", "Reason",
    "Referral Provider Name", "Special Instructions", "Guarantor", "Eligibility",
    "Co-Insurance", "Out Of Pocket"
]


def read_modulemd_frame(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """ModuleMD exports an HTML table saved as .xls; real .xls/.xlsx and .csv are also accepted."""
    if filename.lower().endswith(".csv"):
        try:
            return pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8")
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(file_bytes), encoding="cp1252")
    if is_html_table(file_bytes):
        return read_html_first_table(file_bytes, "No HTML tables found in the uploaded file.")
    return pd.read_excel(io.BytesIO(file_bytes))


def normalize_modulemd_date(val):
    if val is None or pd.isna(val):
        return ""
    val_str = str(val).strip()
    if val_str.lower() in ("nan", "nat", ""):
        return ""

    # Split on first space to strip time component
    parts = val_str.split(maxsplit=1)
    date_part = parts[0]

    # Match MM/DD/YYYY with varying digits
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_part)
    if match:
        mm, dd, yyyy = match.groups()
        return f"{int(mm):02d}/{int(dd):02d}/{yyyy}"

    return val_str


def parse_modulemd_insurance(val):
    if val is None or pd.isna(val):
        return [{"payer": "", "policy": "", "type": ""}]

    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("nan", "nat", "") or val_str == "****":
        return [{"payer": "", "policy": "", "type": ""}]

    val_str = val_str.replace("****", "")
    segments = [s.strip() for s in val_str.split("**") if s.strip()]

    parsed = []
    types = ["Primary", "Secondary", "Tertiary", "Quaternary", "Quinary"]
    for i, seg in enumerate(segments):
        seg_clean = seg.strip('*').strip()
        if not seg_clean:
            continue
        m = re.match(r"^(.*)\[(.*)\]$", seg_clean)
        ins_type = types[i] if i < len(types) else f"Insurance_{i+1}"
        if m:
            payer, policy = m.groups()
            parsed.append({"payer": payer.strip(), "policy": policy.strip(), "type": ins_type})
        else:
            parsed.append({"payer": seg_clean, "policy": "", "type": ins_type})

    if not parsed:
        return [{"payer": "", "policy": "", "type": ""}]

    return parsed


def process_modulemd_df(df_raw):
    df_raw = df_raw.copy()

    # 1. Check if df_raw.columns already contains Account header
    cols_lower = [str(c).strip().lower() for c in df_raw.columns]
    has_header_already = any(h in cols_lower for h in ("account #", "account number", "account no", "acct #", "acct no"))

    if has_header_already:
        df_data = df_raw
    else:
        # Promote headers dynamically by looking for "Account #" row
        header_idx = None
        for i in range(min(15, len(df_raw))):
            row_vals = [str(x).strip().lower() for x in df_raw.iloc[i].values]
            if any(h in row_vals for h in ("account #", "account number", "account no", "acct #", "acct no")):
                header_idx = i
                break

        if header_idx is not None:
            df_raw.columns = df_raw.iloc[header_idx]
            df_data = df_raw.iloc[header_idx+1:].reset_index(drop=True)
        else:
            df_data = df_raw

    # Retain all columns safely without artificial truncation
    df_data = df_data.copy()

    records = []
    for _, row in df_data.iterrows():
        def get_val(col):
            if col in row.index:
                v = row[col]
                if pd.isna(v):
                    return ""
                return str(v).strip()
            return ""

        dob = normalize_modulemd_date(row.get("Date of Birth")) if "Date of Birth" in row.index else ""
        return_visit = normalize_modulemd_date(row.get("Return Visit")) if "Return Visit" in row.index else ""
        last_visit = normalize_modulemd_date(row.get("Last Visit")) if "Last Visit" in row.index else ""
        last_injection = normalize_modulemd_date(row.get("Last Injection")) if "Last Injection" in row.index else ""

        service_date = ""
        service_time = ""
        if "Schedule Date" in row.index:
            schedule_date_val = row["Schedule Date"]
            if schedule_date_val is not None and not pd.isna(schedule_date_val):
                schedule_date_str = str(schedule_date_val).strip()
                service_date = normalize_modulemd_date(schedule_date_str)
                parts = schedule_date_str.split(maxsplit=1)
                if len(parts) > 1:
                    service_time = parts[1].strip()

        email = get_val("Email")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            email = ""

        insurance_val = row.get("Insurance") if "Insurance" in row.index else ""
        insurances = parse_modulemd_insurance(insurance_val)

        for ins in insurances:
            records.append({
                "Account Number": get_val("Account #"),
                "Patient Name": get_val("Patient Name"),
                "Date of Birth": dob,
                "Email": email,
                "Gender": get_val("Gender"),
                "Primary Language": get_val("Primary Language"),
                "Provider": get_val("Provider"),
                "Provider NPI": get_val("Provider NPI"),
                "Visit Slip": get_val("Visit Slip"),
                "Appointment Type": get_val("Visit Type"),
                "Clinic Location": get_val("Location"),
                "Service Date": service_date,
                "Service Time": service_time,
                "Return Visit": return_visit,
                "Last Visit": last_visit,
                "Last Injection": last_injection,
                "Address": get_val("Address"),
                "Home Phone": get_val("Home Phone"),
                "Cell Phone": get_val("Cell Phone"),
                "Insurance Payer": ins["payer"],
                "Policy Number": ins["policy"],
                "Type": ins["type"],
                "Patient Balance": get_val("Patient Balance"),
                "Insurance Balance": get_val("Insurance Balance"),
                "Copay": get_val("Copay"),
                "Reason": get_val("Reason"),
                "Referral Provider Name": get_val("Referral Provider Name"),
                "Special Instructions": get_val("Special Instructions"),
                "Guarantor": get_val("Guarantor"),
                "Eligibility": get_val("Eligibility"),
                "Co-Insurance": get_val("Co-Insurance"),
                "Out Of Pocket": get_val("Out Of Pocket")
            })

    df_out = pd.DataFrame(records, columns=MODULEMD_OUTPUT_COLUMNS)
    df_out = df_out.astype(str)
    for col in df_out.columns:
        df_out[col] = df_out[col].replace({"nan": "", "NaT": ""})
    return df_out
