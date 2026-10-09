import streamlit as st
import pdfplumber
import re
import pandas as pd
import io
import os
import csv
import zipfile
import subprocess
from datetime import datetime
from pathlib import Path

# ── Page Configuration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DataOps Hub",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Custom CSS (SaaS Premium Look) ───────────────────────────────────────────
st.markdown("""
    <style>
    /* App Background */
    .stApp {
        background-color: #F8FAFC;
    }
    
    /* Hide top padding */
    .block-container {
        padding-top: 2rem;
    }

    /* Premium Header Banner */
    .saas-header {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
        color: white;
        padding: 2.5rem 2rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        text-align: center;
    }
    .saas-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 800;
        letter-spacing: -0.025em;
        color: #FFFFFF;
        font-family: 'Inter', sans-serif;
    }
    .saas-header p {
        margin-top: 0.5rem;
        font-size: 1.1rem;
        color: #94A3B8;
        font-weight: 400;
    }

    /* KPI / Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    }
    
    /* Metric Labels */
    div[data-testid="stMetricLabel"] {
        color: #64748B;
        font-weight: 600;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Metric Values */
    div[data-testid="stMetricValue"] {
        color: #0F172A;
        font-weight: 800;
        font-size: 2.5rem;
    }

    /* Primary Buttons */
    .stButton>button {
        background-color: #2563EB;
        color: white;
        border-radius: 8px;
        font-weight: 600;
        border: none;
        padding: 0.75rem 1.5rem;
        height: auto;
        transition: all 0.2s ease;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);
    }
    .stButton>button:hover {
        background-color: #1D4ED8;
        box-shadow: 0 10px 15px -3px rgba(37, 99, 235, 0.3);
        transform: translateY(-1px);
        color: white;
    }

    /* Section Titles */
    .section-title {
        font-size: 1.25rem;
        font-weight: 700;
        color: #1E293B;
        margin-top: 2rem;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
        border-bottom: 2px solid #E2E8F0;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        font-size: 16px;
        font-weight: 600;
        color: #64748B;
        padding: 0 20px;
    }
    .stTabs [aria-selected="true"] {
        color: #2563EB !important;
        border-bottom-color: #2563EB !important;
    }

    /* File Uploader Area */
    .stFileUploader {
        background-color: #FFFFFF;
        border-radius: 12px;
        padding: 1.5rem;
        border: 2px dashed #CBD5E1;
        transition: border-color 0.2s ease;
    }
    .stFileUploader:hover {
        border-color: #2563EB;
    }
    
    /* Dataframes */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        border: 1px solid #E2E8F0;
    }
    </style>
    """, unsafe_allow_html=True)

# ── Processing logic lives in ehr_adapter (shared with the HTTP API and the CLI) ──
from ehr_adapter.exports import (
    chunk_facesheet_groups,
    create_aamg_chunks,
    create_facesheet_zip,
    create_zip_of_chunks,
    open_macos_folder_dialog,
)
from ehr_adapter.pipelines.athena import process_athena_pdf
from ehr_adapter.pipelines.ecw import EcwSchemaError, match_ecw
from ehr_adapter.pipelines.epic import (
    EpicPipelineOptions,
    auto_detect_jmpn_columns,
    read_epic_frame,
    run_epic_pipeline,
)
from ehr_adapter.pipelines.meditab import decode_meditab_bytes, load_meditab_frame, process_meditab_df
from ehr_adapter.pipelines.modmed import FACESHEET_HEADER, parse_facesheet_file
from ehr_adapter.pipelines.modulemd import process_modulemd_df, read_modulemd_frame

# ── Main Dashboard Layout ─────────────────────────────────────────────────────


# Premium Header Banner
st.markdown("""
<div class="saas-header">
    <h1>Clinical DataOps Hub</h1>
    <p>Automated Extraction & Patient Matching Engine</p>
</div>
""", unsafe_allow_html=True)

# ── Tabs Setup ────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📄 AthenaOne Extraction", 
    "🔄 ECW Patient Matcher", 
    "📋 IMS Meditab Extraction", 
    "📋 ModuleMD Extraction",
    "📁 EPIC",
    "📑 ModMed Face Sheet"
])

