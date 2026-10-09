"""Helpers shared by several pipelines (moved verbatim from app.py)."""

import io
import re

import pandas as pd


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
    except Exception:
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


def is_html_table(file_bytes: bytes) -> bool:
    """ModuleMD / EPIC export HTML tables saved with an .xls extension."""
    lowered = file_bytes.lower()
    return b"<html" in lowered or b"<table" in lowered


def read_html_first_table(file_bytes: bytes, empty_message: str) -> pd.DataFrame:
    tables = pd.read_html(io.BytesIO(file_bytes))
    if not tables:
        raise ValueError(empty_message)
    return tables[0]
