#!/usr/bin/env python3
"""
Patient Schedule -> Insurance CSV Processor
Based on facesheet_to_csv_instructions.md

Supports:
- Format A: ModMed Face Sheet PDF (e.g. vegas-week-of-5th_oc.pdf)
- Format B: PatientDemoGraphicData CSV (e.g. PatientDemoGraphicData_*.csv)
"""

import re
import csv
import sys
import os
import subprocess
from collections import Counter

MAX_LINES = 100  # per file, INCLUDING the header row -> max 99 patient rows
HEADER = ["patient name", "date of service", "birth date", "appointment provider", "insurance name", "policy number"]

PRE = {"MR", "MRS", "MS", "DR", "MISS"}
SUF = {"JR", "SR", "II", "III", "IV"}
PART = {"SAN", "DE", "DEL", "LA", "LOS", "VAN", "VON", "DA", "DI", "ST"}
NO_INS = {"", "payer not found", "cash pay", "self pay", "self-pay", "selfpay", "none"}
SUPPORT = re.compile(
    r"copay|co-pay|patient assistance|assistance program|savings|xolair|tezspire|dupixent|nucala|fasenra|cinqair|myway",
    re.I
)

def left_val(line):
    # value in the left column: text segment starting between col 15 and 45, not a label
    return " ".join(
        m.group() for m in re.finditer(r"\S+(?: \S+)*", line)
        if 15 <= m.start() < 45 and not m.group().endswith(":")
    )

def fmt_name(n):
    t = n.replace(",", " ").split()
    while t and t[0].rstrip(".").upper() in PRE:
        t = t[1:]
    suf = t.pop() if t and t[-1].rstrip(".").upper() in SUF else ""
    if len(t) >= 3 and len(t[1].rstrip(".")) == 1:  # FIRST M LAST LAST
        first, last = t[:2], t[2:]
    else:
        k = len(t) - 1
        while k > 1 and t[k - 1].upper() in PART:
            k -= 1  # SAN AGUSTIN, DE LA ...
        first, last = t[:k], t[k:]
    return f"{' '.join(last)}{' ' + suf if suf else ''}, {' '.join(first)}"

def is_support(carrier):
    c = (carrier or "").strip().lower()
    if "medical assistance" in c:  # Government Medicaid program (Rule 4 exception)
        return False
    return bool(SUPPORT.search(c))

def bad(carrier, policy):
    return not carrier or not policy or carrier.strip().lower() in NO_INS or policy.strip() in {"0", "1"}

def reason(carrier, policy):
    if is_support(carrier):
        return f"support program, not a payer: carrier='{carrier}'"
    return f"incomplete insurance: carrier='{carrier}' policy='{policy}'"

