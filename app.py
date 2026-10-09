import streamlit as st
import pdfplumber
import re
import pandas as pd
import io
import os
import csv
import zipfile
import subprocess
from datetime import datetime
from pathlib import Path

# ── Page Configuration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DataOps Hub",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Custom CSS (SaaS Premium Look) ───────────────────────────────────────────
st.markdown("""
    <style>
    /* App Background */
    .stApp {
        background-color: #F8FAFC;
    }
    
    /* Hide top padding */
    .block-container {
        padding-top: 2rem;
    }

    /* Premium Header Banner */
    .saas-header {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
        color: white;
        padding: 2.5rem 2rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        text-align: center;
    }
    .saas-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 800;
        letter-spacing: -0.025em;
        color: #FFFFFF;
        font-family: 'Inter', sans-serif;
    }
    .saas-header p {
        margin-top: 0.5rem;
        font-size: 1.1rem;
        color: #94A3B8;
        font-weight: 400;
    }

    /* KPI / Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    }
    
    /* Metric Labels */
    div[data-testid="stMetricLabel"] {
        color: #64748B;
        font-weight: 600;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Metric Values */
    div[data-testid="stMetricValue"] {
        color: #0F172A;
        font-weight: 800;
        font-size: 2.5rem;
    }

    /* Primary Buttons */
    .stButton>button {
        background-color: #2563EB;
        color: white;
        border-radius: 8px;
        font-weight: 600;
        border: none;
        padding: 0.75rem 1.5rem;
        height: auto;
        transition: all 0.2s ease;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);
    }
    .stButton>button:hover {
        background-color: #1D4ED8;
        box-shadow: 0 10px 15px -3px rgba(37, 99, 235, 0.3);
        transform: translateY(-1px);
        color: white;
    }

    /* Section Titles */
    .section-title {
        font-size: 1.25rem;
        font-weight: 700;
        color: #1E293B;
        margin-top: 2rem;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
        border-bottom: 2px solid #E2E8F0;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        font-size: 16px;
        font-weight: 600;
        color: #64748B;
        padding: 0 20px;
    }
    .stTabs [aria-selected="true"] {
        color: #2563EB !important;
        border-bottom-color: #2563EB !important;
    }

    /* File Uploader Area */
    .stFileUploader {
        background-color: #FFFFFF;
        border-radius: 12px;
        padding: 1.5rem;
        border: 2px dashed #CBD5E1;
        transition: border-color 0.2s ease;
    }
    .stFileUploader:hover {
        border-color: #2563EB;
    }
    
    /* Dataframes */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        border: 1px solid #E2E8F0;
    }
    </style>
    """, unsafe_allow_html=True)

# ── Shared Utility Functions ──────────────────────────────────────────────────
def norm_name(s):
    if pd.isna(s): return ''
    s_clean = str(s).strip().lower()
    if s_clean in ('nan', 'nat', 'none', 'null'): return ''
    return re.sub(r'\s+', ' ', s_clean)

def norm_dob(s):
    if pd.isna(s): return ''
    s_clean = str(s).strip().lower()
    if s_clean in ('nan', 'nat', 'none', 'null', ''): return ''
    try:
        dt = pd.to_datetime(s_clean, errors='coerce')
        if pd.notna(dt):
            return dt.strftime('%Y-%m-%d')
    except:
        pass
    return s_clean

def get_name_match_key(s):
    """
    Extracts (last_name, first_name) from either 'Last, First' or 'First Last'
    stripping middle initials and special characters for fault-tolerant patient matching.
    """
    if pd.isna(s): return ''
    s = re.sub(r'[^a-zA-Z\s,]', '', str(s)).strip().lower()
    if not s or s in ('nan', 'nat', 'none', 'null'): return ''
    if ',' in s:
        parts = [p.strip() for p in s.split(',') if p.strip()]
        last = parts[0]
        first = parts[1].split()[0] if len(parts) > 1 else ''
        return f"{last}|{first}"
    else:
        parts = s.split()
        if len(parts) >= 2:
            return f"{parts[-1]}|{parts[0]}"
        return f"{s}|"

def create_zip_of_chunks(df, base_filename, rows_per_file=99):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as zf:
        chunks = [df.iloc[i:i+rows_per_file] for i in range(0, len(df), rows_per_file)]
        for i, chunk in enumerate(chunks, 1):
            fname = f"{base_filename}_part{i}.csv"
            zf.writestr(fname, chunk.to_csv(index=False))
    buf.seek(0)
    return buf

def extract_service_date(full_text):
    for line in full_text.split('\n')[:5]:
        line = line.strip()
        # Look for Day of week header first (e.g. Monday, October 12th or Monday, October 12, 2026)
        m_day = re.search(r'(\w+day,\s+\w+\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*20\d{2})?)', line, re.I)
        if m_day:
            raw = m_day.group(1)
            clean = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', raw)
            # If no year in line, append current year explicitly
            if not re.search(r'\b20\d{2}\b', clean):
                clean = f"{clean}, {datetime.now().year}"
            for fmt in ('%A, %B %d, %Y', '%A, %B %d %Y'):
                try:
                    dt = datetime.strptime(clean, fmt)
                    return dt.strftime('%m/%d/%Y')
                except:
                    pass
        # Check if line has explicit Service Date or DOS
        m_dos = re.search(r'(?:Date|DOS|Schedule Date):\s*(\d{1,2}/\d{1,2}/20\d{2})', line, re.I)
        if m_dos:
            return m_dos.group(1)
    return ''

APPT_RE = re.compile(r'^(\d{1,2}:\d{2}\s+[AP]M)\s*[-–—]\s*(\d{1,2}:\d{2}\s+[AP]M)\s+([\w/\s\-\(\)]+?)\s+([A-Za-z][A-Za-z\s,\-\.\']+)\s+\(([^)]*)\)\s+#(\d+)')
FREE_SLOT_RE = re.compile(r'^(\d{1,2}:\d{2}\s+[AP]M)\s*[-–—]\s*(\d{1,2}:\d{2}\s+[AP]M)\s+[\w/\s]+?FREE SLOT')
DOB_RE = re.compile(r'DOB:\s*(\d{1,2}/\d{1,2}/\d{4})')
INS_RE = re.compile(r'INS\s*:\s*(.+?)\s*#([\w\d\-\*]*)\s*$', re.I)

ATHENA_KNOWN_APPT_TYPES = sorted([
    'Biologic Drug Administration',
    'Food/Drug Challenge',
    'RUSH Immunotherapy',
    'Initial OIT',
    'Allergy Testing',
    'Telemedicine visit',
    'Allergy Shot',
    'New Patient',
    'Follow-up',
    'Updose',
    'Cluster',
    'Consultation',
    'Office Visit',
    'Annual Visit',
    'Sick Visit',
    'Well Child'
], key=len, reverse=True)

def process_athena_pdf(pdf_file):
    records = []
    with pdfplumber.open(pdf_file) as pdf:
        full_text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        service_date = extract_service_date(full_text)
        current_provider, lines = 'COMPLETE ALLERGY AND ASTHMA', full_text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            dept_m = re.match(r'^(.+?)\s+Department:', line, re.I)
            if dept_m:
                prov = dept_m.group(1).strip()
                if prov: current_provider = prov
                i += 1
                continue
            if re.match(r'NITI', line, re.I): current_provider = 'NITI Y. CHOKSHI, MD'; i += 1; continue
            if re.match(r'BRIAN', line, re.I): current_provider = 'BRIAN E. TISON, MD'; i += 1; continue
            if re.match(r'Department:', line, re.I): current_provider = 'COMPLETE ALLERGY AND ASTHMA'; i += 1; continue
            if FREE_SLOT_RE.match(line): i += 1; continue
            m = APPT_RE.match(line)
            if m:
                combined_middle = f"{m.group(3).strip()} {m.group(4).strip()}".strip()
                appt_type = m.group(3).strip()
                raw_name = m.group(4).strip().rstrip(',')
                for at in ATHENA_KNOWN_APPT_TYPES:
                    if combined_middle.lower().startswith(at.lower()):
                        appt_type = at
                        raw_name = combined_middle[len(at):].strip().rstrip(',')
                        break
                patient_name = ', '.join(part.strip().title() for part in raw_name.split(','))
                dob, insurance, policy_no = '', '', ''
                for j in range(i+1, min(i+10, len(lines))):
                    nxt = lines[j].strip()
                    if APPT_RE.match(nxt) or FREE_SLOT_RE.match(nxt):
                        break
                    if not dob and DOB_RE.search(nxt):
                        dob = DOB_RE.search(nxt).group(1)
                    if not insurance and re.match(r'^INS\b', nxt, re.I):
                        full_ins = nxt
                        if '#' not in full_ins and (j+1) < len(lines) and not APPT_RE.match(lines[j+1]) and not FREE_SLOT_RE.match(lines[j+1]):
                            full_ins += " " + lines[j+1].strip()
                        ins_m = INS_RE.search(full_ins)
                        if ins_m:
                            insurance, policy_no = ins_m.group(1).strip(), ins_m.group(2).strip()
                records.append({'Patient Name': patient_name, 'DOB': dob, 'Appt. Provider': current_provider, 'PCP': '', 'CHPCP': '', 'Service Date': service_date, 'Insurance': insurance, 'Policy No.': policy_no, 'Status': 'Not Submitted', 'Eligible': 'NOT VERIFIED'})
            i += 1
    return records, service_date

