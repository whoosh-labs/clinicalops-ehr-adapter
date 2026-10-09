"""Synthetic EHR exports, one builder per source. Every name, date and ID here is made up."""

import csv
import io

PDFPLUMBER_CHAR_PT = 7.25  # pdfplumber's layout text maps 7.25pt of x to one character
VALUE_COL = 15             # face-sheet left-column values start here (read from col 15-44)
RIGHT_COL = 52             # face-sheet right column, must be ignored


def _pdf(pages: list[list[str]], monospace: bool) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(640, 792))
    for lines in pages:
        if monospace:
            pdf.setFont("Courier", PDFPLUMBER_CHAR_PT / 0.6)  # Courier glyphs are 0.6 em wide
        else:
            pdf.setFont("Helvetica", 10)
        y = 760
        for line in lines:
            pdf.drawString(0 if monospace else 36, y, line)
            y -= 16
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


# ── AthenaOne ────────────────────────────────────────────────────────────────

ATHENA_LINES = [
    "Monday, October 12, 2026",
    "SARAH LIN, MD Department: ALLERGY",
    "9:00 AM - 9:15 AM Allergy Shot DOE, JANE (F) #48213",
    "DOB: 01/02/1980",
    "INS: BCBS TEXAS #XQZ123456789",
    "10:00 AM - 10:15 AM Allergy Shot FREE SLOT",
    "10:15 AM - 10:45 AM Food/Drug Challenge KIM, LEE (M) #50122",
    "DOB: 07/04/2015",
    "INS: UNITED HEALTHCARE",
    "CHOICE PLUS #987654321",
    "NITI SCHEDULE",
    "11:00 AM - 11:15 AM Biologic Drug Administration PARK, MIN JI (F) #50991",
    "DOB: 03/03/1990",
    "11:15 AM - 11:30 AM Follow-up WEST, AMY (F) #50992",
    "DOB: 04/04/1975",
    "INS: AETNA #W555",
]


def athena_pdf() -> bytes:
    return _pdf([ATHENA_LINES], monospace=False)


# ── ModMed face sheet PDF + demographics CSV ─────────────────────────────────

def _row(label: str, value: str = "", right: str = "") -> str:
    line = label.ljust(VALUE_COL) + value
    if right:
        line = line.ljust(RIGHT_COL) + right
    return line.rstrip()


def facesheet_page(appointment, provider, name, dob, blocks) -> list[str]:
    """blocks: [(kind, [carrier lines], policy or None)]"""
    lines = [
        " " * RIGHT_COL + f"Appointment: {appointment}",
        " " * RIGHT_COL + f"Provider: {provider}",
        "",
        "Patient Information",
        _row("Name:", name, "Phone: (555) 010-0100"),
        _row("D.O.B:", dob, "Sex: F"),
        _row("Address:", "1 Example St", "City: Springfield"),
    ]
    for kind, carrier_lines, policy in blocks:
        lines.append("")
        lines.append(f"{kind} Insurance Information")
        first, *rest = carrier_lines
        lines.append(_row("Carrier:", first, "Group #: G-100"))
        lines.extend(_row("", cont) for cont in rest)
        if policy is not None:
            lines.append(_row("Policy #:", policy, "Subscriber: Self"))
    return lines


FACESHEET_PAGES = [
    facesheet_page("10/05/2026 9:00 AM", "Rivera, Ana", "Mrs. ANNA Marie COLE", "03/14/1985", [
        ("Primary", ["UMR formerly Commonwealth", "Administrators, LLC"], "W123456789"),
        ("Secondary", ["MEDICARE PART B"], "1EG4TE5MK72"),
    ]),
    facesheet_page("10/05/2026 9:30 AM", "Rivera, Ana", "PETER James HALL, III", "07/01/1990", [
        ("Primary", ["AETNA PPO"], "W222000111"),
        ("Secondary", ["Xolair Copay Assistance"], "XC10442"),
    ]),
    facesheet_page("10/06/2026 8:00 AM", "Rivera, Ana", "NORA K BELL TATE", "02/02/1972", []),
    facesheet_page("10/06/2026 8:15 AM", "Rivera, Ana", "ROSA DE LA CRUZ", "11/30/1966", [
        ("Primary", ["BCBS TEXAS"], "XQZ123456789"),
        ("Secondary", ["Self Pay"], "SP1"),
    ]),
    facesheet_page("10/07/2026 10:00 AM", "Rivera, Ana", "JUAN D SAN MARTIN", "05/05/1955", [
        ("Primary", ["Maryland Medical Assistance"], "12345678901"),
        ("Secondary", ["AETNA PPO"], "0"),
    ]),
]


def facesheet_pdf() -> bytes:
    return _pdf(FACESHEET_PAGES, monospace=True)


DEMOGRAPHICS_HEADER = ["Pat L Name", "Pat F Name", "Pat M Initial", "Date", "Pat Birthdate", "ProviderName",
                       "ResourceName", "Primary Insurance Name", "Primary Ins Subscriber No", "Primary Ins Group No"]


