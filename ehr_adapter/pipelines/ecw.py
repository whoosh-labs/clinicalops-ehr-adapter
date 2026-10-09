"""eClinicalWorks patient matcher (was inline in the ECW tab).

Keeps eligibility rows whose patient appears in the appointment reports: exact normalized
name + DOB, or tokenized ``last|first`` + DOB (handles "Last, First M" vs "First Last").
"""

from dataclasses import dataclass

import pandas as pd

from ehr_adapter.pipelines.common import get_name_match_key, norm_dob, norm_name

APPT_NAME_COLUMNS = ('patient', 'patient name', 'patient_name', 'pt name', 'name', 'full name', 'pt_name')
ELIGIBILITY_NAME_COLUMNS = ('patient name', 'patient', 'patient_name', 'pt name', 'name', 'member name', 'insured name')
DOB_COLUMNS = ('dob', 'date of birth', 'patient dob', 'birth date', 'dob (mm/dd/yyyy)', 'birthdate')


class EcwSchemaError(ValueError):
    def __init__(self, missing: list[str]):
        super().__init__(", ".join(missing))
        self.missing = missing


@dataclass
class EcwMatchResult:
    matched: pd.DataFrame
    unmatched: pd.DataFrame
    name_col: str
    dob_col: str


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...]):
    for c in df.columns:
        if str(c).strip().lower() in candidates:
            return c
    return None


def match_ecw(appointments: pd.DataFrame, insurance: pd.DataFrame) -> EcwMatchResult:
    appt_name_col = _find_column(appointments, APPT_NAME_COLUMNS)
    appt_dob_col = _find_column(appointments, DOB_COLUMNS)
    ins_name_col = _find_column(insurance, ELIGIBILITY_NAME_COLUMNS)
    ins_dob_col = _find_column(insurance, DOB_COLUMNS)

    if not (appt_name_col and ins_name_col and appt_dob_col and ins_dob_col):
        missing = []
        if not appt_name_col: missing.append("CW Reports missing Patient name column")
        if not appt_dob_col: missing.append("CW Reports missing DOB column")
        if not ins_name_col: missing.append("Eligibility missing Patient name column")
        if not ins_dob_col: missing.append("Eligibility missing DOB column")
        raise EcwSchemaError(missing)

    insurance = insurance.copy()
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
    return EcwMatchResult(matched=matched, unmatched=unmatched, name_col=ins_name_col, dob_col=ins_dob_col)
