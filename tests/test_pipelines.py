"""Characterization tests for the per-EHR pipelines moved out of app.py (synthetic fixtures only)."""

import io

import pytest

import fixtures as fx
from ehr_adapter.pipelines import athena, ecw, epic, meditab, modmed, modulemd
from ehr_adapter.pipelines.common import get_name_match_key


# ── AthenaOne ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def athena_records():
    records, service_date = athena.process_athena_pdf(io.BytesIO(fx.athena_pdf()))
    assert service_date == "10/12/2026"
    return {r["Patient Name"]: r for r in records}


def test_athena_free_slot_is_skipped_and_known_types_split_off(athena_records):
    assert set(athena_records) == {"Doe, Jane", "Kim, Lee", "Park, Min Ji", "West, Amy"}


def test_athena_provider_comes_from_department_header_then_alias(athena_records):
    assert athena_records["Doe, Jane"]["Appt. Provider"] == "SARAH LIN, MD"
    assert athena_records["Park, Min Ji"]["Appt. Provider"] == "NITI Y. CHOKSHI, MD"


def test_athena_wrapped_ins_line_is_joined(athena_records):
    kim = athena_records["Kim, Lee"]
    assert (kim["Insurance"], kim["Policy No."]) == ("UNITED HEALTHCARE CHOICE PLUS", "987654321")
    assert athena_records["Doe, Jane"]["DOB"] == "01/02/1980"


def test_athena_appointment_without_ins_line_keeps_blank_insurance(athena_records):
    assert (athena_records["Park, Min Ji"]["Insurance"], athena_records["Park, Min Ji"]["Policy No."]) == ("", "")


# ── ModMed ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("Mrs. ANNA Marie COLE", "COLE, ANNA Marie"),
    ("PETER James HALL, III", "HALL III, PETER James"),
    ("NORA K BELL TATE", "BELL TATE, NORA K"),
    ("ROSA DE LA CRUZ", "DE LA CRUZ, ROSA"),
    ("JUAN D SAN MARTIN", "SAN MARTIN, JUAN D"),
    ("LUCIA MARIA VEGA ROJAS", "ROJAS, LUCIA MARIA VEGA"),
])
def test_facesheet_name_rules(raw, expected):
    assert modmed.facesheet_fmt_name(raw) == expected


@pytest.mark.parametrize("carrier, policy, is_support, is_bad", [
    ("Xolair Copay Assistance", "XC1", True, False),
    ("Dupixent MyWay", "DM1", True, False),
    ("Maryland Medical Assistance", "12345678901", False, False),
    ("Self Pay", "SP1", False, True),
    ("Payer Not Found", "X1", False, True),
    ("AETNA PPO", "0", False, True),
    ("AETNA PPO", "", False, True),
    ("AETNA PPO", "W1", False, False),
])
def test_facesheet_payer_filters(carrier, policy, is_support, is_bad):
    assert modmed.facesheet_is_support(carrier) is is_support
    assert modmed.facesheet_bad(carrier, policy) is is_bad


def test_facesheet_pdf_rows_and_drops():
    rows, dropped, src_count, fmt, secondaries, support = modmed.parse_facesheet_file(fx.facesheet_pdf(), "w.pdf")

    assert (src_count, fmt, secondaries) == (5, modmed.FORMAT_A, 1)
    assert [r for _, r in rows] == [
        ["COLE, ANNA Marie", "10/05/2026", "03/14/1985", "Rivera, Ana",
         "UMR formerly Commonwealth Administrators, LLC", "W123456789"],
        ["COLE, ANNA Marie", "10/05/2026", "03/14/1985", "Rivera, Ana", "MEDICARE PART B", "1EG4TE5MK72"],
        ["HALL III, PETER James", "10/05/2026", "07/01/1990", "Rivera, Ana", "AETNA PPO", "W222000111"],
        ["DE LA CRUZ, ROSA", "10/06/2026", "11/30/1966", "Rivera, Ana", "BCBS TEXAS", "XQZ123456789"],
        ["SAN MARTIN, JUAN D", "10/07/2026", "05/05/1955", "Rivera, Ana", "Maryland Medical Assistance",
         "12345678901"],
    ]
    assert [(page, reason.split(":")[0]) for page, _, reason in dropped] == [
        (2, "support program, not a payer"),
        (3, "no insurance on file"),
        (4, "incomplete insurance"),
        (5, "incomplete insurance"),
    ]
    assert dict(support) == {"Xolair Copay Assistance": 1}


def test_demographics_csv_rows_and_drops():
    rows, dropped, src_count, fmt, *_ = modmed.parse_facesheet_file(fx.demographics_csv(), "d.csv")

    assert (src_count, fmt) == (4, modmed.FORMAT_B)
    assert [r for _, r in rows] == [["COLE, ANNA M", "10/05/2026", "03/14/1985", "Rivera Ana L", "AETNA PPO", "0012345"]]
    assert [line for line, _, _ in dropped] == [3, 4, 5]


def test_demographics_csv_column_check_is_opt_in():
    broken = fx.demographics_csv().replace(b"Pat L Name", b"Last")
    modmed.parse_facesheet_file(broken, "d.csv")  # Streamlit behaviour: no check
    with pytest.raises(ValueError, match="Missing required columns: \\['Pat L Name'\\]"):
        modmed.parse_facesheet_file(broken, "d.csv", require_csv_columns=True)


def test_modmed_rejects_other_extensions():
    with pytest.raises(ValueError, match="Unsupported file format"):
        modmed.parse_facesheet_file(b"x", "schedule.xlsx")