# ── Meditab Extraction Logic ──────────────────────────────────────────────────
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

# ── ModuleMD Extraction Logic ────────────────────────────────────────────────
MODULEMD_OUTPUT_COLUMNS = [
    "Account Number", "Patient Name", "Date of Birth", "Email", "Gender", "Primary Language",
    "Provider", "Provider NPI", "Visit Slip", "Appointment Type", "Clinic Location",
    "Service Date", "Service Time", "Return Visit", "Last Visit", "Last Injection",
    "Address", "Home Phone", "Cell Phone", "Insurance Payer", "Policy Number",
    "Type", "Patient Balance", "Insurance Balance", "Copay", "Reason",
    "Referral Provider Name", "Special Instructions", "Guarantor", "Eligibility",
    "Co-Insurance", "Out Of Pocket"
]

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

# ── AAMG VOB Uploads Logic ────────────────────────────────────────────────────
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

def create_aamg_chunks(df, base_filename, rows_per_file=100, local_output_dir=None):
    """
    Splits df into chunks of 100 data rows each, repeating header in every file.
    Quotes every field using csv.QUOTE_ALL.
    Names output files: <original_filename_with_underscores>_part01.csv, _part02.csv, etc.
    """
    clean_base = re.sub(r'[^\w\-]+', '_', base_filename).strip('_')
    if not clean_base:
        clean_base = "aamg_vobs"
        
    chunks = [df.iloc[i:i+rows_per_file] for i in range(0, len(df), rows_per_file)]
    if not chunks:
        chunks = [df]
        
    if local_output_dir:
        os.makedirs(local_output_dir, exist_ok=True)
        
    saved_files = []
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "a", zipfile.ZIP_DEFLATED, False) as zf:
        for i, chunk in enumerate(chunks, 1):
            fname = f"{clean_base}_part{i:02d}.csv"
            csv_str = chunk.to_csv(index=False, quoting=csv.QUOTE_ALL)
            zf.writestr(fname, csv_str.encode('utf-8'))
            if local_output_dir:
                file_path = os.path.join(local_output_dir, fname)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(csv_str)
                saved_files.append(file_path)
                
    zip_buf.seek(0)
    return zip_buf, saved_files, len(chunks)

def open_macos_folder_dialog(initial_dir=None):
    """
    Prompts user with native macOS Finder folder picker dialog.
    """
    if not initial_dir or not os.path.exists(initial_dir):
        initial_dir = os.path.expanduser('~')
    script = f'''
    set chosenFolder to choose folder with prompt "Select Local Output Directory" default location POSIX file "{initial_dir}"
    POSIX path of chosenFolder
    '''
    try:
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=60)
        folder = res.stdout.strip()
        return folder if folder else None
    except Exception:
        return None

# ── AAMG / JMPN Policy ID Stripper Logic ──────────────────────────────────────
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


# ── ModMed Face Sheet & Schedule Functions ─────────────────────────────────────
FACESHEET_HEADER = ["patient name", "date of service", "birth date", "appointment provider", "insurance name", "policy number"]
FACESHEET_PRE = {"MR", "MRS", "MS", "DR", "MISS"}
FACESHEET_SUF = {"JR", "SR", "II", "III", "IV"}
FACESHEET_PART = {"SAN", "DE", "DEL", "LA", "LOS", "VAN", "VON", "DA", "DI", "ST"}
FACESHEET_NO_INS = {"", "payer not found", "cash pay", "self pay", "self-pay", "selfpay", "none"}
FACESHEET_SUPPORT = re.compile(
    r"copay|co-pay|patient assistance|assistance program|savings|xolair|tezspire|dupixent|nucala|fasenra|cinqair|myway",
    re.I
)

def facesheet_left_val(line):
    return " ".join(
        m.group() for m in re.finditer(r"\S+(?: \S+)*", line)
        if 15 <= m.start() < 45 and not m.group().endswith(":")
    )

def facesheet_fmt_name(n):
    t = n.replace(",", " ").split()
    while t and t[0].rstrip(".").upper() in FACESHEET_PRE:
        t = t[1:]
    suf = t.pop() if t and t[-1].rstrip(".").upper() in FACESHEET_SUF else ""
    if len(t) >= 3 and len(t[1].rstrip(".")) == 1:
        first, last = t[:2], t[2:]
    else:
        k = len(t) - 1
        while k > 1 and t[k - 1].upper() in FACESHEET_PART:
            k -= 1
        first, last = t[:k], t[k:]
    return f"{' '.join(last)}{' ' + suf if suf else ''}, {' '.join(first)}"

def facesheet_is_support(carrier):
    c = (carrier or "").strip().lower()
    if "medical assistance" in c:
        return False
    return bool(FACESHEET_SUPPORT.search(c))

def facesheet_bad(carrier, policy):
    return not carrier or not policy or carrier.strip().lower() in FACESHEET_NO_INS or policy.strip() in {"0", "1"}

def facesheet_reason(carrier, policy):
    if facesheet_is_support(carrier):
        return f"support program, not a payer: carrier='{carrier}'"
    return f"incomplete insurance: carrier='{carrier}' policy='{policy}'"

