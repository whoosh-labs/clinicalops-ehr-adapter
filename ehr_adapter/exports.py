"""File-export helpers for the Streamlit UI and the face-sheet CLI (moved verbatim from app.py).

Not used by the HTTP API: the service returns one CSV and never writes to disk.
"""

import csv
import io
import os
import re
import subprocess
import zipfile

from ehr_adapter.pipelines.modmed import FACESHEET_HEADER


def create_zip_of_chunks(df, base_filename, rows_per_file=99):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as zf:
        chunks = [df.iloc[i:i+rows_per_file] for i in range(0, len(df), rows_per_file)]
        for i, chunk in enumerate(chunks, 1):
            fname = f"{base_filename}_part{i}.csv"
            zf.writestr(fname, chunk.to_csv(index=False))
    buf.seek(0)
    return buf


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


def chunk_facesheet_groups(rows, cap=99):
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