# ── Meditab ──────────────────────────────────────────────────────────────────

def test_meditab_primary_and_secondary_become_rows():
    df = meditab.process_meditab_df(meditab.load_meditab_frame(meditab.decode_meditab_bytes(fx.meditab_csv()),
                                                               as_text=True))
    cole = df[df["patient_name"] == "COLE, ANNA"]
    assert list(cole["insurance_priority"]) == ["Primary", "Secondary"]
    assert list(cole["insurance_name"]) == ["AETNA PPO", "MEDICARE PART B"]
    assert list(cole["patient_bdate"]) == ["03/14/1985", "03/14/1985"]
    assert list(cole["schedule_date"]) == ["10/05/2026", "10/05/2026"]
    assert len(df) == 4


def test_meditab_as_text_keeps_policy_numbers_intact():
    text = meditab.decode_meditab_bytes(fx.meditab_csv())
    inferred = meditab.process_meditab_df(meditab.load_meditab_frame(text))
    as_text = meditab.process_meditab_df(meditab.load_meditab_frame(text, as_text=True))

    assert list(inferred["insurance_no"][:3]) == ["12345.0", "1EG4TE5MK72", "445566.0"]  # Streamlit behaviour
    assert list(as_text["insurance_no"][:3]) == ["0012345", "1EG4TE5MK72", "445566"]


def test_meditab_cp1252_fallback():
    assert "MUÑOZ, NORA" in meditab.decode_meditab_bytes(fx.meditab_cp1252_csv())


# ── ModuleMD ─────────────────────────────────────────────────────────────────

def test_modulemd_html_xls_header_promotion_and_insurance_split():
    df = modulemd.process_modulemd_df(modulemd.read_modulemd_frame(fx.modulemd_html_xls(), "s.xls"))

    cole = df[df["Patient Name"] == "COLE, ANNA"]
    assert list(zip(cole["Insurance Payer"], cole["Policy Number"], cole["Type"], strict=True)) == [
        ("AETNA", "W1234567", "Primary"), ("MEDICARE", "1EG4TE5MK72", "Secondary"),
    ]
    assert list(cole["Service Date"]) == ["10/05/2026", "10/05/2026"]
    assert list(cole["Service Time"]) == ["09:30 AM", "09:30 AM"]
    assert list(cole["Date of Birth"]) == ["03/14/1985", "03/14/1985"]

    hall = df[df["Patient Name"] == "HALL, PETER"].iloc[0]
    assert (hall["Insurance Payer"], hall["Policy Number"], hall["Email"]) == ("", "", "")  # "****", bad email

    tate = df[df["Patient Name"] == "TATE, NORA"].iloc[0]
    assert (tate["Insurance Payer"], tate["Policy Number"]) == ("SELF PAY", "")


# ── EPIC ─────────────────────────────────────────────────────────────────────

def test_epic_pipeline_defaults():
    raw = epic.read_epic_frame(fx.epic_csv(), "e.csv")
    payer, member_id, patient = epic.auto_detect_jmpn_columns(raw)
    assert (payer, member_id, patient) == ("Original Payer", "Primary Mem ID", "Patient")

    result = epic.run_epic_pipeline(raw, epic.EpicPipelineOptions(payer_col=payer, id_col=member_id,
                                                                  patient_col=patient))

    assert list(result.df["Primary Mem ID"]) == ["ABC123456789", "ABC12345678901", "123456789", "W1234567890123"]
    assert list(result.df["Visit Date"]) == ["03/25/2026", "04/05/2026", "04/06/2026", "04/07/2026"]
    assert result.detected_label.startswith("DD/MM/YYYY")
    assert (result.anthem_modified_count, result.healthy_modified_count) == (1, 1)


@pytest.mark.parametrize("raw_id, payer, expected", [
    ("ABC12345678901", "JMPN Anthem Blue Cross [1185026]", "ABC123456789"),
    ("ABC123456789012", "Anthem (JMPN)", "ABC123456789"),
    ("ABC12345678901", "Anthem Blue Cross", "ABC12345678901"),
    ("12345678901", "JMPN Healthy Employee Plan [1640000026]", "123456789"),
    ("123456789", "JMPN HEP", "123456789"),
    ("W1234567890123", "Aetna", "W1234567890123"),
    ("123456789.0", "Aetna", "123456789"),
])
def test_jmpn_member_id_rules(raw_id, payer, expected):
    assert epic.clean_jmpn_member_id(raw_id, payer)[0] == expected


# ── eClinicalWorks ───────────────────────────────────────────────────────────

def test_ecw_match():
    import pandas as pd

    appts = pd.read_csv(io.BytesIO(fx.ecw_appointments_csv()), engine="python")
    elig = pd.read_csv(io.BytesIO(fx.ecw_eligibility_csv()), engine="python")
    result = ecw.match_ecw(appts, elig)

    assert list(result.matched["Member ID"]) == ["W111", "C222"]
    assert list(result.unmatched["Member ID"]) == ["U333", "U444"]


def test_ecw_missing_columns():
    import pandas as pd

    with pytest.raises(ecw.EcwSchemaError) as err:
        ecw.match_ecw(pd.DataFrame({"Patient": ["A"]}), pd.DataFrame({"Name": ["A"], "DOB": ["1/1/1980"]}))
    assert err.value.missing == ["CW Reports missing DOB column"]


@pytest.mark.parametrize("raw, key", [
    ("Smith, John A", "smith|john"),
    ("John Smith", "smith|john"),
    ("Smith", "smith|"),
])
def test_name_match_key(raw, key):
    assert get_name_match_key(raw) == key
