#!/usr/bin/env python3
"""
Patient Schedule -> Insurance CSV Processor
Based on facesheet_to_csv_instructions.md
Supports:
- Format A: ModMed Face Sheet PDF (e.g. vegas-week-of-5th_oc.pdf)
- Format B: PatientDemoGraphicData CSV (e.g. PatientDemoGraphicData_*.csv)

Parsing lives in ehr_adapter.pipelines.modmed (shared with the Streamlit app and the HTTP API).
"""

import csv
import os
import sys

from ehr_adapter.exports import chunk_facesheet_groups
from ehr_adapter.pipelines.modmed import FACESHEET_HEADER, parse_facesheet_file

MAX_LINES = 100  # per file, INCLUDING the header row -> max 99 patient rows


def process_facesheet(input_path):
    """
    Processes an input file (PDF or CSV) and returns:
    (rows, dropped, src_count, format_type, secondaries_count, support_counter)
    """
    with open(input_path, "rb") as f:
        content = f.read()
    return parse_facesheet_file(content, os.path.basename(input_path), require_csv_columns=True)


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

    chunks = chunk_facesheet_groups(rows, cap=MAX_LINES - 1)
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    for n, chunk in enumerate(chunks, 1):
        path = f"{out}_part{n}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(FACESHEET_HEADER)
            w.writerows(chunk)
        print(f"{path}: {len(chunk)} patient rows (+ header)")

    print("\n--- Summary ---")
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
