"""AthenaOne schedule PDF (moved verbatim from app.py)."""

import re
from datetime import datetime

import pdfplumber

ATHENA_COLUMNS = ['Patient Name', 'DOB', 'Appt. Provider', 'PCP', 'CHPCP', 'Service Date', 'Insurance', 'Policy No.',
                  'Status', 'Eligible']


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
                except ValueError:
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
