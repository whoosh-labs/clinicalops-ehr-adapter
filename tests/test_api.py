"""HTTP contract of POST /v1/normalize/{source} (synthetic fixtures only)."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

import fixtures as fx
from ehr_adapter import api
from ehr_adapter.normalize import REQUIRED, us_date

client = TestClient(api.app)


def post(source, filename, content, options=None):
    data = {"options": json.dumps(options)} if options is not None else None
    return client.post(f"/v1/normalize/{source}", files={"file": (filename, content)}, data=data)


def rows_of(body):
    return list(csv.DictReader(io.StringIO(body["csv"])))


def test_health_and_sources():
    assert client.get("/health").json() == {"status": "UP"}
    assert client.get("/v1/sources").json() == ["athena", "epic", "meditab", "modmed", "modulemd"]


def test_athena():
    body = post("athena", "schedule.pdf", fx.athena_pdf()).json()

    assert body["csv"].splitlines() == [
        "Patient Name,DOB,Appt. Provider,Service Date,Insurance,Policy No.",
        '"Doe, Jane",01/02/1980,"SARAH LIN, MD",10/12/2026,BCBS TEXAS,XQZ123456789',
        '"Kim, Lee",07/04/2015,"SARAH LIN, MD",10/12/2026,UNITED HEALTHCARE CHOICE PLUS,987654321',
        '"West, Amy",04/04/1975,"NITI Y. CHOKSHI, MD",10/12/2026,AETNA,W555',
    ]
    assert body["dropped"] == [
        {"source": "appointment 3", "patientName": "Park, Min Ji", "reason": "missing Insurance, Policy No."},
    ]
    assert body["stats"] == {"sourceUnits": 4, "rows": 3, "dropped": 1}
    assert body["rowCount"] == 3


def test_modmed_facesheet_pdf():
    body = post("modmed", "week.pdf", fx.facesheet_pdf()).json()

    assert [(r["Patient Name"], r["Insurance"], r["Policy No."]) for r in rows_of(body)] == [
        ("COLE, ANNA Marie", "UMR formerly Commonwealth Administrators, LLC", "W123456789"),
        ("COLE, ANNA Marie", "MEDICARE PART B", "1EG4TE5MK72"),
        ("HALL III, PETER James", "AETNA PPO", "W222000111"),
        ("DE LA CRUZ, ROSA", "BCBS TEXAS", "XQZ123456789"),
        ("SAN MARTIN, JUAN D", "Maryland Medical Assistance", "12345678901"),
    ]
    assert [(d["source"], d["patientName"]) for d in body["dropped"]] == [
        ("page 2", "HALL III, PETER James"), ("page 3", "BELL TATE, NORA K"),
        ("page 4", "DE LA CRUZ, ROSA"), ("page 5", "SAN MARTIN, JUAN D"),
    ]
    assert body["dropped"][0]["reason"] == "support program, not a payer: carrier='Xolair Copay Assistance'"
    assert body["stats"] == {"sourceUnits": 5, "rows": 5, "dropped": 4}


def test_modmed_demographics_csv():
    body = post("modmed", "PatientDemoGraphicData.csv", fx.demographics_csv()).json()

    assert body["csv"].splitlines()[1:] == ['"COLE, ANNA M",03/14/1985,Rivera Ana L,10/05/2026,AETNA PPO,0012345']
    assert [d["source"] for d in body["dropped"]] == ["line 3", "line 4", "line 5"]


def test_modmed_demographics_missing_columns_is_422():
    resp = post("modmed", "d.csv", fx.demographics_csv().replace(b"Pat L Name", b"Last Name"))

    assert resp.status_code == 422
    assert resp.json()["detail"] == "CSV format unrecognized. Missing required columns: ['Pat L Name']"


def test_meditab_keeps_policy_numbers_as_text():
    body = post("meditab", "export.csv", fx.meditab_csv()).json()

    assert body["csv"].splitlines()[0] == ("Patient Name,DOB,Appt. Provider,Service Date,Insurance,Policy No.,"
                                           "Appointment Type,Email,Phone")
    assert [(r["Patient Name"], r["Insurance"], r["Policy No."]) for r in rows_of(body)] == [
        ("COLE, ANNA", "AETNA PPO", "0012345"),
        ("COLE, ANNA", "MEDICARE PART B", "1EG4TE5MK72"),
        ("HALL, PETER", "BCBS TEXAS", "445566"),
    ]
    assert body["dropped"] == [{"source": "record 4", "patientName": "TATE, NORA", "reason": "missing Policy No."}]


def test_meditab_txt_and_cp1252_accepted():
    body = post("meditab", "export.txt", fx.meditab_cp1252_csv()).json()
    assert body["dropped"][0]["patientName"] == "MUÑOZ, NORA"


def test_modulemd_html_xls():
    body = post("modulemd", "schedule.xls", fx.modulemd_html_xls()).json()

    assert body["csv"].splitlines() == [
        "Patient Name,DOB,Appt. Provider,Service Date,Insurance,Policy No.,Appointment Type,Clinic,Email,Phone",
        '"COLE, ANNA",03/14/1985,"Rivera, Ana",10/05/2026,AETNA,W1234567,New Patient,Main Clinic,anna@example.com,'
        "555-010-0100",
        '"COLE, ANNA",03/14/1985,"Rivera, Ana",10/05/2026,MEDICARE,1EG4TE5MK72,New Patient,Main Clinic,'
        "anna@example.com,555-010-0100",
    ]
    assert [(d["patientName"], d["reason"]) for d in body["dropped"]] == [
        ("HALL, PETER", "missing Insurance, Policy No."),
        ("TATE, NORA", "missing Policy No."),
    ]


def test_modulemd_without_header_row_is_422():
    resp = post("modulemd", "s.csv", b"a,b\n1,2\n")
    assert resp.status_code == 422
    assert "header row not found" in resp.json()["detail"]


def test_epic_defaults():
    body = post("epic", "aamg.csv", fx.epic_csv()).json()

    assert body["csv"].splitlines() == [
        "Patient Name,DOB,Appt. Provider,Service Date,Insurance,Policy No.",
        '"GRAY, OWEN",12/25/1979,"Lin, Sarah",03/25/2026,JMPN Anthem Blue Cross [1185026],ABC123456789',
        '"LANE, MIA",02/01/1980,"Lin, Sarah",04/05/2026,Anthem Blue Cross,ABC12345678901',
        '"ROSS, ELI",03/03/1985,"Lin, Sarah",04/06/2026,JMPN Healthy Employee Plan [1640000026],123456789',
        '"WARD, ZOE",04/04/1975,"Lin, Sarah",04/07/2026,Aetna,W1234567890123',
    ]


def test_epic_options():
    body = post("epic", "aamg.csv", fx.epic_csv(), {"dateFormat": "mm/dd/yyyy", "strictJmpnAnthem": False}).json()
    lane = rows_of(body)[1]
    assert lane["Policy No."] == "ABC123456789"  # broad Anthem match trims commercial Anthem too

    assert post("epic", "aamg.csv", fx.epic_csv(), {"dateFormat": "yyyy"}).status_code == 422
    assert post("epic", "aamg.csv", fx.epic_csv(), {"anthemAliases": "BCBS CA"}).status_code == 422


def test_epic_unrecognized_columns_is_422():
    resp = post("epic", "x.csv", b"Foo,Bar\n1,2\n")
    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("EPIC export unrecognized")


@pytest.mark.parametrize("source, filename, content, status, detail", [
    ("nope", "x.csv", b"a", 404, "unknown source 'nope'"),
    ("ecw", "x.csv", b"a", 422, "ecw needs the two-file upload"),
    ("meditab", "x.pdf", b"%PDF", 422, "meditab expects .csv, .txt; got '.pdf'"),
    ("athena", "x.pdf", b"", 422, "The uploaded file is empty"),
    ("athena", "x.pdf", b"not a pdf at all", 422, "Could not read the file as a athena export"),
])
def test_errors(source, filename, content, status, detail):
    resp = post(source, filename, content)
    assert resp.status_code == status
    assert resp.json()["detail"].startswith(detail)


def test_bad_options_json_is_422():
    resp = client.post("/v1/normalize/epic", files={"file": ("e.csv", fx.epic_csv())}, data={"options": "{"})
    assert resp.status_code == 422


def test_file_size_limit(monkeypatch):
    monkeypatch.setattr(api, "MAX_FILE_BYTES", 10)
    assert post("epic", "e.csv", fx.epic_csv()).status_code == 413


def test_unexpected_error_is_500_without_details(monkeypatch, caplog):
    def boom(*_):
        raise KeyError("COLE, ANNA 03/14/1985")

    monkeypatch.setitem(api.SOURCES, "athena", api.SOURCES["athena"].__class__("athena", ("pdf",), [], boom))
    resp = post("athena", "s.pdf", fx.athena_pdf())

    assert resp.status_code == 500
    assert resp.json() == {"detail": "failed to normalize the file"}
    assert "COLE" not in caplog.text and "KeyError" in caplog.text


@pytest.mark.parametrize("raw, expected", [
    ("3/7/2026", "03/07/2026"),
    ("03/07/2026 09:15", "03/07/2026"),
    ("2026-03-07", "03/07/2026"),
    ("2026-03-07 09:15:00", "03/07/2026"),
    ("2026-03-07T09:15:00", "03/07/2026"),
    ("March 7", "March 7"),
])
def test_us_date(raw, expected):
    assert us_date(raw) == expected


def test_every_row_has_required_fields():
    for source, name, data in [("athena", "s.pdf", fx.athena_pdf()), ("modmed", "w.pdf", fx.facesheet_pdf()),
                               ("meditab", "m.csv", fx.meditab_csv()), ("modulemd", "s.xls", fx.modulemd_html_xls()),
                               ("epic", "e.csv", fx.epic_csv())]:
        for row in rows_of(post(source, name, data).json()):
            assert all(row[col] for col in REQUIRED), (source, row)