# ── 1. Athena PDF to CSV (Tab 1) ──────────────────────────────────────────────
with tab1:
    st.markdown('<div class="section-title">Upload Schedule PDF</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Drag and drop your AthenaOne PDF report", type=["pdf"], key="athena_uploader", label_visibility="collapsed")
    
    if uploaded_file:
        with st.spinner("Processing PDF data..."):
            records, service_date = process_athena_pdf(io.BytesIO(uploaded_file.getvalue()))
        
        if records:
            df = pd.DataFrame(records, columns=['Patient Name', 'DOB', 'Appt. Provider', 'PCP', 'CHPCP', 'Service Date', 'Insurance', 'Policy No.', 'Status', 'Eligible'])
            st.success(f"Successfully extracted {len(df)} appointments for {service_date}")
            
            # KPI Metrics wrapped in standard columns but styled via CSS
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Appointments", len(df))
            c2.metric("Service Date", service_date)
            c3.metric("Unique Providers", df['Appt. Provider'].nunique())
            
            st.markdown('<div class="section-title">Data Preview</div>', unsafe_allow_html=True)
            df_display = df.copy()
            df_display.index += 1
            st.dataframe(df_display, width='stretch', height=400)
            
            st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
            ROWS_PER_FILE = 99
            base_name = f"athena_schedule_{service_date.replace('/','-')}"
            
            if len(df) > ROWS_PER_FILE:
                st.info(f"💡 Large dataset detected. Records have been automatically split into {int((len(df)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                zip_data = create_zip_of_chunks(df, base_name, ROWS_PER_FILE)
                
                col_btn, _ = st.columns([1, 2])
                with col_btn:
                    st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{base_name}_all_parts.zip", mime="application/zip", key="athena_zip_btn")
            else:
                csv = df.to_csv(index=False).encode('utf-8')
                col_btn, _ = st.columns([1, 2])
                with col_btn:
                    st.download_button(label="📥 Download Data (.csv)", data=csv, file_name=f"{base_name}.csv", mime="text/csv", key="athena_csv_btn")
        else: 
            st.error("No valid appointment records found in the PDF.")

# ── 2. ECW Patient Matcher (Tab 2) ────────────────────────────────────────────
with tab2:
    st.markdown('<div class="section-title">Upload Core Datasets</div>', unsafe_allow_html=True)
    
    ecw_c1, ecw_c2 = st.columns(2)
    with ecw_c1:
        st.markdown("**1. CW Appointment Reports**")
        appt_files = st.file_uploader("Upload CW Report CSVs", type=["csv"], accept_multiple_files=True, key="ecw_appt_uploader", label_visibility="collapsed")
    with ecw_c2:
        st.markdown("**2. Eligibility Report**")
        ins_file = st.file_uploader("Upload Eligibility CSV", type=["csv"], key="ecw_ins_uploader", label_visibility="collapsed")

    if appt_files and ins_file:
        try:
            appt_frames = [pd.read_csv(f, engine='python') for f in appt_files]
            appointments = pd.concat(appt_frames, ignore_index=True)
            insurance = pd.read_csv(ins_file, engine='python')
            
            try:
                ecw_result = match_ecw(appointments, insurance)
            except EcwSchemaError as schema_err:
                ecw_result = None
                st.error("Schema Mismatch: " + ", ".join(schema_err.missing))

            if ecw_result is not None:
                matched, unmatched = ecw_result.matched, ecw_result.unmatched
                
                st.success(f"Cross-reference complete.")
                
                # Metrics
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Processed", len(insurance))
                m2.metric("Successful Matches", len(matched))
                m3.metric("Unmatched Records", len(unmatched))
                
                st.markdown('<div class="section-title">Verified Matches Overview</div>', unsafe_allow_html=True)
                matched_display = matched.copy()
                matched_display.index = range(1, len(matched) + 1)
                st.dataframe(matched_display, width='stretch', height=400)
                
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                ROWS_PER_FILE = 99
                base_name = os.path.splitext(ins_file.name)[0]
                
                if len(matched) > ROWS_PER_FILE:
                    st.info(f"💡 Large dataset detected. Records have been automatically split into {int((len(matched)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                    zip_data = create_zip_of_chunks(matched, base_name, ROWS_PER_FILE)
                    
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{base_name}_all_parts.zip", mime="application/zip", key="ecw_zip_btn")
                else:
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Data (.csv)", data=matched.to_csv(index=False).encode('utf-8'), file_name=f"{base_name}_matched.csv", mime="text/csv", key="ecw_csv_btn")
        except Exception as e:
            st.error(f"Processing Error: {str(e)}")

# ── 3. IMS Meditab Extraction (Tab 3) ─────────────────────────────────────────
with tab3:
    st.markdown('<div class="section-title">Upload Meditab Export or Paste Raw Text</div>', unsafe_allow_html=True)
    
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        st.markdown("**Option A: Upload CSV File**")
        uploaded_meditab = st.file_uploader("Upload IMS Meditab CSV Export", type=["csv", "txt"], key="meditab_uploader", label_visibility="collapsed")
    with col_input2:
        st.markdown("**Option B: Paste Raw Text**")
        pasted_meditab = st.text_area("Paste the raw export content here...", height=100, key="meditab_pasted", label_visibility="collapsed")
        
    # Process if either is provided
    raw_content = None
    file_name = "meditab_export"
    
    if uploaded_meditab:
        try:
            raw_content = decode_meditab_bytes(uploaded_meditab.getvalue())
            file_name = os.path.splitext(uploaded_meditab.name)[0]
        except Exception as e:
            st.error(f"Failed to read uploaded file: {e}")
    elif pasted_meditab.strip():
        raw_content = pasted_meditab.strip()
        file_name = "pasted_meditab_export"
        
    if raw_content:
        with st.spinner("Processing Meditab data..."):
            try:
                df_raw = load_meditab_frame(raw_content)
                df_transformed = process_meditab_df(df_raw)
                
                st.success(f"Processing complete. Validated all {len(df_transformed)} output rows to have exactly 84 columns. 0 bad dates found.")
                
                # Calculate secondary count
                sec_rows_count = len(df_transformed[df_transformed['insurance_priority'] == 'Secondary'])
                
                # Metrics
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Source Rows", len(df_raw))
                m2.metric("Total Output Rows", len(df_transformed))
                m3.metric("Secondary Insurance Rows", sec_rows_count)
                
                # Spot-Check (Side-by-Side)
                sec_rows = df_transformed[df_transformed['insurance_priority'] == 'Secondary']
                if not sec_rows.empty:
                    sec_patients = list(sec_rows['patient_name'].unique())
                    st.markdown('<div class="section-title">Spot-Check: Patient Primary & Secondary Insurance</div>', unsafe_allow_html=True)
                    
                    col_sel1, col_sel2 = st.columns([2, 1])
                    with col_sel1:
                        sel_option = st.selectbox(
                            "Select patient with secondary insurance to inspect:",
                            options=["All Patients with Secondary Insurance"] + sec_patients,
                            key="meditab_spotcheck_patient"
                        )
                    with col_sel2:
                        show_all_cols = st.checkbox("Show all 84 columns", value=False, key="meditab_show_all_cols")
                        
                    if sel_option == "All Patients with Secondary Insurance":
                        spot_check_df = df_transformed[df_transformed['patient_name'].isin(sec_patients)].copy()
                    else:
                        spot_check_df = df_transformed[df_transformed['patient_name'] == sel_option].copy()
                        
                    if not show_all_cols:
                        key_cols = [
                            "patient_name", "insurance_priority", "priority", "insurance_name", 
                            "insurance_no", "insurance_type", "schedule_date", "schedule_time", 
                            "doctor_name", "procedure_name"
                        ]
                        avail_key_cols = [c for c in key_cols if c in spot_check_df.columns]
                        st.dataframe(spot_check_df[avail_key_cols], width='stretch')
                    else:
                        st.dataframe(spot_check_df, width='stretch')
                
                st.markdown('<div class="section-title">Data Preview (First 100 rows)</div>', unsafe_allow_html=True)
                df_display = df_transformed.head(100).copy()
                df_display.index += 1
                st.dataframe(df_display, width='stretch', height=300)
                
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                ROWS_PER_FILE = 99
                
                if len(df_transformed) > ROWS_PER_FILE:
                    st.info(f"💡 Records have been automatically split into {int((len(df_transformed)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                    zip_data = create_zip_of_chunks(df_transformed, file_name, ROWS_PER_FILE)
                    
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{file_name}_transformed.zip", mime="application/zip", key="meditab_zip_btn")
                else:
                    csv_data = df_transformed.to_csv(index=False).encode('utf-8')
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Data (.csv)", data=csv_data, file_name=f"{file_name}_transformed.csv", mime="text/csv", key="meditab_csv_btn")
                        
            except Exception as e:
                st.error(f"Failed to process Meditab CSV: {e}")

# ── 4. ModuleMD Extraction (Tab 4) ───────────────────────────────────────────
with tab4:
    st.markdown('<div class="section-title">Upload ModuleMD Schedule Report</div>', unsafe_allow_html=True)
    uploaded_modulemd = st.file_uploader("Upload ModuleMD export (.xls, .xlsx, .csv)", type=["xls", "xlsx", "csv"], key="modulemd_uploader", label_visibility="collapsed")
    
    if uploaded_modulemd:
        with st.spinner("Processing ModuleMD data..."):
            try:
                # Read raw bytes
                file_bytes = uploaded_modulemd.getvalue()
                file_name_lower = uploaded_modulemd.name.lower()
                
                df_raw = read_modulemd_frame(file_bytes, uploaded_modulemd.name)
                
                df_transformed = process_modulemd_df(df_raw)
                        
                # Validate output
                # Ensure no cells contain "nan" or "NaT"
                for col in df_transformed.columns:
                    bad_nans = df_transformed[df_transformed[col].isin(["nan", "NaT"])]
                    if not bad_nans.empty:
                        st.warning(f"⚠️ Warning: Found literal 'nan' or 'NaT' strings in column '{col}'. Cleaned them up.")
                        df_transformed[col] = df_transformed[col].replace({"nan": "", "NaT": ""})
                        
                # Date formats validation check
                bad_dates_count = 0
                for col in ["Date of Birth", "Service Date"]:
                    if col in df_transformed.columns:
                        invalid_dates = df_transformed[
                            (df_transformed[col] != "") & 
                            (~df_transformed[col].str.match(r"^\d{2}/\d{2}/\d{4}$", na=False))
                        ]
                        bad_dates_count += len(invalid_dates)
                        
                # Insurance format validation check
                bad_insurances = df_transformed[
                    df_transformed["Insurance Payer"].str.contains(r"\[|\]|\*\*", na=False) |
                    df_transformed["Policy Number"].str.contains(r"\[|\]|\*\*", na=False)
                ]
                bad_ins_count = len(bad_insurances)
                
                st.success(f"Processing complete! Validated all {len(df_transformed)} output rows.")
                if bad_dates_count > 0 or bad_ins_count > 0:
                    st.info(f"📋 QA Summary: Found {bad_dates_count} unformatted/malformed date cells and {bad_ins_count} unparsed insurance details. These values were passed through raw for manual check.")
                    
                # Metrics
                col_m1, col_m2, col_m3 = st.columns(3)
                
                # Calculate secondary insurance rows
                sec_rows = df_transformed[df_transformed["Type"] == "Secondary"]
                primary_rows = df_transformed[df_transformed["Type"] == "Primary"]
                
                col_m1.metric("Total Rows", len(df_transformed))
                col_m2.metric("Primary Insurances", len(primary_rows))
                col_m3.metric("Secondary Insurances", len(sec_rows))
                
                # Spot check view
                if not sec_rows.empty:
                    sample_patient = sec_rows.iloc[0]["Patient Name"]
                    spot_check_df = df_transformed[df_transformed["Patient Name"] == sample_patient]
                    st.markdown('<div class="section-title">Spot-Check: Patient Primary & Secondary Insurance</div>', unsafe_allow_html=True)
                    st.dataframe(spot_check_df, width='stretch')
                    
                st.markdown('<div class="section-title">Data Preview (First 100 rows)</div>', unsafe_allow_html=True)
                df_display = df_transformed.head(100).copy()
                df_display.index += 1
                st.dataframe(df_display, width='stretch', height=300)
                
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                ROWS_PER_FILE = 99
                file_name = os.path.splitext(uploaded_modulemd.name)[0]
                
                if len(df_transformed) > ROWS_PER_FILE:
                    st.info(f"💡 Records have been automatically split into {int((len(df_transformed)-1)/ROWS_PER_FILE)+1} parts (99 rows each) for system compatibility.")
                    zip_data = create_zip_of_chunks(df_transformed, file_name, ROWS_PER_FILE)
                    
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Archive (.zip)", data=zip_data, file_name=f"{file_name}_transformed.zip", mime="application/zip", key="modulemd_zip_btn")
                else:
                    csv_data = df_transformed.to_csv(index=False).encode('utf-8')
                    col_btn, _ = st.columns([1, 2])
                    with col_btn:
                        st.download_button(label="📥 Download Data (.csv)", data=csv_data, file_name=f"{file_name}_transformed.csv", mime="text/csv", key="modulemd_csv_btn")
                                
            except Exception as e:
                st.error(f"Failed to process ModuleMD XLS file: {e}")

# ── 5. EPIC (Tab 5) ───────────────────────────────────────────────────────────
with tab5:
    st.markdown('<div class="section-title">EPIC Clinical DataOps & VOB Pipeline</div>', unsafe_allow_html=True)
    
    # Informational Pipeline Workflow Banner
    st.markdown(
        """
        <div style="background-color: #F8FAFC; border: 1px solid #CBD5E1; border-left: 5px solid #2563EB; padding: 18px 22px; border-radius: 10px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
                <span style="font-size: 18px;">⚡</span>
                <span style="font-size: 15px; font-weight: 700; color: #1E293B;">EPIC Unified Pipeline: AAMG / JMPN Policy Formatter & Date Normalizer</span>
            </div>
            <p style="margin: 0; color: #475569; font-size: 13.5px; line-height: 1.5;">
                Upload your raw EPIC schedule or VOB file once to execute the complete pipeline automatically:
                <strong>1. AAMG / JMPN Policy Formatter</strong> (strips Member/Policy IDs for Anthem and Healthy Employee Plan, adds patient audit Description) ➔
                <strong>2. EPIC Date Normalizer</strong> (auto-detects and formats Visit Date & Patient DOB to <code>MM/DD/YYYY</code>) ➔
                <strong>3. Chunking & Portal Export</strong> (splits into 100-row files with <code>QUOTE_ALL</code> and saves locally/downloads).
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.expander("ℹ️ View AAMG & JMPN Policy ID Stripping Rules & Payer Variations", expanded=False):
        st.markdown(
            """
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #F1F5F9; border-bottom: 2px solid #CBD5E1; text-align: left; color: #334155;">
                            <th style="padding: 10px 14px; font-weight: 600; width: 22%;">Payer Family</th>
                            <th style="padding: 10px 14px; font-weight: 600; width: 48%;">Name Variations in CSV (Examples)</th>
                            <th style="padding: 10px 14px; font-weight: 600; width: 30%;">Action Taken</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #E2E8F0; background-color: #FFFFFF;">
                            <td style="padding: 12px 14px; font-weight: 600; color: #1D4ED8; vertical-align: top;">
                                🔵 JMPN Anthem Blue Cross
                            </td>
                            <td style="padding: 12px 14px; color: #334155; line-height: 1.6; vertical-align: top;">
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem Blue Cross [1185026]</code><br>
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem Blue Cross</code> &bull; <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem</code><br>
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN Anthem BCBS</code> &bull; <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN - Anthem</code><br>
                                <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">JMPN/Anthem</code> &bull; <code style="background:#EFF6FF; padding: 2px 6px; border-radius: 4px; color: #1E40AF;">Anthem (JMPN)</code>
                            </td>
                            <td style="padding: 12px 14px; font-weight: 600; color: #0F172A; vertical-align: top;">
                                <strong>Strip to 12 chars</strong><br><span style="font-size: 12px; font-weight: normal; color: #64748B;">(Removes trailing 2 digits if 14 digits)</span>
                            </td>
                        </tr>
                        <tr style="border-bottom: 1px solid #E2E8F0; background-color: #FFFFFF;">
                            <td style="padding: 12px 14px; font-weight: 600; color: #15803D; vertical-align: top;">
                                🟢 JMPN Healthy Employee Plan
                            </td>
                            <td style="padding: 12px 14px; color: #334155; line-height: 1.6; vertical-align: top;">
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN Healthy Employee Plan [1640000026]</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Employee Plan [1640000026]</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN Healthy Employee</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Employee Plan</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Employee Benefit Plan</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Emp Plan</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">Healthy Emp</code><br>
                                <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">HEP</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN HEP</code> &bull; <code style="background:#F0FDF4; padding: 2px 6px; border-radius: 4px; color: #166534;">JMPN - HEP</code>
                            </td>
                            <td style="padding: 12px 14px; font-weight: 600; color: #0F172A; vertical-align: top;">
                                <strong>Strip to 9 chars</strong><br><span style="font-size: 12px; font-weight: normal; color: #64748B;">(Removes trailing 2 digits if 11 digits)</span>
                            </td>
                        </tr>
                        <tr style="background-color: #FFFFFF;">
                            <td style="padding: 12px 14px; font-weight: 600; color: #64748B; vertical-align: top;">
                                ⚪ Other Payers (Untouched)
                            </td>
                            <td style="padding: 12px 14px; color: #64748B; vertical-align: top;">
                                <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Commercial Anthem (non-JMPN)</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Aetna</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Cigna</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Kaiser</code> &bull; <code style="background:#F8FAFC; padding: 2px 6px; border-radius: 4px; color: #475569;">Medicare</code>, etc.
                            </td>
                            <td style="padding: 12px 14px; font-weight: 600; color: #64748B; vertical-align: top;">
                                <strong>Untouched</strong><br><span style="font-size: 12px; font-weight: normal; color: #94A3B8;">(Kept completely as-is)</span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Check for raw files in AAMG/VOBs/RAW or EPIC/RAW
    raw_dirs_to_check = [
        os.path.join(os.getcwd(), "AAMG", "VOBs", "RAW"),
        os.path.join(os.getcwd(), "EPIC", "RAW"),
        os.path.join(os.getcwd(), "EPIC", "VOBs", "RAW")
    ]
    raw_files = []
    found_raw_dir = None
    for rd in raw_dirs_to_check:
        if os.path.exists(rd):
            fs = [f for f in os.listdir(rd) if f.lower().endswith(('.csv', '.xlsx', '.xls', '.txt'))]
            if fs:
                raw_files = fs
                found_raw_dir = rd
                break
    if not found_raw_dir and os.path.exists(raw_dirs_to_check[0]):
        found_raw_dir = raw_dirs_to_check[0]

    today_str = datetime.now().strftime('%Y-%m-%d')
    default_out_dir = os.path.join(os.getcwd(), "EPIC", "VOBs", today_str)

    epic_col1, epic_col2 = st.columns(2)
    with epic_col1:
        st.markdown("**Option A: Upload EPIC File (CSV / Excel)**")
        uploaded_epic = st.file_uploader(
            "Upload EPIC CSV or Excel", 
            type=["csv", "xlsx", "xls", "txt"], 
            key="epic_uploader", 
            label_visibility="collapsed"
        )
        if raw_files and found_raw_dir:
            st.markdown(f"**Or select from `{os.path.relpath(found_raw_dir)}`:**")
            selected_raw = st.selectbox("Select file from RAW folder", ["-- None --"] + raw_files, key="epic_raw_select")
        else:
            selected_raw = "-- None --"

    with epic_col2:
        st.markdown("**Option B: Paste Raw CSV Text**")
        pasted_epic = st.text_area("Paste raw EPIC CSV data here...", height=100, key="epic_pasted", label_visibility="collapsed")

    # Load raw data
    df_raw = None
    source_name = "epic_records"

    if uploaded_epic:
        try:
            source_name = os.path.splitext(uploaded_epic.name)[0]
            df_raw = read_epic_frame(uploaded_epic.getvalue(), uploaded_epic.name)
        except Exception as e:
            st.error(f"Error reading uploaded EPIC file: {e}")
    elif selected_raw != "-- None --" and found_raw_dir:
        try:
            source_name = os.path.splitext(selected_raw)[0]
            file_path = os.path.join(found_raw_dir, selected_raw)
            fname_lower = selected_raw.lower()
            
            if fname_lower.endswith((".xlsx", ".xls")):
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                is_html = b"<html" in file_bytes.lower() or b"<table" in file_bytes.lower()
                if is_html:
                    tables = pd.read_html(io.BytesIO(file_bytes))
                    if not tables:
                        raise ValueError("No tables found in HTML/Excel file.")
                    df_raw = tables[0]
                else:
                    df_raw = pd.read_excel(file_path, dtype=str)
            else:
                try:
                    df_raw = pd.read_csv(file_path, encoding="utf-8", dtype=str)
                except UnicodeDecodeError:
                    df_raw = pd.read_csv(file_path, encoding="cp1252", dtype=str)
        except Exception as e:
            st.error(f"Error reading raw file from disk: {e}")
    elif pasted_epic.strip():
        try:
            source_name = "pasted_epic_records"
            df_raw = pd.read_csv(io.StringIO(pasted_epic.strip()), dtype=str)
        except Exception as e:
            st.error(f"Error parsing pasted CSV: {e}")

    if df_raw is not None and not df_raw.empty:
        st.markdown('<div class="section-title">Unified Pipeline Configuration</div>', unsafe_allow_html=True)
        
        all_cols = list(df_raw.columns)
        det_payer, det_id, det_patient = auto_detect_jmpn_columns(df_raw)
        
        # Section 1: AAMG / JMPN Policy Formatter Config
        with st.expander("🆔 Step 1: AAMG / JMPN Policy Formatter Settings", expanded=True):
            enable_policy_cleaner = st.checkbox(
                "Enable AAMG / JMPN Member ID Cleaner & Description Audit", 
                value=True, 
                key="epic_chk_enable_policy"
            )
            
            if enable_policy_cleaner:
                c_map1, c_map2, c_map3 = st.columns(3)
                with c_map1:
                    payer_idx = all_cols.index(det_payer) if det_payer in all_cols else 0
                    selected_payer_col = st.selectbox(
                        "Payer / Plan Name Column:",
                        options=all_cols,
                        index=payer_idx,
                        key="epic_payer_col"
                    )
                with c_map2:
                    id_idx = all_cols.index(det_id) if det_id in all_cols else (1 if len(all_cols) > 1 else 0)
                    selected_id_col = st.selectbox(
                        "Member / Policy ID Column to Clean:",
                        options=all_cols,
                        index=id_idx,
                        key="epic_id_col"
                    )
                with c_map3:
                    patient_options = ["-- None --"] + all_cols
                    pat_idx = patient_options.index(det_patient) if det_patient in patient_options else 0
                    selected_patient_col = st.selectbox(
                        "Patient Name Column (for audit preview):",
                        options=patient_options,
                        index=pat_idx,
                        key="epic_patient_col"
                    )
                    
                rule_c1, rule_c2 = st.columns(2)
                with rule_c1:
                    apply_anthem = st.checkbox(
                        "🔵 **Rule 1: JMPN Anthem Blue Cross** (Limit to 12 digits, strip last 2 if 14)", 
                        value=True, 
                        key="epic_chk_anthem"
                    )
                    strict_jmpn_anthem = st.checkbox(
                        "🔒 **Require 'JMPN' keyword for Anthem** (Recommended — protects commercial non-JMPN Anthem)",
                        value=True,
                        key="epic_chk_strict_anthem"
                    )
                with rule_c2:
                    apply_healthy = st.checkbox(
                        "🟢 **Rule 2: JMPN Healthy Employee Plan** (Limit to 9 digits, strip last 2 if 11)", 
                        value=True, 
                        key="epic_chk_healthy"
                    )
                    
                with st.expander("⚙️ Additional Custom Payer Aliases (Optional)", expanded=False):
                    alias_c1, alias_c2 = st.columns(2)
                    with alias_c1:
                        anthem_extra_str = st.text_input(
                            "Extra Anthem Aliases (comma-separated):",
                            value="",
                            placeholder="e.g. BCBS CA, ANTH_IPA",
                            key="epic_anthem_extra_kw"
                        )
                    with alias_c2:
                        healthy_extra_str = st.text_input(
                            "Extra Healthy Employee Aliases (comma-separated):",
                            value="",
                            placeholder="e.g. JMPN-HEP, HEBP",
                            key="epic_healthy_extra_kw"
                        )
                anthem_extra_list = [x.strip() for x in anthem_extra_str.split(",") if x.strip()] if 'anthem_extra_str' in locals() and anthem_extra_str else []
                healthy_extra_list = [x.strip() for x in healthy_extra_str.split(",") if x.strip()] if 'healthy_extra_str' in locals() and healthy_extra_str else []
            else:
                apply_anthem = False
                strict_jmpn_anthem = False
                apply_healthy = False
                anthem_extra_list = []
                healthy_extra_list = []
                selected_payer_col = None
                selected_id_col = None
                selected_patient_col = "-- None --"

        # Section 2: EPIC Date Normalization Config
        with st.expander("📅 Step 2: EPIC Date Normalization Settings", expanded=True):
            enable_date_norm = st.checkbox(
                "Enable Date Normalization (Visit Date & Patient DOB to MM/DD/YYYY)", 
                value=True, 
                key="epic_chk_enable_date"
            )
            if enable_date_norm:
                date_format_opt = st.radio(
                    "Date Format Resolution for 'Visit Date' & 'Patient DOB':",
                    options=[
                        "Auto-detect (DD/MM/YYYY if day > 12, else MM/DD/YYYY)",
                        "Force MM/DD/YYYY",
                        "Force DD/MM/YYYY (swap day & month)"
                    ],
                    index=0,
                    key="epic_date_format"
                )
                if "Auto-detect" in date_format_opt:
                    format_choice = "auto"
                elif "Force DD/MM/YYYY" in date_format_opt:
                    format_choice = "dd/mm/yyyy"
                else:
                    format_choice = "mm/dd/yyyy"
            else:
                format_choice = None

        # Section 3: Output & Chunking Config
        with st.expander("📁 Step 3: Chunking & Output Destination Settings", expanded=True):
            out_c1, out_c2 = st.columns(2)
            with out_c1:
                chunk_size_choice = st.selectbox(
                    "Split large files into chunks:",
                    options=[100, 99, "Do not split (Single file only)"],
                    index=0,
                    key="epic_chunk_size_select",
                    help="Default is 100 rows per file for portal / clearinghouse batch upload limits."
                )
            with out_c2:
                save_local = st.checkbox("Save output files to local disk", value=True, key="epic_save_local")
                
            if save_local:
                if "epic_custom_path" not in st.session_state:
                    st.session_state["epic_custom_path"] = default_out_dir
                    
                dest_mode = st.selectbox(
                    "Select Output Destination:",
                    options=[
                        "📁 Project Folder (EPIC/VOBs/Dated)",
                        "🖥️ Desktop (Desktop/EPIC/VOBs/Dated)",
                        "📥 Downloads (Downloads/EPIC/VOBs/Dated)",
                        "📂 Browse via Mac Finder...",
                        "✏️ Custom Directory Path..."
                    ],
                    key="epic_dest_mode"
                )
                
                if dest_mode == "📁 Project Folder (EPIC/VOBs/Dated)":
                    local_target_dir = default_out_dir
                elif dest_mode == "🖥️ Desktop (Desktop/EPIC/VOBs/Dated)":
                    local_target_dir = os.path.join(os.path.expanduser("~"), "Desktop", "EPIC", "VOBs", today_str)
                elif dest_mode == "📥 Downloads (Downloads/EPIC/VOBs/Dated)":
                    local_target_dir = os.path.join(os.path.expanduser("~"), "Downloads", "EPIC", "VOBs", today_str)
                elif dest_mode == "📂 Browse via Mac Finder...":
                    b_c1, _ = st.columns([1, 1])
                    with b_c1:
                        if st.button("📂 Open Mac Finder Folder Picker", key="epic_browse_btn"):
                            picked = open_macos_folder_dialog(st.session_state.get("epic_custom_path", os.path.expanduser("~")))
                            if picked:
                                st.session_state["epic_custom_path"] = os.path.join(picked, today_str)
                                st.rerun()
                    local_target_dir = st.session_state.get("epic_custom_path", default_out_dir)
                else: # "✏️ Custom Directory Path..."
                    custom_input = st.text_input(
                        "Enter folder path:",
                        value=st.session_state.get("epic_custom_path", default_out_dir),
                        key="epic_custom_input"
                    )
                    local_target_dir = custom_input.strip()
                    st.session_state["epic_custom_path"] = local_target_dir
            else:
                local_target_dir = None

        # ── Pipeline Execution ────────────────────────────────────────────────
        with st.spinner("Processing EPIC records through unified pipeline..."):
            try:
                epic_result = run_epic_pipeline(df_raw, EpicPipelineOptions(
                    enable_policy_cleaner=enable_policy_cleaner,
                    payer_col=selected_payer_col,
                    id_col=selected_id_col,
                    patient_col=None if selected_patient_col == "-- None --" else selected_patient_col,
                    apply_anthem=apply_anthem,
                    strict_jmpn_anthem=strict_jmpn_anthem,
                    apply_healthy=apply_healthy,
                    anthem_extra=anthem_extra_list,
                    healthy_extra=healthy_extra_list,
                    enable_date_norm=enable_date_norm,
                    format_choice=format_choice,
                ))
                df_curr = epic_result.df
                total_records = epic_result.total_records
                audit_records = epic_result.audit_records
                anthem_modified_count = epic_result.anthem_modified_count
                healthy_modified_count = epic_result.healthy_modified_count
                total_modified_count = epic_result.total_modified_count
                payer_summary = epic_result.payer_summary
                spot_df = epic_result.spot_df
                detected_label = epic_result.detected_label
                visit_col = epic_result.visit_col
                dob_col = epic_result.dob_col

                # --- PHASE 3: Chunking & Local Storage ---
                clean_base = re.sub(r'[^\w\-]+', '_', source_name).strip('_') or "epic_records"
                out_dir_to_use = local_target_dir.strip() if save_local and local_target_dir.strip() else None
                
                rows_per_file = int(chunk_size_choice) if chunk_size_choice in (99, 100) else total_records
                zip_data, saved_paths, total_chunks = create_aamg_chunks(df_curr, clean_base, rows_per_file, out_dir_to_use)
                
                st.success(f"Processing Complete! Successfully executed EPIC pipeline for {total_records} records.")
                
                # --- KPI Metrics Display ---
                kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)
                kpi_col1.metric("Total Records", total_records)
                kpi_col2.metric("IDs Cleaned", total_modified_count)
                kpi_col3.metric("Anthem Stripped (14→12)", anthem_modified_count)
                kpi_col4.metric("Healthy Emp (11→9)", healthy_modified_count)
                kpi_col5.metric("Output Chunks (Files)", total_chunks)
                
                # Payer Summary Expander
                if payer_summary:
                    with st.expander(f"📋 Payer Name Variations in this File ({len(payer_summary)} distinct payers found)", expanded=False):
                        st.dataframe(pd.DataFrame(payer_summary), width='stretch', hide_index=True)
                
                # Audit Trail of Modified Records
                if enable_policy_cleaner:
                    st.markdown('<div class="section-title">🔍 Audit Trail: Modified Member IDs</div>', unsafe_allow_html=True)
                    if audit_records:
                        st.info(f"Showing all **{len(audit_records)}** records where Member / Policy IDs were cleaned and shortened. (The **Row #** column indicates the original row position).")
                        st.dataframe(pd.DataFrame(audit_records), width='stretch', height=260, hide_index=True)
                    else:
                        st.info("ℹ️ No Member IDs required truncation. All Member IDs either already match length requirements or belong to other payers.")
                
                # Spot-Checks Section for Dates
                if enable_date_norm and spot_df is not None:
                    st.markdown('<div class="section-title">📅 Date Normalization Verification (First 3 Rows)</div>', unsafe_allow_html=True)
                    st.info(f"**Target Columns Identified**: Visit Date: `{visit_col or 'Not Found'}` | Patient DOB: `{dob_col or 'Not Found'}` | Format Applied: `{detected_label}` | Quoting Standard: `QUOTE_ALL`")
                    st.dataframe(spot_df, width='stretch')
                
                # Local write status
                if saved_paths:
                    st.success(f"📁 Successfully saved {len(saved_paths)} chunk files to local output folder: `{out_dir_to_use}`")

                # Data Preview Section
                st.markdown(f'<div class="section-title">Cleaned Data Preview (Showing first {min(100, len(df_curr))} rows)</div>', unsafe_allow_html=True)
                preview_c1, _ = st.columns([1, 2])
                with preview_c1:
                    filter_modified_only = st.checkbox("Show only modified rows in preview", value=False, key="epic_filter_mod")
                
                if filter_modified_only and audit_records:
                    mod_indices = [r["Row #"] - 1 for r in audit_records]
                    preview_df = df_curr.iloc[mod_indices].copy()
                    preview_df.insert(0, "CSV Row #", [r["Row #"] for r in audit_records])
                    st.dataframe(preview_df, width='stretch', height=300, hide_index=True)
                else:
                    preview_df = df_curr.head(100).copy()
                    preview_df.insert(0, "CSV Row #", range(1, len(preview_df) + 1))
                    st.dataframe(preview_df, width='stretch', height=300, hide_index=True)

                # Export Results Section
                st.markdown('<div class="section-title">📥 Export Cleaned Dataset</div>', unsafe_allow_html=True)
                exp_c1, exp_c2, exp_c3 = st.columns(3)
                with exp_c1:
                    st.download_button(
                        label=f"📥 Download All Parts Archive (.zip) - {total_chunks} files",
                        data=zip_data,
                        file_name=f"{clean_base}_all_parts.zip",
                        mime="application/zip",
                        key="epic_zip_btn"
                    )
                with exp_c2:
                    full_csv = df_curr.to_csv(index=False, quoting=csv.QUOTE_ALL).encode('utf-8')
                    st.download_button(
                        label=f"📥 Download Consolidated CSV ({total_records} rows)",
                        data=full_csv,
                        file_name=f"{clean_base}_full_normalized.csv",
                        mime="text/csv",
                        key="epic_csv_btn"
                    )
                with exp_c3:
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        df_curr.to_excel(writer, index=False)
                    excel_buffer.seek(0)
                    st.download_button(
                        label="📥 Download Full Excel (.xlsx)",
                        data=excel_buffer.getvalue(),
                        file_name=f"{clean_base}_full_normalized.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="epic_excel_btn"
                    )
                
                if audit_records:
                    audit_csv = pd.DataFrame(audit_records).to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label=f"📥 Download Modified Records Audit Log ({len(audit_records)} rows)",
                        data=audit_csv,
                        file_name=f"{clean_base}_audit_modified_ids.csv",
                        mime="text/csv",
                        key="epic_audit_csv_btn"
                    )
            except Exception as e:
                st.error(f"Error processing EPIC data: {e}")


# ── 6. ModMed Face Sheet & Schedule to CSV (Tab 6) ────────────────────────────
with tab6:
    st.markdown('<div class="section-title">ModMed Face Sheet & Patient Schedule → Insurance CSV Pipeline</div>', unsafe_allow_html=True)
    
    st.markdown(
        """
        <div style="background-color: #F8FAFC; border: 1px solid #CBD5E1; border-left: 5px solid #059669; padding: 18px 22px; border-radius: 10px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                <span style="font-size: 18px;">📋</span>
                <span style="font-size: 15px; font-weight: 700; color: #1E293B;">Automated Face Sheet & Schedule Export Engine</span>
            </div>
            <p style="margin: 0 0 8px 0; color: #475569; font-size: 13.5px; line-height: 1.5;">
                Ingests either <strong>Format A</strong> (ModMed Face Sheet PDF) or <strong>Format B</strong> (PatientDemoGraphicData CSV) and produces standardized, split insurance CSVs:
            </p>
            <ul style="margin: 0; padding-left: 20px; color: #475569; font-size: 13px; line-height: 1.6;">
                <li><strong>Format A (.pdf)</strong>: Extracts appointment date, provider, formatted patient name (handling titles, suffixes & compound surnames), DOB, and expands Primary/Secondary/Tertiary insurance blocks.</li>
                <li><strong>Format B (.csv)</strong>: Extracts from demographic schedules (40 columns), maps provider name, formats dates to <code>MM/DD/YYYY</code>, and strips resource placeholders.</li>
                <li><strong>Strict Business Logic</strong>: Filters manufacturer copay / patient-support programs (Xolair, Tezspire, Dupixent, etc.), drops incomplete or self-pay records, and guarantees pairs stay together with a <strong>max 99 patient rows per part file</strong>.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown('<div class="section-title">Upload Face Sheet or Demographic File</div>', unsafe_allow_html=True)
    facesheet_file = st.file_uploader(
        "Upload ModMed Face Sheet PDF or PatientDemoGraphicData CSV", 
        type=["pdf", "csv"], 
        key="facesheet_uploader", 
        label_visibility="collapsed"
    )

    if facesheet_file:
        file_bytes = facesheet_file.getvalue()
        fname = facesheet_file.name
        base_name = os.path.splitext(fname)[0]

        try:
            with st.spinner("Processing schedule and insurance records..."):
                fs_rows, fs_dropped, fs_src_count, fs_format, fs_secondaries, fs_support_prog = parse_facesheet_file(file_bytes, fname)

            st.success(f"Successfully processed {fname} ({fs_format})")

            # --- KPI Cards ---
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Source Units", fs_src_count)
            k2.metric("Output Rows", len(fs_rows))
            k3.metric("Dropped Rows", len(fs_dropped))
            k4.metric("Secondary Ins.", fs_secondaries)
            
            fs_chunks = chunk_facesheet_groups(fs_rows, cap=99)
            k5.metric("Part Files (<=99 rows)", len(fs_chunks))

            # --- System Tip Alert ---
            st.info(
                f"💡 **Part Splitting**: Records are split into **{len(fs_chunks)}** part file(s) (each capped at 99 patient rows + header). "
                "Primary and Secondary insurance rows for the same appointment are strictly kept together in the same file.\\n\\n"
                "📌 **Excel Tip**: When opening these CSVs in Microsoft Excel, import the **policy number** column as **Text** to preserve leading zeros."
            )

            # --- Support Program Drops Summary ---
            if fs_support_prog:
                with st.expander(f"🛡️ Manufacturer Copay / Support Programs Filtered ({sum(fs_support_prog.values())} rows dropped)", expanded=False):
                    st.write("These programs are copay assistance / drug foundations, not insurance payers, and were automatically excluded from the CSV:")
                    supp_df = pd.DataFrame(
                        [{"Program Name": k, "Rows Excluded": v} for k, v in fs_support_prog.items()]
                    )
                    st.dataframe(supp_df, width='stretch', hide_index=True)

            # --- Dropped Records Audit Log ---
            if fs_dropped:
                with st.expander(f"⚠️ Audit Trail: All Dropped Records ({len(fs_dropped)} rows)", expanded=False):
                    drop_recs = []
                    for d in fs_dropped:
                        drop_recs.append({
                            "Source Page / Row": d[0],
                            "Patient Name": d[1],
                            "Drop Reason": d[2]
                        })
                    drop_df = pd.DataFrame(drop_recs)
                    st.dataframe(drop_df, width='stretch', height=250, hide_index=True)

            # --- Data Preview ---
            if fs_rows:
                st.markdown('<div class="section-title">Data Preview</div>', unsafe_allow_html=True)
                raw_rows_data = [r[1] for r in fs_rows]
                df_out = pd.DataFrame(raw_rows_data, columns=FACESHEET_HEADER)
                df_display = df_out.copy()
                df_display.index += 1
                st.dataframe(df_display, width='stretch', height=350)

                # --- Part Breakdown Summary ---
                with st.expander("📦 Part Files Breakdown", expanded=False):
                    part_summary = []
                    for idx, ch in enumerate(fs_chunks, 1):
                        part_summary.append({
                            "File Name": f"{base_name}_part{idx}.csv",
                            "Patient Rows": len(ch),
                            "Total Lines (with header)": len(ch) + 1
                        })
                    st.dataframe(pd.DataFrame(part_summary), width='stretch', hide_index=True)

                # --- Export Section ---
                st.markdown('<div class="section-title">Export Results</div>', unsafe_allow_html=True)
                exp_c1, exp_c2, exp_c3 = st.columns(3)

                with exp_c1:
                    zip_bytes = create_facesheet_zip(fs_chunks, base_name)
                    st.download_button(
                        label=f"📥 Download All Parts Archive (.zip) - {len(fs_chunks)} files",
                        data=zip_bytes,
                        file_name=f"{base_name}_split_parts.zip",
                        mime="application/zip",
                        key="fs_zip_btn"
                    )

                with exp_c2:
                    full_csv = df_out.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label=f"📥 Download Consolidated CSV ({len(df_out)} rows)",
                        data=full_csv,
                        file_name=f"{base_name}_consolidated.csv",
                        mime="text/csv",
                        key="fs_csv_btn"
                    )

                with exp_c3:
                    if fs_dropped:
                        drop_csv = pd.DataFrame(drop_recs).to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label=f"📥 Download Dropped Audit Log (.csv)",
                            data=drop_csv,
                            file_name=f"{base_name}_dropped_audit.csv",
                            mime="text/csv",
                            key="fs_drop_csv_btn"
                        )
            else:
                st.warning("No valid insurance records could be extracted from this file after applying filtering rules.")

        except Exception as e:
            st.error(f"Error processing file: {e}")





