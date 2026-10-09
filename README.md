# ⚡ Clinical DataOps Hub

> **Automated Extraction, Transformation, Verification of Benefits (VOB) & Patient Matching Engine for Healthcare EHRs**

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://pdftocsv-1.streamlit.app/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()

**Clinical DataOps Hub** is an end-to-end data operations platform built for medical clinics, billing teams, and clinical data engineers. It automates the extraction, cleansing, transformation, and normalization of complex patient schedules, face sheets, and eligibility reports across major Electronic Health Record (EHR) and Practice Management (PM) systems.

---

## 🌟 Core Modules & Capabilities

The platform provides dedicated, battle-tested ingestion and transformation modules:

### 1. 📄 AthenaOne Schedule Extraction
- **Input**: Daily AthenaOne schedule export PDFs.
- **Parsing**: Automatically isolates appointment times, service dates, providers, patient demographics (Name, DOB), and insurance details (Payer, Policy #).
- **Cleansing**: Intelligently ignores `FREE SLOT` placeholders, handles multi-line clinic department headers, and parses dynamic provider layouts.
- **Batch Export**: Automatically chunks large schedules into portal-compatible 99-row files.

### 2. 🔄 eClinicalWorks (ECW) Patient Matcher
- **Input**: Multi-file CW Appointment CSVs + Eligibility / Insurance Master CSVs.
- **Matching Engine**: Dual-tier deterministic and tokenized fuzzy matching:
  - Exact match on normalized full name + DOB (`norm_name` + `norm_dob`).
  - Tokenized cross-matching (`get_name_match_key`) to resolve discrepancies between `"Last, First M"` vs `"First Last"`.
- **Audit Reports**: Produces reconciled datasets showing verified active appointments alongside unmatched exceptions.

### 3. 📋 IMS Meditab Extraction
- **Input**: Raw IMS Meditab billing logs, appointment registers, or pasted CSV text.
- **Pipeline**: Normalizes appointment dates, validates primary vs secondary insurance priority flags, and generates clean CSV outputs tailored for downstream claim scrubbers.

### 4. 📋 ModuleMD Extraction
- **Input**: ModuleMD spreadsheet registers and schedule extracts.
- **Pipeline**: Automated column header resolution, date standardization (`MM/DD/YYYY`), patient name segmentation, and policy number sanitization.

### 5. 📁 EPIC Clinical DataOps & VOB Pipeline
- **Input**: Raw EPIC schedule exports or Verification of Benefits (VOB) files (CSV, Excel `.xlsx`, `.xls`, or pasted text).
- **AAMG / JMPN Member ID Cleaner**:
  - **JMPN Anthem Blue Cross**: Enforces 12-digit standard by stripping 2-digit trailing suffixes from 14-digit IDs.
  - **JMPN Healthy Employee Plan (HEP)**: Enforces 9-digit standard by stripping 2-digit trailing suffixes from 11-digit IDs.
  - **Payer Protection**: Protects Commercial (non-JMPN) Anthem and third-party payers from unintended modification.
- **EPIC Date Normalizer**: Detects and standardizes appointment dates and birth dates to `MM/DD/YYYY`.
- **Export Standards**: Produces 100-row chunked files with `QUOTE_ALL` compliance for seamless payer portal uploading, complete with audit trail logs.

### 6. 📑 ModMed Face Sheet & Patient Schedule to CSV
- **Input**:
  - **Format A**: ModMed Face Sheet PDFs (e.g. `vegas-week-of-5th_oc.pdf`, `dmv.pdf`).
  - **Format B**: PatientDemoGraphicData CSV exports (40-column appointment files).
- **Name Engine**: Cleans titles (`Mr`, `Dr`, etc.), preserves suffixes (`Jr`, `III`), and respects Spanish compound surname particles (`DE`, `DEL`, `SAN`, `LOS`).
- **Payer Filtering Rules**:
  - Automatically identifies and filters manufacturer copay & patient-support assistance programs (e.g. Xolair, Tezspire, Dupixent, Nucala, Fasenra, Cinqair, MyWay) that cannot be verified via VOB eligibility.
  - Preserves legitimate government payers (e.g. Maryland Medical Assistance).
  - Automatically excludes self-pay, empty carriers, and placeholder policies (`0`, `1`).
- **File Splitting**: Strictly caps files at 99 patient rows (100 lines total with header) while guaranteeing Primary and Secondary insurance rows for the same appointment remain in the same part file.
- **Dual Runtime**: Accessible via the Streamlit web dashboard or as a standalone CLI script (`facesheet_to_csv.py`).

---

## 🏗️ Repository Architecture

```
├── app.py                             # Main Streamlit web application & UI
├── facesheet_to_csv.py                # Standalone CLI tool for ModMed Face Sheet parsing
├── facesheet_to_csv_instructions.md   # Specification & business rules documentation
├── packages.txt                       # Linux system packages for deployment (poppler-utils)
├── requirements.txt                   # Python runtime dependencies
├── .streamlit/
│   └── config.toml                    # Streamlit visual theme configuration
├── AAMG/                              # AAMG sample dataset repository
├── EPIC/                              # EPIC sample dataset repository
└── Clinical_DataOps_Platform_Guide.html # Interactive visual platform reference guide
```

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10 or higher
- Poppler utilities (for high-speed PDF text parsing):
  - **macOS**: `brew install poppler`
  - **Ubuntu/Debian**: `sudo apt-get install -y poppler-utils`

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Yadav0896/PDFTOCSV.git
   cd PDFTOCSV
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate    # On Windows: .venv\Scripts\activate
   ```

3. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## 💻 Usage

### 1. Launching the Web Application
Start the interactive Streamlit dashboard locally:
```bash
streamlit run app.py
```
Open your browser and navigate to:
```
http://localhost:8501
```

### 2. Using the Standalone Face Sheet CLI
To process ModMed Face Sheet PDFs or Patient Demographic CSVs directly from the terminal without launching the UI:
```bash
python3 facesheet_to_csv.py /path/to/schedule_input.pdf /path/to/output_prefix
```
**Example output**:
```bash
/path/to/output_prefix_part1.csv: 99 patient rows (+ header)
/path/to/output_prefix_part2.csv: 99 patient rows (+ header)
...
Source pages/rows=410 | Output rows=464 | Dropped=106
Generated 5 file(s)
Patients with secondary insurance: 70
```

---

## ☁️ Deployment

This project is pre-configured for **Streamlit Community Cloud**:
- [`packages.txt`](packages.txt) ensures `poppler-utils` (`pdftotext`) is installed in the Linux runtime container.
- High-resilience fallbacks guarantee identical, reliable extraction even if system libraries vary.

---

## 📄 Output CSV Specifications

For standardized insurance extracts, outputs adhere to the following strict format:

| Column | Format / Source | Description |
|---|---|---|
| `patient name` | `LAST, FIRST MIDDLE` | Cleaned of titles, casing preserved |
| `date of service` | `MM/DD/YYYY` | Appointment date |
| `birth date` | `MM/DD/YYYY` | Date of birth |
| `appointment provider` | Source string | As printed in source |
| `insurance name` | Normalized text | Manufacturer copay programs filtered |
| `policy number` | Alphanumeric | Formatted as text (leading zeros preserved) |

> 💡 **Excel Tip**: When opening output CSV files in Microsoft Excel, use the **Text Import Wizard** to import the `policy number` column as **Text** to prevent Excel from dropping leading zeros.