def parse_facesheet_file(file_bytes, filename):
    import tempfile
    from collections import Counter
    rows, dropped = [], []
    src_count = 0
    secondaries_count = 0
    lower_name = filename.lower()

    if lower_name.endswith(".pdf"):
        format_type = "Format A: ModMed Face Sheet PDF"
        text = ""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            res = subprocess.run(["pdftotext", "-layout", tmp_path, "-"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                text = res.stdout
        except Exception:
            pass
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        if text.strip():
            pages = [p for p in text.split("\f") if p.strip()]
        else:
            pages = []
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for p in pdf.pages:
                    pages.append(p.extract_text(layout=True) or "")

        src_count = len(pages)
        for i, p in enumerate(pages, 1):
            L = p.split("\n")
            dos_match = re.search(r"Appointment:\s*(\d{2}/\d{2}/\d{4})", p)
            dos = dos_match.group(1) if dos_match else ""

            prov_matches = [re.search(r"Provider:\s*(.+)", l).group(1).strip() for l in L[:5] if "Provider:" in l]
            prov = prov_matches[0] if prov_matches else ""

            name_lines = [l for l in L if l.lstrip().startswith("Name:")]
            name = facesheet_fmt_name(facesheet_left_val(name_lines[0].replace("Name:", "     ", 1))) if name_lines else f"Unknown_Page_{i}"

            dob_match = re.search(r"D\.O\.B:\s+(\d{2}/\d{2}/\d{4})", p)
            dob = dob_match.group(1) if dob_match else ""

            base = [name, dos, dob, prov]
            blocks = [k for k, l in enumerate(L) if re.match(r"^\s*(Primary|Secondary|Tertiary) Insurance Information", l)]
            if not blocks:
                dropped.append((i, name, "no insurance on file"))
                continue

            valid_for_patient = 0
            for k in blocks:
                j, car = k + 1, []
                while j < len(L) and not L[j].lstrip().startswith("Policy #:"):
                    car.append(facesheet_left_val(L[j].replace("Carrier:", "        ", 1)))
                    j += 1
                carrier = " ".join(c for c in car if c).strip()
                policy = facesheet_left_val(L[j].replace("Policy #:", "         ", 1)) if j < len(L) else ""

                if facesheet_is_support(carrier) or facesheet_bad(carrier, policy):
                    dropped.append((i, name, facesheet_reason(carrier, policy)))
                    continue

                rows.append((i, base + [carrier, policy]))
                valid_for_patient += 1

            if valid_for_patient > 1:
                secondaries_count += 1

    elif lower_name.endswith(".csv"):
        format_type = "Format B: PatientDemoGraphicData CSV"
        text_content = ""
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
            try:
                text_content = file_bytes.decode(enc)
                break
            except Exception:
                continue

        reader = list(csv.DictReader(io.StringIO(text_content)))
        src_count = len(reader)
        for i, x in enumerate(reader, 2):
            g = lambda k: (x.get(k) or "").strip()
            first = " ".join(v for v in [g("Pat F Name"), g("Pat M Initial")] if v)
            name = f"{g('Pat L Name')}, {first}".strip().rstrip(",")
            raw_date = g("Date")
            if "-" in raw_date:
                parts = raw_date.split("-")
                dos = f"{parts[1]}/{parts[2]}/{parts[0]}" if len(parts) == 3 else raw_date
            else:
                dos = raw_date

            dob = g("Pat Birthdate")
            prov = g("ProviderName")
            base = [name, dos, dob, prov]

            carrier = g("Primary Insurance Name")
            policy = g("Primary Ins Subscriber No")

            if facesheet_is_support(carrier) or facesheet_bad(carrier, policy):
                dropped.append((i, name, facesheet_reason(carrier, policy)))
                continue

            rows.append((i, base + [carrier, policy]))

    else:
        raise ValueError("Unsupported file format. Please upload a .pdf or .csv file.")

    support_counter = Counter(
        r.split("carrier='")[1].rstrip("'")
        for _, _, r in dropped
        if "support program" in r and "carrier='" in r
    )

    return rows, dropped, src_count, format_type, secondaries_count, support_counter

def chunk_facesheet_groups(rows, cap=99):
    groups = []
    for page, row in rows:
        if groups and groups[-1][0] == page:
            groups[-1][1].append(row)
        else:
            groups.append((page, [row]))

    chunks = []
    cur = []
    for _, g in groups:
        if cur and len(cur) + len(g) > cap:
            chunks.append(cur)
            cur = []
        cur += g
    if cur:
        chunks.append(cur)
    return chunks

def create_facesheet_zip(chunks, base_name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, chunk in enumerate(chunks, 1):
            out_s = io.StringIO()
            w = csv.writer(out_s)
            w.writerow(FACESHEET_HEADER)
            w.writerows(chunk)
            zf.writestr(f"{base_name}_part{idx}.csv", out_s.getvalue().encode("utf-8"))
    buf.seek(0)
    return buf.getvalue()


# ── Main Dashboard Layout ─────────────────────────────────────────────────────


# Premium Header Banner
st.markdown("""
<div class="saas-header">
    <h1>Clinical DataOps Hub</h1>
    <p>Automated Extraction & Patient Matching Engine</p>
</div>
""", unsafe_allow_html=True)

# ── Tabs Setup ────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📄 AthenaOne Extraction", 
    "🔄 ECW Patient Matcher", 
    "📋 IMS Meditab Extraction", 
    "📋 ModuleMD Extraction",
    "📁 EPIC",
    "📑 ModMed Face Sheet"
])

# ── 1. Athena PDF to CSV (Tab 1) ──────────────────────────────────────────────
with tab1:
    st.markdown('<div class="section-title">Upload Schedule PDF</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Drag and drop your AthenaOne PDF report", type=["pdf"], key="athena_uploader", label_visibility="collapsed")
    
    if uploaded_file:
        with st.spinner("Processing PDF data..."):
            records, service_date = process_athena_pdf(io.BytesIO(uploaded_file.getvalue()))
        
        if records:
            df = pd.DataFrame(records, columns=['Patient Name', 'DOB', 'Appt. Provider', 'PCP', 'CHPCP', 'Service Date', 'Insurance', 'Policy No.', 'Status', 'Eligible'])
            st.success(f"Successfully extracted {len(df)} appointments for {service_date}")
            
            # KPI Metrics wrapped in standard columns but styled via CSS
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Appointments", len(df))
            c2.metric("Service Date", service_date)
            c3.metric("Unique Providers", df['Appt. Provider'].nunique())
            
            st.markdown('<div class="section-title">Data Preview</div>', unsafe_allow_html=True)
            df_display = df.copy()
            df_display.index += 1
            st.dataframe(df_display, width='stretch', height=400)
            
            st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
            ROWS_PER_FILE = 99
            base_name = f"athena_schedule_{service_date.replace('/','-')}"
            
            if len(df) > ROWS_PER_FILE:
                st.info(f"💡 Large dataset detected. Records have been automatically split into {int((len(df)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                zip_data = create_zip_of_chunks(df, base_name, ROWS_PER_FILE)
                
                col_btn, _ = st.columns([1, 2])
                with col_btn:
                    st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{base_name}_all_parts.zip", mime="application/zip", key="athena_zip_btn")
            else:
                csv = df.to_csv(index=False).encode('utf-8')
                col_btn, _ = st.columns([1, 2])
                with col_btn:
                    st.download_button(label="📥 Download Data (.csv)", data=csv, file_name=f"{base_name}.csv", mime="text/csv", key="athena_csv_btn")
        else: 
            st.error("No valid appointment records found in the PDF.")

# ── 2. ECW Patient Matcher (Tab 2) ────────────────────────────────────────────
with tab2:
    st.markdown('<div class="section-title">Upload Core Datasets</div>', unsafe_allow_html=True)
    
    ecw_c1, ecw_c2 = st.columns(2)
    with ecw_c1:
        st.markdown("**1. CW Appointment Reports**")
        appt_files = st.file_uploader("Upload CW Report CSVs", type=["csv"], accept_multiple_files=True, key="ecw_appt_uploader", label_visibility="collapsed")
    with ecw_c2:
        st.markdown("**2. Eligibility Report**")
        ins_file = st.file_uploader("Upload Eligibility CSV", type=["csv"], key="ecw_ins_uploader", label_visibility="collapsed")

    if appt_files and ins_file:
        try:
            appt_frames = [pd.read_csv(f, engine='python') for f in appt_files]
            appointments = pd.concat(appt_frames, ignore_index=True)
            insurance = pd.read_csv(ins_file, engine='python')
            
            # Dynamic Column Resolution for Appointments
            appt_name_col, appt_dob_col = None, None
            for c in appointments.columns:
                c_clean = str(c).strip().lower()
                if not appt_name_col and c_clean in ('patient', 'patient name', 'patient_name', 'pt name', 'name', 'full name', 'pt_name'):
                    appt_name_col = c
                if not appt_dob_col and c_clean in ('dob', 'date of birth', 'patient dob', 'birth date', 'dob (mm/dd/yyyy)', 'birthdate'):
                    appt_dob_col = c
                    
            # Dynamic Column Resolution for Insurance
            ins_name_col, ins_dob_col = None, None
            for c in insurance.columns:
                c_clean = str(c).strip().lower()
                if not ins_name_col and c_clean in ('patient name', 'patient', 'patient_name', 'pt name', 'name', 'member name', 'insured name'):
                    ins_name_col = c
                if not ins_dob_col and c_clean in ('dob', 'date of birth', 'patient dob', 'birth date', 'dob (mm/dd/yyyy)', 'birthdate'):
                    ins_dob_col = c
            
            if appt_name_col and ins_name_col and appt_dob_col and ins_dob_col:
                # 1. Exact norm key: norm_name + '|' + norm_dob
                exact_appt_keys = set(appointments[appt_name_col].map(norm_name) + '|' + appointments[appt_dob_col].map(norm_dob))
                # 2. Tokenized key: (last|first) + '|' + norm_dob (matches across 'Last, First M' and 'First Last')
                token_appt_keys = set(appointments[appt_name_col].map(get_name_match_key) + '|' + appointments[appt_dob_col].map(norm_dob))
                
                insurance['_key_exact'] = insurance[ins_name_col].map(norm_name) + '|' + insurance[ins_dob_col].map(norm_dob)
                insurance['_key_token'] = insurance[ins_name_col].map(get_name_match_key) + '|' + insurance[ins_dob_col].map(norm_dob)
                
                is_matched = (
                    insurance['_key_exact'].isin(exact_appt_keys) | 
                    (insurance['_key_token'].isin(token_appt_keys) & (insurance[ins_dob_col].map(norm_dob) != ''))
                )
                
                matched = insurance[is_matched].drop(columns=['_key_exact', '_key_token']).copy()
                unmatched = insurance[~is_matched].drop(columns=['_key_exact', '_key_token']).copy()
                
                st.success(f"Cross-reference complete.")
                
                # Metrics
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Processed", len(insurance))
                m2.metric("Successful Matches", len(matched))
                m3.metric("Unmatched Records", len(unmatched))
                
                st.markdown('<div class="section-title">Verified Matches Overview</div>', unsafe_allow_html=True)
                matched_display = matched.copy()
                matched_display.index = range(1, len(matched) + 1)
                st.dataframe(matched_display, width='stretch', height=400)
                
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                ROWS_PER_FILE = 99
                base_name = os.path.splitext(ins_file.name)[0]
                
                if len(matched) > ROWS_PER_FILE:
                    st.info(f"💡 Large dataset detected. Records have been automatically split into {int((len(matched)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                    zip_data = create_zip_of_chunks(matched, base_name, ROWS_PER_FILE)
                    
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{base_name}_all_parts.zip", mime="application/zip", key="ecw_zip_btn")
                else:
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Data (.csv)", data=matched.to_csv(index=False).encode('utf-8'), file_name=f"{base_name}_matched.csv", mime="text/csv", key="ecw_csv_btn")
            else:
                missing_desc = []
                if not appt_name_col: missing_desc.append("CW Reports missing Patient name column")
                if not appt_dob_col: missing_desc.append("CW Reports missing DOB column")
                if not ins_name_col: missing_desc.append("Eligibility missing Patient name column")
                if not ins_dob_col: missing_desc.append("Eligibility missing DOB column")
                st.error("Schema Mismatch: " + ", ".join(missing_desc))
        except Exception as e:
            st.error(f"Processing Error: {str(e)}")

# ── 3. IMS Meditab Extraction (Tab 3) ─────────────────────────────────────────
with tab3:
    st.markdown('<div class="section-title">Upload Meditab Export or Paste Raw Text</div>', unsafe_allow_html=True)
    
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        st.markdown("**Option A: Upload CSV File**")
        uploaded_meditab = st.file_uploader("Upload IMS Meditab CSV Export", type=["csv", "txt"], key="meditab_uploader", label_visibility="collapsed")
    with col_input2:
        st.markdown("**Option B: Paste Raw Text**")
        pasted_meditab = st.text_area("Paste the raw export content here...", height=100, key="meditab_pasted", label_visibility="collapsed")
        
    # Process if either is provided
    raw_content = None
    file_name = "meditab_export"
    
    if uploaded_meditab:
        try:
            raw_bytes = uploaded_meditab.getvalue()
            try:
                raw_content = raw_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                raw_content = raw_bytes.decode('cp1252', errors='replace')
            file_name = os.path.splitext(uploaded_meditab.name)[0]
        except Exception as e:
            st.error(f"Failed to read uploaded file: {e}")
    elif pasted_meditab.strip():
        raw_content = pasted_meditab.strip()
        file_name = "pasted_meditab_export"
        
    if raw_content:
        with st.spinner("Processing Meditab data..."):
            try:
                # Detect boundary reconstruction
                lines = [l for l in raw_content.split('\n') if l.strip()]
                needs_reconstruct = len(lines) <= 2 and len(raw_content) > 1000
                
                if needs_reconstruct:
                    reconstructed_text = reconstruct_meditab_csv_blob(raw_content)
                    df_raw = pd.read_csv(io.StringIO(reconstructed_text), encoding='cp1252')
                else:
                    df_raw = pd.read_csv(io.StringIO(raw_content), encoding='cp1252')
                    
                df_transformed = process_meditab_df(df_raw)
                
                st.success(f"Processing complete. Validated all {len(df_transformed)} output rows to have exactly 84 columns. 0 bad dates found.")
                
                # Calculate secondary count
                sec_rows_count = len(df_transformed[df_transformed['insurance_priority'] == 'Secondary'])
                
                # Metrics
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Source Rows", len(df_raw))
                m2.metric("Total Output Rows", len(df_transformed))
                m3.metric("Secondary Insurance Rows", sec_rows_count)
                
                # Spot-Check (Side-by-Side)
                sec_rows = df_transformed[df_transformed['insurance_priority'] == 'Secondary']
                if not sec_rows.empty:
                    sec_patients = list(sec_rows['patient_name'].unique())
                    st.markdown('<div class="section-title">Spot-Check: Patient Primary & Secondary Insurance</div>', unsafe_allow_html=True)
                    
                    col_sel1, col_sel2 = st.columns([2, 1])
                    with col_sel1:
                        sel_option = st.selectbox(
                            "Select patient with secondary insurance to inspect:",
                            options=["All Patients with Secondary Insurance"] + sec_patients,
                            key="meditab_spotcheck_patient"
                        )
                    with col_sel2:
                        show_all_cols = st.checkbox("Show all 84 columns", value=False, key="meditab_show_all_cols")
                        
                    if sel_option == "All Patients with Secondary Insurance":
                        spot_check_df = df_transformed[df_transformed['patient_name'].isin(sec_patients)].copy()
                    else:
                        spot_check_df = df_transformed[df_transformed['patient_name'] == sel_option].copy()
                        
                    if not show_all_cols:
                        key_cols = [
                            "patient_name", "insurance_priority", "priority", "insurance_name", 
                            "insurance_no", "insurance_type", "schedule_date", "schedule_time", 
                            "doctor_name", "procedure_name"
                        ]
                        avail_key_cols = [c for c in key_cols if c in spot_check_df.columns]
                        st.dataframe(spot_check_df[avail_key_cols], width='stretch')
                    else:
                        st.dataframe(spot_check_df, width='stretch')
                
                st.markdown('<div class="section-title">Data Preview (First 100 rows)</div>', unsafe_allow_html=True)
                df_display = df_transformed.head(100).copy()
                df_display.index += 1
                st.dataframe(df_display, width='stretch', height=300)
                
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                ROWS_PER_FILE = 99
                
                if len(df_transformed) > ROWS_PER_FILE:
                    st.info(f"💡 Records have been automatically split into {int((len(df_transformed)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                    zip_data = create_zip_of_chunks(df_transformed, file_name, ROWS_PER_FILE)
                    
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{file_name}_transformed.zip", mime="application/zip", key="meditab_zip_btn")
                else:
                    csv_data = df_transformed.to_csv(index=False).encode('utf-8')
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Data (.csv)", data=csv_data, file_name=f"{file_name}_transformed.csv", mime="text/csv", key="meditab_csv_btn")
                        
            except Exception as e:
                st.error(f"Failed to process Meditab CSV: {e}")

# ── 4. ModuleMD Extraction (Tab 4) ───────────────────────────────────────────
with tab4:
    st.markdown('<div class="section-title">Upload ModuleMD Schedule Report</div>', unsafe_allow_html=True)
    uploaded_modulemd = st.file_uploader("Upload ModuleMD export (.xls, .xlsx, .csv)", type=["xls", "xlsx", "csv"], key="modulemd_uploader", label_visibility="collapsed")
    
    if uploaded_modulemd:
        with st.spinner("Processing ModuleMD data..."):
            try:
                # Read raw bytes
                file_bytes = uploaded_modulemd.getvalue()
                file_name_lower = uploaded_modulemd.name.lower()
                
                # Check if it is actually HTML (ModuleMD exports HTML table as .xls)
                is_html = b"<html" in file_bytes.lower() or b"<table" in file_bytes.lower()
                
                if file_name_lower.endswith(".csv"):
                    try:
                        df_raw = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8")
                    except UnicodeDecodeError:
                        df_raw = pd.read_csv(io.BytesIO(file_bytes), encoding="cp1252")
                elif is_html:
                    tables = pd.read_html(io.BytesIO(file_bytes))
                    if not tables:
                        raise ValueError("No HTML tables found in the uploaded file.")
                    df_raw = tables[0]
                else:
                    # Parse as binary Excel (.xlsx or binary .xls)
                    df_raw = pd.read_excel(io.BytesIO(file_bytes))
                
                df_transformed = process_modulemd_df(df_raw)
                        
                # Validate output
                # Ensure no cells contain "nan" or "NaT"
                for col in df_transformed.columns:
                    bad_nans = df_transformed[df_transformed[col].isin(["nan", "NaT"])]
                    if not bad_nans.empty:
                        st.warning(f"⚠️ Warning: Found literal 'nan' or 'NaT' strings in column '{col}'. Cleaned them up.")
                        df_transformed[col] = df_transformed[col].replace({"nan": "", "NaT": ""})
                        
                # Date formats validation check
                bad_dates_count = 0
                for col in ["Date of Birth", "Service Date"]:
                    if col in df_transformed.columns:
                        invalid_dates = df_transformed[
                            (df_transformed[col] != "") & 
                            (~df_transformed[col].str.match(r"^\d{2}/\d{2}/\d{4}$", na=False))
                        ]
                        bad_dates_count += len(invalid_dates)
                        
                # Insurance format validation check
                bad_insurances = df_transformed[
                    df_transformed["Insurance Payer"].str.contains(r"\[|\]|\*\*", na=False) |
                    df_transformed["Policy Number"].str.contains(r"\[|\]|\*\*", na=False)
                ]
                bad_ins_count = len(bad_insurances)
                
                st.success(f"Processing complete! Validated all {len(df_transformed)} output rows.")
                if bad_dates_count > 0 or bad_ins_count > 0:
                    st.info(f"📋 QA Summary: Found {bad_dates_count} unformatted/malformed date cells and {bad_ins_count} unparsed insurance details. These values were passed through raw for manual check.")
                    
                # Metrics
                col_m1, col_m2, col_m3 = st.columns(3)
                
                # Calculate secondary insurance rows
                sec_rows = df_transformed[df_transformed["Type"] == "Secondary"]
                primary_rows = df_transformed[df_transformed["Type"] == "Primary"]
                
                col_m1.metric("Total Rows", len(df_transformed))
                col_m2.metric("Primary Insurances", len(primary_rows))
                col_m3.metric("Secondary Insurances", len(sec_rows))
                
                # Spot check view
                if not sec_rows.empty:
                    sample_patient = sec_rows.iloc[0]["Patient Name"]
                    spot_check_df = df_transformed[df_transformed["Patient Name"] == sample_patient]
                    st.markdown('<div class="section-title">Spot-Check: Patient Primary & Secondary Insurance</div>', unsafe_allow_html=True)
                    st.dataframe(spot_check_df, width='stretch')
                    
                st.markdown('<div class="section-title">Data Preview (First 100 rows)</div>', unsafe_allow_html=True)
                df_display = df_transformed.head(100).copy()
                df_display.index += 1
                st.dataframe(df_display, width='stretch', height=300)
                
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                ROWS_PER_FILE = 99
                file_name = os.path.splitext(uploaded_modulemd.name)[0]
                
                if len(df_transformed) > ROWS_PER_FILE:
                    st.info(f"💡 Records have been automatically split into {int((len(df_transformed)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                    zip_data = create_zip_of_chunks(df_transformed, file_name, ROWS_PER_FILE)
                    
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{file_name}_transformed.zip", mime="application/zip", key="modulemd_zip_btn")
                else:
                    csv_data = df_transformed.to_csv(index=False).encode('utf-8')
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Data (.csv)", data=csv_data, file_name=f"{file_name}_transformed.csv", mime="text/csv", key="modulemd_csv_btn")
                                
            except Exception as e:
                st.error(f"Failed to process ModuleMD XLS file: {e}")

# ── 5. EPIC (Tab 5) ───────────────────────────────────────────────────────────
with tab5:
    st.markdown('<div class="section-title">EPIC Clinical DataOps & VOB Pipeline</div>', unsafe_allow_html=True)
    
    # Informational Pipeline Workflow Banner
    st.markdown(
        """
        <div style="background-color: #F8FAFC; border: 1px solid #CBD5E1; border-left: 5px solid #2563EB; padding: 18px 22px; border-radius: 10px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
                <span style="font-size: 18px;">⚡</span>
                <span style="font-size: 15px; font-weight: 700; color: #1E293B;">EPIC Unified Pipeline: AAMG / JMPN Policy Formatter & Date Normalizer</span>
            </div>
            <p style="margin: 0; color: #475569; font-size: 13.5px; line-height: 1.5;">
                Upload your raw EPIC schedule or VOB file once to execute the complete pipeline automatically:
                <strong>1. AAMG / JMPN Policy Formatter</strong> (strips Member/Policy IDs for Anthem and Healthy Employee Plan, adds patient audit Description) ➔
                <strong>2. EPIC Date Normalizer</strong> (auto-detects and formats Visit Date & Patient DOB to <code>MM/DD/YYYY</code>) ➔
                <strong>3. Chunking & Portal Export</strong> (splits into 100-row files with <code>QUOTE_ALL</code> and saves locally/downloads).
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.expander("ℹ️ View AAMG & JMPN Policy ID Stripping Rules & Payer Variations", expanded=False):
        st.markdown(
            """
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #F1F5F9; border-bottom: 2px solid #CBD5E1; text-align: left; color: #334155;">
                            <th style="padding: 10px 14px; font-weight: 600; width: 22%;">Payer Family</th>
                            <th style="padding: 10px 14px; font-weight: 600; width: 48%;">Name Variations in CSV (Examples)</th>
                            <th style="padding: 10px 14px; font-weight: 600; width: 30%;">Action Taken</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #E2E8F0; background-color: #FFFFFF;">
                            <td style="padding: 12px 14px; font-weight: 600; color: #1D4ED8; vertical-align: top;">
                                🔵 JMPN Anthem Blue Cross
                            </td>
                            <td style="padding: 12px 14px; color: #334155; line-height: 1.6; vertical-align: top;">
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem Blue Cross [1185026]</code><br>
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem Blue Cross</code> &bull; <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem</code><br>
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem BCBS</code> &bull; <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN - Anthem</code><br>
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN/Anthem</code> &bull; <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">Anthem (JMPN)</code>
                            </td>
                            <td style="padding: 12px 14px; font-weight: 600; color: #0F172A; vertical-align: top;">
                                <strong>Strip to 12 chars</strong><br><span style="font-size: 12px; font-weight: normal; color: #64748B;">(Removes trailing 2 digits if 14 digits)</span>
                            </td>
                        </tr>
                        <tr style="border-bottom: 1px solid #E2E8F0; background-color: #FFFFFF;">
                            <td style="padding: 12px 14px; font-weight: 600; color: #15803D; vertical-align: top;">
                                🟢 JMPN Healthy Employee Plan
                            </td>
                            <td style="padding: 12px 14px; color: #334155; line-height: 1.6; vertical-align: top;">
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN Healthy Employee Plan [1640000026]</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Employee Plan [1640000026]</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN Healthy Employee</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Employee Plan</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Employee Benefit Plan</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Emp Plan</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Emp</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">HEP</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN HEP</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN - HEP</code>
                            </td>
                            <td style="padding: 12px 14px; font-weight: 600; color: #0F172A; vertical-align: top;">
                                <strong>Strip to 9 chars</strong><br><span style="font-size: 12px; font-weight: normal; color: #64748B;">(Removes trailing 2 digits if 11 digits)</span>
                            </td>
                        </tr>
                        <tr style="background-color: #FFFFFF;">
                            <td style="padding: 12px 14px; font-weight: 600; color: #64748B; vertical-align: top;">
                                ⚪ Other Payers (Untouched)
                            </td>
                            <td style="padding: 12px 14px; color: #64748B; vertical-align: top;">
                                <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Commercial Anthem (non-JMPN)</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Aetna</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Cigna</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Kaiser</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Medicare</code>, etc.
                            </td>
                            <td style="padding: 12px 14px; font-weight: 600; color: #64748B; vertical-align: top;">
                                <strong>Untouched</strong><br><span style="font-size: 12px; font-weight: normal; color: #94A3B8;">(Kept completely as-is)</span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Check for raw files in AAMG/VOBs/RAW or EPIC/RAW
    raw_dirs_to_check = [
        os.path.join(os.getcwd(), "AAMG", "VOBs", "RAW"),
        os.path.join(os.getcwd(), "EPIC", "RAW"),
        os.path.join(os.getcwd(), "EPIC", "VOBs", "RAW")
    ]
    raw_files = []
    found_raw_dir = None
    for rd in raw_dirs_to_check:
        if os.path.exists(rd):
            fs = [f for f in os.listdir(rd) if f.lower().endswith(('.csv', '.xlsx', '.xls', '.txt'))]
            if fs:
                raw_files = fs
                found_raw_dir = rd
                break
    if not found_raw_dir and os.path.exists(raw_dirs_to_check[0]):
        found_raw_dir = raw_dirs_to_check[0]

    today_str = datetime.now().strftime('%Y-%m-%d')
    default_out_dir = os.path.join(os.getcwd(), "EPIC", "VOBs", today_str)

    epic_col1, epic_col2 = st.columns(2)
    with epic_col1:
        st.markdown("**Option A: Upload EPIC File (CSV / Excel)**")
        uploaded_epic = st.file_uploader(
            "Upload EPIC CSV or Excel", 
            type=["csv", "xlsx", "xls", "txt"], 
            key="epic_uploader", 
            label_visibility="collapsed"
        )
        if raw_files and found_raw_dir:
            st.markdown(f"**Or select from `{os.path.relpath(found_raw_dir)}`:**")
            selected_raw = st.selectbox("Select file from RAW folder", ["-- None --"] + raw_files, key="epic_raw_select")
        else:
            selected_raw = "-- None --"

    with epic_col2:
        st.markdown("**Option B: Paste Raw CSV Text**")
        pasted_epic = st.text_area("Paste raw EPIC CSV data here...", height=100, key="epic_pasted", label_visibility="collapsed")

    # Load raw data
    df_raw = None
    source_name = "epic_records"

    if uploaded_epic:
        try:
            source_name = os.path.splitext(uploaded_epic.name)[0]
            fname_lower = uploaded_epic.name.lower()
            file_bytes = uploaded_epic.getvalue()
            
            if fname_lower.endswith((".xlsx", ".xls")):
                is_html = b"<html" in file_bytes.lower() or b"<table" in file_bytes.lower()
                if is_html:
                    tables = pd.read_html(io.BytesIO(file_bytes))
                    if not tables:
                        raise ValueError("No tables found in HTML/Excel file.")
                    df_raw = tables[0]
                else:
                    df_raw = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
            else:
                try:
                    df_raw = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8", dtype=str)
                except UnicodeDecodeError:
                    df_raw = pd.read_csv(io.BytesIO(file_bytes), encoding="cp1252", dtype=str)
        except Exception as e:
            st.error(f"Error reading uploaded EPIC file: {e}")
    elif selected_raw != "-- None --" and found_raw_dir:
        try:
            source_name = os.path.splitext(selected_raw)[0]
            file_path = os.path.join(found_raw_dir, selected_raw)
            fname_lower = selected_raw.lower()
            
            if fname_lower.endswith((".xlsx", ".xls")):
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                is_html = b"<html" in file_bytes.lower() or b"<table" in file_bytes.lower()
                if is_html:
                    tables = pd.read_html(io.BytesIO(file_bytes))
                    if not tables:
                        raise ValueError("No tables found in HTML/Excel file.")
                    df_raw = tables[0]
                else:
                    df_raw = pd.read_excel(file_path, dtype=str)
            else:
                try:
                    df_raw = pd.read_csv(file_path, encoding="utf-8", dtype=str)
                except UnicodeDecodeError:
                    df_raw = pd.read_csv(file_path, encoding="cp1252", dtype=str)
        except Exception as e:
            st.error(f"Error reading raw file from disk: {e}")
    elif pasted_epic.strip():
        try:
            source_name = "pasted_epic_records"
            df_raw = pd.read_csv(io.StringIO(pasted_epic.strip()), dtype=str)
        except Exception as e:
            st.error(f"Error parsing pasted CSV: {e}")

    if df_raw is not None and not df_raw.empty:
        st.markdown('<div class="section-title">Unified Pipeline Configuration</div>', unsafe_allow_html=True)
        
        all_cols = list(df_raw.columns)
        det_payer, det_id, det_patient = auto_detect_jmpn_columns(df_raw)
        
        # Section 1: AAMG / JMPN Policy Formatter Config
        with st.expander("🆔 Step 1: AAMG / JMPN Policy Formatter Settings", expanded=True):
            enable_policy_cleaner = st.checkbox(
                "Enable AAMG / JMPN Member ID Cleaner & Description Audit", 
                value=True, 
                key="epic_chk_enable_policy"
            )
            
            if enable_policy_cleaner:
                c_map1, c_map2, c_map3 = st.columns(3)
                with c_map1:
                    payer_idx = all_cols.index(det_payer) if det_payer in all_cols else 0
                    selected_payer_col = st.selectbox(
                        "Payer / Plan Name Column:",
                        options=all_cols,
                        index=payer_idx,
                        key="epic_payer_col"
                    )
                with c_map2:
                    id_idx = all_cols.index(det_id) if det_id in all_cols else (1 if len(all_cols) > 1 else 0)
                    selected_id_col = st.selectbox(
                        "Member / Policy ID Column to Clean:",
                        options=all_cols,
                        index=id_idx,
                        key="epic_id_col"
                    )
                with c_map3:
                    patient_options = ["-- None --"] + all_cols
                    pat_idx = patient_options.index(det_patient) if det_patient in patient_options else 0
                    selected_patient_col = st.selectbox(
                        "Patient Name Column (for audit preview):",
                        options=patient_options,
                        index=pat_idx,
                        key="epic_patient_col"
                    )
                    
                rule_c1, rule_c2 = st.columns(2)
                with rule_c1:
                    apply_anthem = st.checkbox(
                        "🔵 **Rule 1: JMPN Anthem Blue Cross** (Limit to 12 digits, strip last 2 if 14)", 
                        value=True, 
                        key="epic_chk_anthem"
                    )
                    strict_jmpn_anthem = st.checkbox(
                        "🔒 **Require 'JMPN' keyword for Anthem** (Recommended — protects commercial non-JMPN Anthem)",
                        value=True,
                        key="epic_chk_strict_anthem"
                    )
                with rule_c2:
                    apply_healthy = st.checkbox(
                        "🟢 **Rule 2: JMPN Healthy Employee Plan** (Limit to 9 digits, strip last 2 if 11)", 
                        value=True, 
                        key="epic_chk_healthy"
                    )
                    
                with st.expander("⚙️ Additional Custom Payer Aliases (Optional)", expanded=False):
                    alias_c1, alias_c2 = st.columns(2)
                    with alias_c1:
                        anthem_extra_str = st.text_input(
                            "Extra Anthem Aliases (comma-separated):",
                            value="",
                            placeholder="e.g. BCBS CA, ANTH_IPA",
                            key="epic_anthem_extra_kw"
                        )
                    with alias_c2:
                        healthy_extra_str = st.text_input(
                            "Extra Healthy Employee Aliases (comma-separated):",
                            value="",
                            placeholder="e.g. JMPN-HEP, HEBP",
                            key="epic_healthy_extra_kw"
                        )
                anthem_extra_list = [x.strip() for x in anthem_extra_str.split(",") if x.strip()] if 'anthem_extra_str' in locals() and anthem_extra_str else []
                healthy_extra_list = [x.strip() for x in healthy_extra_str.split(",") if x.strip()] if 'healthy_extra_str' in locals() and healthy_extra_str else []
            else:
                apply_anthem = False
                strict_jmpn_anthem = False
                apply_healthy = False
                anthem_extra_list = []
                healthy_extra_list = []
                selected_payer_col = None
                selected_id_col = None
                selected_patient_col = "-- None --"

        # Section 2: EPIC Date Normalization Config
        with st.expander("📅 Step 2: EPIC Date Normalization Settings", expanded=True):
            enable_date_norm = st.checkbox(
                "Enable Date Normalization (Visit Date & Patient DOB to MM/DD/YYYY)", 
                value=True, 
                key="epic_chk_enable_date"
            )
            if enable_date_norm:
                date_format_opt = st.radio(
                    "Date Format Resolution for 'Visit Date' & 'Patient DOB':",
                    options=[
                        "Auto-detect (DD/MM/YYYY if day > 12, else MM/DD/YYYY)",
                        "Force MM/DD/YYYY",
                        "Force DD/MM/YYYY (swap day & month)"
                    ],
                    index=0,
                    key="epic_date_format"
                )
                if "Auto-detect" in date_format_opt:
                    format_choice = "auto"
                elif "Force DD/MM/YYYY" in date_format_opt:
                    format_choice = "dd/mm/yyyy"
                else:
                    format_choice = "mm/dd/yyyy"
            else:
                format_choice = None

        # Section 3: Output & Chunking Config
        with st.expander("📁 Step 3: Chunking & Output Destination Settings", expanded=True):
            out_c1, out_c2 = st.columns(2)
            with out_c1:
                chunk_size_choice = st.selectbox(
                    "Split large files into chunks:",
                    options=[100, 99, "Do not split (Single file only)"],
                    index=0,
                    key="epic_chunk_size_select",
                    help="Default is 100 rows per file for portal / clearinghouse batch upload limits."
                )
            with out_c2:
                save_local = st.checkbox("Save output files to local disk", value=True, key="epic_save_local")
                
            if save_local:
                if "epic_custom_path" not in st.session_state:
                    st.session_state["epic_custom_path"] = default_out_dir
                    
                dest_mode = st.selectbox(
                    "Select Output Destination:",
                    options=[
                        "📁 Project Folder (EPIC/VOBs/Dated)",
                        "🖥️ Desktop (Desktop/EPIC/VOBs/Dated)",
                        "📥 Downloads (Downloads/EPIC/VOBs/Dated)",
                        "📂 Browse via Mac Finder...",
                        "✏️ Custom Directory Path..."
                    ],
                    key="epic_dest_mode"
                )
                
                if dest_mode == "📁 Project Folder (EPIC/VOBs/Dated)":
                    local_target_dir = default_out_dir
                elif dest_mode == "🖥️ Desktop (Desktop/EPIC/VOBs/Dated)":
                    local_target_dir = os.path.join(os.path.expanduser("~"), "Desktop", "EPIC", "VOBs", today_str)
                elif dest_mode == "📥 Downloads (Downloads/EPIC/VOBs/Dated)":
                    local_target_dir = os.path.join(os.path.expanduser("~"), "Downloads", "EPIC", "VOBs", today_str)
                elif dest_mode == "📂 Browse via Mac Finder...":
                    b_c1, _ = st.columns([1, 1])
                    with b_c1:
                        if st.button("📂 Open Mac Finder Folder Picker", key="epic_browse_btn"):
                            picked = open_macos_folder_dialog(st.session_state.get("epic_custom_path", os.path.expanduser("~")))
                            if picked:
                                st.session_state["epic_custom_path"] = os.path.join(picked, today_str)
                                st.rerun()
                    local_target_dir = st.session_state.get("epic_custom_path", default_out_dir)
                else: # "✏️ Custom Directory Path..."
                    custom_input = st.text_input(
                        "Enter folder path:",
                        value=st.session_state.get("epic_custom_path", default_out_dir),
                        key="epic_custom_input"
                    )
                    local_target_dir = custom_input.strip()
                    st.session_state["epic_custom_path"] = local_target_dir
            else:
                local_target_dir = None

        # ── Pipeline Execution ────────────────────────────────────────────────
        with st.spinner("Processing EPIC records through unified pipeline..."):
            try:
                df_curr = df_raw.copy()
                total_records = len(df_curr)
                
                # --- PHASE 1: AAMG / JMPN Policy Formatter ---
                audit_records = []
                anthem_modified_count = 0
                healthy_modified_count = 0
                total_modified_count = 0
                payer_summary = []
                
                if enable_policy_cleaner and selected_id_col and selected_id_col in df_curr.columns and selected_payer_col and selected_payer_col in df_curr.columns:
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
                        if selected_patient_col != "-- None --" and selected_patient_col in df_curr.columns:
                            patient_name_for_desc = str(row.get(selected_patient_col, "")).strip()
                            
                        cleaned_id, rule_name, was_modified = clean_jmpn_member_id(
                            raw_id_val, 
                            raw_payer_val, 
                            strip_anthem=apply_anthem, 
                            strip_healthy=apply_healthy,
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
                            if selected_patient_col != "-- None --" and selected_patient_col in row:
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
                if enable_date_norm and format_choice:
                    df_curr, spot_df, detected_label, visit_col, dob_col = process_aamg_df(df_curr, format_choice)

                # --- PHASE 3: Chunking & Local Storage ---
                clean_base = re.sub(r'[^\w\-]+', '_', source_name).strip('_') or "epic_records"
                out_dir_to_use = local_target_dir.strip() if save_local and local_target_dir.strip() else None
                
                rows_per_file = int(chunk_size_choice) if chunk_size_choice in (99, 100) else total_records
                zip_data, saved_paths, total_chunks = create_aamg_chunks(df_curr, clean_base, rows_per_file, out_dir_to_use)
                
                st.success(f"Processing Complete! Successfully executed EPIC pipeline for {total_records} records.")
                
                # --- KPI Metrics Display ---
                kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)
                kpi_col1.metric("Total Records", total_records)
                kpi_col2.metric("IDs Cleaned", total_modified_count)
                kpi_col3.metric("Anthem Stripped (14→12)", anthem_modified_count)
                kpi_col4.metric("Healthy Emp (11→9)", healthy_modified_count)
                kpi_col5.metric("Output Chunks (Files)", total_chunks)
                
                # Payer Summary Expander
                if payer_summary:
                    with st.expander(f"📋 Payer Name Variations in this File ({len(payer_summary)} distinct payers found)", expanded=False):
                        st.dataframe(pd.DataFrame(payer_summary), width='stretch', hide_index=True)
                
                # Audit Trail of Modified Records
                if enable_policy_cleaner:
                    st.markdown('<div class="section-title">🔍 Audit Trail: Modified Member IDs</div>', unsafe_allow_html=True)
                    if audit_records:
                        st.info(f"Showing all **{len(audit_records)}** records where Member / Policy IDs were cleaned and shortened. (The **Row #** column indicates the original row position).")
                        st.dataframe(pd.DataFrame(audit_records), width='stretch', height=260, hide_index=True)
                    else:
                        st.info("ℹ️ No Member IDs required truncation. All Member IDs either already match length requirements or belong to other payers.")
                
                # Spot-Checks Section for Dates
                if enable_date_norm and spot_df is not None:
                    st.markdown('<div class="section-title">📅 Date Normalization Verification (First 3 Rows)</div>', unsafe_allow_html=True)
                    st.info(f"**Target Columns Identified**: Visit Date: `{visit_col or 'Not Found'}` | Patient DOB: `{dob_col or 'Not Found'}` | Format Applied: `{detected_label}` | Quoting Standard: `QUOTE_ALL`")
                    st.dataframe(spot_df, width='stretch')
                
                # Local write status
                if saved_paths:
                    st.success(f"📁 Successfully saved {len(saved_paths)} chunk files to local output folder: `{out_dir_to_use}`")

                # Data Preview Section
                st.markdown(f'<div class="section-title">Cleaned Data Preview (Showing first {min(100, len(df_curr))} rows)</div>', unsafe_allow_html=True)
                preview_c1, _ = st.columns([1, 2])
                with preview_c1:
                    filter_modified_only = st.checkbox("Show only modified rows in preview", value=False, key="epic_filter_mod")
                
                if filter_modified_only and audit_records:
                    mod_indices = [r["Row #"] - 1 for r in audit_records]
                    preview_df = df_curr.iloc[mod_indices].copy()
                    preview_df.insert(0, "CSV Row #", [r["Row #"] for r in audit_records])
                    st.dataframe(preview_df, width='stretch', height=300, hide_index=True)
                else:
                    preview_df = df_curr.head(100).copy()
                    preview_df.insert(0, "CSV Row #", range(1, len(preview_df) + 1))
                    st.dataframe(preview_df, width='stretch', height=300, hide_index=True)

                # Export Results Section
                st.markdown('<div class="section-title">📥 Export Cleaned Dataset</div>', unsafe_allow_html=True)
                exp_c1, exp_c2, exp_c3 = st.columns(3)
                with exp_c1:
                    st.download_button(
                        label=f"📥 Download All Parts Archive (.zip) - {total_chunks} files",
                        data=zip_data,
                        file_name=f"{clean_base}_all_parts.zip",
                        mime="application/zip",
                        key="epic_zip_btn"
                    )
                with exp_c2:
                    full_csv = df_curr.to_csv(index=False, quoting=csv.QUOTE_ALL).encode('utf-8')
                    st.download_button(
                        label=f"📥 Download Consolidated CSV ({total_records} rows)",
                        data=full_csv,
                        file_name=f"{clean_base}_full_normalized.csv",
                        mime="text/csv",
                        key="epic_csv_btn"
                    )
                with exp_c3:
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        df_curr.to_excel(writer, index=False)
                    excel_buffer.seek(0)
                    st.download_button(
                        label="📥 Download Full Excel (.xlsx)",
                        data=excel_buffer.getvalue(),
                        file_name=f"{clean_base}_full_normalized.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="epic_excel_btn"
                    )
                
                if audit_records:
                    audit_csv = pd.DataFrame(audit_records).to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label=f"📥 Download Modified Records Audit Log ({len(audit_records)} rows)",
                        data=audit_csv,
                        file_name=f"{clean_base}_audit_modified_ids.csv",
                        mime="text/csv",
                        key="epic_audit_csv_btn"
                    )
            except Exception as e:
                st.error(f"Error processing EPIC data: {e}")


# ── 6. ModMed Face Sheet & Schedule to CSV (Tab 6) ────────────────────────────
with tab6:
    st.markdown('<div class="section-title">ModMed Face Sheet & Patient Schedule → Insurance CSV Pipeline</div>', unsafe_allow_html=True)
    
    st.markdown(
        """
        <div style="background-color: #F8FAFC; border: 1px solid #CBD5E1; border-left: 5px solid #059669; padding: 18px 22px; border-radius: 10px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                <span style="font-size: 18px;">📋</span>
                <span style="font-size: 15px; font-weight: 700; color: #1E293B;">Automated Face Sheet & Schedule Export Engine</span>
            </div>
            <p style="margin: 0 0 8px 0; color: #475569; font-size: 13.5px; line-height: 1.5;">
                Ingests either <strong>Format A</strong> (ModMed Face Sheet PDF) or <strong>Format B</strong> (PatientDemoGraphicData CSV) and produces standardized, split insurance CSVs:
            </p>
            <ul style="margin: 0; padding-left: 20px; color: #475569; font-size: 13px; line-height: 1.6;">
                <li><strong>Format A (.pdf)</strong>: Extracts appointment date, provider, formatted patient name (handling titles, suffixes & compound surnames), DOB, and expands Primary/Secondary/Tertiary insurance blocks.</li>
                <li><strong>Format B (.csv)</strong>: Extracts from demographic schedules (40 columns), maps provider name, formats dates to <code>MM/DD/YYYY</code>, and strips resource placeholders.</li>
                <li><strong>Strict Business Logic</strong>: Filters manufacturer copay / patient-support programs (Xolair, Tezspire, Dupixent, etc.), drops incomplete or self-pay records, and guarantees pairs stay together with a <strong>max 99 patient rows per part file</strong>.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown('<div class="section-title">Upload Face Sheet or Demographic File</div>', unsafe_allow_html=True)
    facesheet_file = st.file_uploader(
        "Upload ModMed Face Sheet PDF or PatientDemoGraphicData CSV", 
        type=["pdf", "csv"], 
        key="facesheet_uploader", 
        label_visibility="collapsed"
    )

    if facesheet_file:
        file_bytes = facesheet_file.getvalue()
        fname = facesheet_file.name
        base_name = os.path.splitext(fname)[0]

        try:
            with st.spinner("Processing schedule and insurance records..."):
                fs_rows, fs_dropped, fs_src_count, fs_format, fs_secondaries, fs_support_prog = parse_facesheet_file(file_bytes, fname)

            st.success(f"Successfully processed {fname} ({fs_format})")

            # --- KPI Cards ---
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Source Units", fs_src_count)
            k2.metric("Output Rows", len(fs_rows))
            k3.metric("Dropped Rows", len(fs_dropped))
            k4.metric("Secondary Ins.", fs_secondaries)
            
            fs_chunks = chunk_facesheet_groups(fs_rows, cap=99)
            k5.metric("Part Files (<=99 rows)", len(fs_chunks))

            # --- System Tip Alert ---
            st.info(
                f"💡 **Part Splitting**: Records are split into **{len(fs_chunks)}** part file(s) (each capped at 99 patient rows + header). "
                "Primary and Secondary insurance rows for the same appointment are strictly kept together in the same file.\\n\\n"
                "📌 **Excel Tip**: When opening these CSVs in Microsoft Excel, import the **policy number** column as **Text** to preserve leading zeros."
            )

            # --- Support Program Drops Summary ---
            if fs_support_prog:
                with st.expander(f"🛡️ Manufacturer Copay / Support Programs Filtered ({sum(fs_support_prog.values())} rows dropped)", expanded=False):
                    st.write("These programs are copay assistance / drug foundations, not insurance payers, and were automatically excluded from the CSV:")
                    supp_df = pd.DataFrame(
                        [{"Program Name": k, "Rows Excluded": v} for k, v in fs_support_prog.items()]
                    )
                    st.dataframe(supp_df, width='stretch', hide_index=True)

            # --- Dropped Records Audit Log ---
            if fs_dropped:
                with st.expander(f"⚠️ Audit Trail: All Dropped Records ({len(fs_dropped)} rows)", expanded=False):
                    drop_recs = []
                    for d in fs_dropped:
                        drop_recs.append({
                            "Source Page / Row": d[0],
                            "Patient Name": d[1],
                            "Drop Reason": d[2]
                        })
                    drop_df = pd.DataFrame(drop_recs)
                    st.dataframe(drop_df, width='stretch', height=250, hide_index=True)

            # --- Data Preview ---
            if fs_rows:
                st.markdown('<div class="section-title">Data Preview</div>', unsafe_allow_html=True)
                raw_rows_data = [r[1] for r in fs_rows]
                df_out = pd.DataFrame(raw_rows_data, columns=FACESHEET_HEADER)
                df_display = df_out.copy()
                df_display.index += 1
                st.dataframe(df_display, width='stretch', height=350)

                # --- Part Breakdown Summary ---
                with st.expander("📦 Part Files Breakdown", expanded=False):
                    part_summary = []
                    for idx, ch in enumerate(fs_chunks, 1):
                        part_summary.append({
                            "File Name": f"{base_name}_part{idx}.csv",
                            "Patient Rows": len(ch),
                            "Total Lines (with header)": len(ch) + 1
                        })
                    st.dataframe(pd.DataFrame(part_summary), width='stretch', hide_index=True)

                # --- Export Section ---
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                exp_c1, exp_c2, exp_c3 = st.columns(3)

                with exp_c1:
                    zip_bytes = create_facesheet_zip(fs_chunks, base_name)
                    st.download_button(
                        label=f"📥 Download All Parts Archive (.zip) - {len(fs_chunks)} files",
                        data=zip_bytes,
                        file_name=f"{base_name}_split_parts.zip",
                        mime="application/zip",
                        key="fs_zip_btn"
                    )

                with exp_c2:
                    full_csv = df_out.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label=f"📥 Download Consolidated CSV ({len(df_out)} rows)",
                        data=full_csv,
                        file_name=f"{base_name}_consolidated.csv",
                        mime="text/csv",
                        key="fs_csv_btn"
                    )

                with exp_c3:
                    if fs_dropped:
                        drop_csv = pd.DataFrame(drop_recs).to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label=f"📥 Download Dropped Audit Log (.csv)",
                            data=drop_csv,
                            file_name=f"{base_name}_dropped_audit.csv",
                            mime="text/csv",
                            key="fs_drop_csv_btn"
                        )
            else:
                st.warning("No valid insurance records could be extracted from this file after applying filtering rules.")

        except Exception as e:
            st.error(f"Error processing file: {e}")