def process_facesheet(input_path):
    """
    Processes an input file (PDF or CSV) and returns:
    (rows, dropped, src_count, format_type, secondaries_count, support_counter)
    """
    rows = []
    dropped = []
    src_count = 0
    secondaries_count = 0
    lower_path = input_path.lower()

    if lower_path.endswith(".pdf"):
        format_type = "Format A (ModMed Face Sheet PDF)"
        # Use pdftotext -layout
        res = subprocess.run(["pdftotext", "-layout", input_path, "-"], capture_output=True, text=True)
        if res.returncode != 0 or not res.stdout.strip():
            # Fallback to pdfplumber if pdftotext is unavailable or returns empty
            import pdfplumber
            pages_text = []
            with pdfplumber.open(input_path) as p_pdf:
                for page in p_pdf.pages:
                    pages_text.append(page.extract_text(layout=True) or "")
            pages = pages_text
        else:
            pages = [p for p in res.stdout.split("\f") if p.strip()]

        src_count = len(pages)
        for i, p in enumerate(pages, 1):
            L = p.split("\n")
            dos_match = re.search(r"Appointment:\s*(\d{2}/\d{2}/\d{4})", p)
            dos = dos_match.group(1) if dos_match else ""
            
            prov_matches = [re.search(r"Provider:\s*(.+)", l).group(1).strip() for l in L[:5] if "Provider:" in l]
            prov = prov_matches[0] if prov_matches else ""
            
            name_lines = [l for l in L if l.lstrip().startswith("Name:")]
            if name_lines:
                name = fmt_name(left_val(name_lines[0].replace("Name:", "     ", 1)))
            else:
                name = f"Unknown_Page_{i}"

            dob_match = re.search(r"D\.O\.B:\s+(\d{2}/\d{2}/\d{4})", p)
            dob = dob_match.group(1) if dob_match else ""

            base = [name, dos, dob, prov]
            blocks = [k for k, l in enumerate(L) if re.match(r"^\s*(Primary|Secondary|Tertiary) Insurance Information", l)]
            if not blocks:
                dropped.append((i, name, "no insurance on file"))
                continue

            patient_valid_rows = 0
            for k in blocks:
                j, car = k + 1, []
                while j < len(L) and not L[j].lstrip().startswith("Policy #:"):
                    car.append(left_val(L[j].replace("Carrier:", "        ", 1)))
                    j += 1
                carrier = " ".join(c for c in car if c).strip()
                policy = left_val(L[j].replace("Policy #:", "         ", 1)) if j < len(L) else ""

                if is_support(carrier) or bad(carrier, policy):
                    dropped.append((i, name, reason(carrier, policy)))
                    continue

                rows.append((i, base + [carrier, policy]))
                patient_valid_rows += 1

            if patient_valid_rows > 1:
                secondaries_count += 1

    elif lower_path.endswith(".csv"):
        format_type = "Format B (PatientDemoGraphicData CSV)"
        with open(input_path, encoding="utf-8-sig", newline="") as f:
            data = list(csv.DictReader(f))
        src_count = len(data)

        # Validate format B columns
        sample_row = data[0] if data else {}
        expected_cols = ["Pat L Name", "Pat F Name", "Date", "Pat Birthdate", "ProviderName", "Primary Insurance Name", "Primary Ins Subscriber No"]
        missing_cols = [c for c in expected_cols if c not in sample_row]
        if missing_cols and data:
            raise ValueError(f"CSV format unrecognized. Missing required columns: {missing_cols}")

        for i, x in enumerate(data, 2):  # line number in CSV
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
            prov = g("ProviderName")  # ProviderName, NOT ResourceName
            base = [name, dos, dob, prov]

            carrier = g("Primary Insurance Name")
            policy = g("Primary Ins Subscriber No")

            if is_support(carrier) or bad(carrier, policy):
                dropped.append((i, name, reason(carrier, policy)))
                continue

            rows.append((i, base + [carrier, policy]))

    else:
        raise ValueError("Unsupported file format. Please upload a .pdf (ModMed Face Sheet) or .csv (PatientDemoGraphicData) file.")

    support_counter = Counter(
        r.split("carrier='")[1].rstrip("'")
        for _, _, r in dropped
        if "support program" in r and "carrier='" in r
    )

    return rows, dropped, src_count, format_type, secondaries_count, support_counter

def chunk_rows(rows, cap=99):
    """
    Groups rows by appointment page and chunks into files with at most `cap` rows,
    guaranteeing primary and secondary rows for an appointment stay in the same file.
    """
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

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 facesheet_to_csv.py <input.pdf|.csv> <output_prefix>")
        sys.exit(1)

    inp = sys.argv[1]
    out = sys.argv[2]

    if not os.path.exists(inp):
        print(f"Error: Input file '{inp}' does not exist.")
        sys.exit(1)

    print(f"Processing '{inp}'...")
    try:
        rows, dropped, src_count, format_type, secondaries_count, support_counter = process_facesheet(inp)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    chunks = chunk_rows(rows, cap=MAX_LINES - 1)
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    for n, chunk in enumerate(chunks, 1):
        path = f"{out}_part{n}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(chunk)
        print(f"{path}: {len(chunk)} patient rows (+ header)")

    print(f"\n--- Summary ---")
    print(f"Format: {format_type}")
    print(f"Source pages/rows={src_count} | Output rows={len(rows)} | Dropped={len(dropped)}")
    print(f"Generated {len(chunks)} file(s)")
    if secondaries_count:
        print(f"Patients with secondary insurance: {secondaries_count}")

    if support_counter:
        print("\n--- Support Programs Dropped ---")
        for k, v in support_counter.items():
            print(f"SUPPORT PROGRAM DROPPED: {k} x{v}")

    print("\n--- Dropped Rows (Incomplete / No Insurance) ---")
    for d in dropped:
        if not d[2].startswith("support program"):
            print(f"DROPPED (page/line {d[0]}): {d[1]} -> {d[2]}")

    print("\nTip: When opening generated CSV files in Excel, import the 'policy number' column as Text to preserve leading zeros.")

if __name__ == "__main__":
    main()
