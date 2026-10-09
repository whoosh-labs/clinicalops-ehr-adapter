"""ModMed face sheet PDF (Format A) and PatientDemoGraphicData CSV (Format B).

Moved verbatim from app.py, which had its own copy next to facesheet_to_csv.py; both now use this
module. ``require_csv_columns`` keeps the CLI's stricter Format B column check.
"""

import csv
import io
import os
import re
import subprocess
import tempfile
from collections import Counter

import pdfplumber

FACESHEET_HEADER = ["patient name", "date of service", "birth date", "appointment provider", "insurance name", "policy number"]
FACESHEET_PRE = {"MR", "MRS", "MS", "DR", "MISS"}
FACESHEET_SUF = {"JR", "SR", "II", "III", "IV"}
FACESHEET_PART = {"SAN", "DE", "DEL", "LA", "LOS", "VAN", "VON", "DA", "DI", "ST"}
FACESHEET_NO_INS = {"", "payer not found", "cash pay", "self pay", "self-pay", "selfpay", "none"}
FACESHEET_SUPPORT = re.compile(
    r"copay|co-pay|patient assistance|assistance program|savings|xolair|tezspire|dupixent|nucala|fasenra|cinqair|myway",
    re.I
)
FORMAT_B_REQUIRED_COLUMNS = ["Pat L Name", "Pat F Name", "Date", "Pat Birthdate", "ProviderName",
                             "Primary Insurance Name", "Primary Ins Subscriber No"]

FORMAT_A = "Format A: ModMed Face Sheet PDF"
FORMAT_B = "Format B: PatientDemoGraphicData CSV"


def facesheet_left_val(line):
    # value in the left column: text segment starting between col 15 and 45, not a label
    return " ".join(
        m.group() for m in re.finditer(r"\S+(?: \S+)*", line)
        if 15 <= m.start() < 45 and not m.group().endswith(":")
    )


def facesheet_fmt_name(n):
    t = n.replace(",", " ").split()
    while t and t[0].rstrip(".").upper() in FACESHEET_PRE:
        t = t[1:]
    suf = t.pop() if t and t[-1].rstrip(".").upper() in FACESHEET_SUF else ""
    if len(t) >= 3 and len(t[1].rstrip(".")) == 1:  # FIRST M LAST LAST
        first, last = t[:2], t[2:]
    else:
        k = len(t) - 1
        while k > 1 and t[k - 1].upper() in FACESHEET_PART:  # SAN MARTIN, DE LA ...
            k -= 1
        first, last = t[:k], t[k:]
    return f"{' '.join(last)}{' ' + suf if suf else ''}, {' '.join(first)}"


def facesheet_is_support(carrier):
    c = (carrier or "").strip().lower()
    if "medical assistance" in c:  # Government Medicaid program (Rule 4 exception)
        return False
    return bool(FACESHEET_SUPPORT.search(c))


def facesheet_bad(carrier, policy):
    return not carrier or not policy or carrier.strip().lower() in FACESHEET_NO_INS or policy.strip() in {"0", "1"}


def facesheet_reason(carrier, policy):
    if facesheet_is_support(carrier):
        return f"support program, not a payer: carrier='{carrier}'"
    return f"incomplete insurance: carrier='{carrier}' policy='{policy}'"


def _facesheet_pages(file_bytes):
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
        return [p for p in text.split("\f") if p.strip()]
    # Fallback when poppler is unavailable; column positions can differ from pdftotext -layout
    pages = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text(layout=True) or "")
    return pages


def parse_facesheet_file(file_bytes, filename, require_csv_columns=False):
    """Returns (rows, dropped, src_count, format_type, secondaries_count, support_counter).

    rows: [(page_or_line, [name, dos, dob, provider, carrier, policy])]
    dropped: [(page_or_line, name, reason)]
    """
    rows, dropped = [], []
    src_count = 0
    secondaries_count = 0
    lower_name = filename.lower()

    if lower_name.endswith(".pdf"):
        format_type = FORMAT_A
        pages = _facesheet_pages(file_bytes)

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
        format_type = FORMAT_B
        text_content = ""
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
            try:
                text_content = file_bytes.decode(enc)
                break
            except Exception:
                continue

        reader = list(csv.DictReader(io.StringIO(text_content)))
        src_count = len(reader)
        if require_csv_columns and reader:
            missing_cols = [c for c in FORMAT_B_REQUIRED_COLUMNS if c not in reader[0]]
            if missing_cols:
                raise ValueError(f"CSV format unrecognized. Missing required columns: {missing_cols}")

        for i, x in enumerate(reader, 2):  # line number in CSV
            def g(k, x=x):
                return (x.get(k) or "").strip()
            first = " ".join(v for v in [g("Pat F Name"), g("Pat M Initial")] if v)
            name = f"{g('Pat L Name')}, {first}".strip().rstrip(",")
            raw_date = g("Date")
            if "-" in raw_date:
                parts = raw_date.split("-")
                dos = f"{parts[1]}/{parts[2]}/{parts[0]}" if len(parts) == 3 else raw_date
            else:
                dos = raw_date

            dob = g("Pat Birthdate")
            prov = g("ProviderName")  # ProviderName, NOT ResourceName (OIT, Allergy Shots)
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