def demographics_csv() -> bytes:
    return _csv(DEMOGRAPHICS_HEADER, [
        ["COLE", "ANNA", "M", "2026-10-05", "03/14/1985", "Rivera Ana L", "Allergy Shots", "AETNA PPO", "0012345", "G1"],
        ["HALL", "PETER", "", "2026-10-05", "07/01/1990", "Rivera Ana L", "OIT", "Dupixent MyWay", "DM5521", "G2"],
        ["TATE", "NORA", "K", "2026-10-06", "02/02/1972", "Rivera Ana L", "Allergy Shots", "Payer Not Found", "X1", ""],
        ["CRUZ", "ROSA", "", "2026-10-06", "11/30/1966", "Rivera Ana L", "Allergy Shots", "BCBS TEXAS", "", ""],
    ])


# ── IMS Meditab ──────────────────────────────────────────────────────────────

MEDITAB_HEADER = ["office_name", "schedule_date", "schedule_time", "doctor_name", "procedure_name", "patient_name",
                  "patient_bdate", "insurance_type", "ins_name", "insurance_no", "ins_secondary_name",
                  "sec_insurance_no", "phone_mobile", "pat_email"]


def meditab_csv() -> bytes:
    return _csv(MEDITAB_HEADER, [
        ["Main Clinic", "10/5/2026", "09:00", "RIVERA, ANA MD", "Allergy Shot", "COLE, ANNA", "3/14/1985",
         "Commercial Insurance Co", "AETNA PPO", "0012345", "MEDICARE PART B", "1EG4TE5MK72", "5550100100",
         "anna@example.com"],
        ["Main Clinic", "10/5/2026", "09:30", "RIVERA, ANA MD", "New Patient", "HALL, PETER", "7/1/1990",
         "BlueShield/Blue Cross", "BCBS TEXAS", "445566", "", "", "", ""],
        ["Main Clinic", "10/6/2026", "08:00", "RIVERA, ANA MD", "Follow-up", "TATE, NORA", "2/2/1972",
         "", "CIGNA", "", "", "", "", ""],
    ])


def meditab_cp1252_csv() -> bytes:
    return meditab_csv().decode("utf-8").replace("TATE, NORA", "MUÑOZ, NORA").encode("cp1252")


# ── ModuleMD (HTML table saved as .xls) ──────────────────────────────────────

MODULEMD_HEADER = ["Account #", "Patient Name", "Date of Birth", "Provider", "Schedule Date", "Visit Type",
                   "Location", "Email", "Cell Phone", "Insurance"]
MODULEMD_ROWS = [
    ["1001", "COLE, ANNA", "3/14/1985", "Rivera, Ana", "10/05/2026 09:30 AM", "New Patient", "Main Clinic",
     "anna@example.com", "555-010-0100", "AETNA[W1234567]**MEDICARE[1EG4TE5MK72]"],
    ["1002", "HALL, PETER", "7/1/1990", "Rivera, Ana", "10/05/2026 10:00 AM", "Follow-up", "Main Clinic",
     "peter@", "", "****"],
    ["1003", "TATE, NORA", "2/2/1972", "Rivera, Ana", "10/06/2026 08:00 AM", "Allergy Shot", "Main Clinic",
     "", "", "SELF PAY"],
]


def modulemd_html_xls() -> bytes:
    width = len(MODULEMD_HEADER)

    def tr(cells):
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    rows = [
        tr(["Schedule Report"] + [""] * (width - 1)),
        tr([""] * width),
        tr(["Printed 10/05/2026"] + [""] * (width - 1)),
        tr(MODULEMD_HEADER),
    ] + [tr(r) for r in MODULEMD_ROWS]
    return ("<html><body><table>" + "".join(rows) + "</table></body></html>").encode("utf-8")


# ── EPIC / AAMG ──────────────────────────────────────────────────────────────

EPIC_HEADER = ["Patient", "Visit Date", "Patient DOB", "Original Payer", "Primary Mem ID", "Visit Provider"]


def epic_csv() -> bytes:
    return _csv(EPIC_HEADER, [
        ["GRAY, OWEN", "25/03/2026", "25/12/1979", "JMPN Anthem Blue Cross [1185026]", "ABC12345678901", "Lin, Sarah"],
        ["LANE, MIA", "05/04/2026", "01/02/1980", "Anthem Blue Cross", "ABC12345678901", "Lin, Sarah"],
        ["ROSS, ELI", "06/04/2026", "03/03/1985", "JMPN Healthy Employee Plan [1640000026]", "12345678901",
         "Lin, Sarah"],
        ["WARD, ZOE", "07/04/2026", "04/04/1975", "Aetna", "W1234567890123", "Lin, Sarah"],
    ])


# ── eClinicalWorks ───────────────────────────────────────────────────────────

def ecw_appointments_csv() -> bytes:
    return _csv(["Patient", "DOB", "Visit Time"], [
        ["Smith, John A", "01/02/1980", "9:00"],
        ["Brown, Amy", "05/06/1970", "9:30"],
    ])


def ecw_eligibility_csv() -> bytes:
    return _csv(["Patient Name", "DOB", "Payer", "Member ID"], [
        ["John Smith", "1980-01-02", "AETNA", "W111"],
        ["brown,  amy", "5/6/1970", "CIGNA", "C222"],
        ["Smith, Jon", "01/02/1980", "UHC", "U333"],
        ["John Smith", "", "UHC", "U444"],
    ])
