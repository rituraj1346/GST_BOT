import os
import sys
import glob
import time
import base64
import requests
import traceback
import pandas as pd
import gspread
from datetime import datetime, timedelta
from google.cloud import bigquery
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from fpdf import FPDF
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

# ==============================================================================
# CONFIGURATION - FILL IN YOUR DETAILS HERE
# ==============================================================================
TWOCAPTCHA_API_KEY = "7edb643dc2fc3fd3c31baeb38dbe30cc"
GST_USERNAME = "AABFB6874"
GST_PASSWORD = "Jitu@2026"

# ==============================================================================
# TIME TRAVEL OVERRIDE (Set to None for automatic dynamic dates)
# Example: OVERRIDE_MONTH = 4  | OVERRIDE_YEAR = 2026
# ==============================================================================
OVERRIDE_MONTH = None
OVERRIDE_YEAR = None

# System Paths
# Automatically uses the folder where the script is located
DOWNLOAD_DIR = os.path.dirname(os.path.abspath(__file__)) 
SERVICE_ACCOUNT_FILE = os.path.join(DOWNLOAD_DIR, "halogen-valve-469005-j3-0b0820e1bd6c.json")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_FILE

# Google Drive Configuration
DRIVE_FOLDER_ID = "0AA-fV1pVBSk9Uk9PVA"

# ==============================================================================
# WhatsApp API Configuration
# ==============================================================================
WA_PHONE_ID = "695194337013529"
WA_BUSINESS_ID = "695194337013529"
WA_TOKEN = "EAAHPINsf7EcBPKiothSx8vR3Kbw5eOUwqxUD3g07A6evEZAoUAFN32cZC6EZAYQuem3QZA4HjmJSzw93VIMAiwbyk0kRKT75VK2qDFvPnUZBZBvEJP59n8wmobSNrpc4qsjl9a8M6ZA1mZBqKHzW91gqZC4FKz2vcMrXtZCjpylxxE9OYEk9ZCV2SolqAUw4rLkwkfRMAZDZD"
WA_TEMPLATE = "declartion"
WA_LANG = "en"
SEND_TO_NUMBER = "919854186693"
# ==============================================================================

# BigQuery Schema
PROJECT_ID = "halogen-valve-469005-j3"
BQ_DATASETS = {
    "tallydb": "Hardware",
    "tallydb3": "Paints",
    "tallydb4": "Tiles",
    "tallydb5": "Grocery"
} 
BQ_TABLE_NAME = "trn_voucher" 

# Mapped precisely to your BigQuery Schema aliases
BQ_COL_INVOICE = "Invoice_No"    
BQ_COL_DATE = "Voucher_Date"     
BQ_COL_TYPE = "Voucher_Type"
# ==============================================================================


def get_dynamic_gst_dates(override_month=None, override_year=None):
    """Calculates the target month dynamically, or uses manual override if provided."""
    import calendar
    
    if override_month and override_year:
        print(f"⏰ MANUAL OVERRIDE DETECTED: Forcing data extraction for {override_month}/{override_year}")
        target_month = override_month
        target_year = override_year
        period = calendar.month_name[target_month]
    else:
        # Standard dynamic rule
        today = datetime.now()
        if today.day < 16:
            first_of_this_month = today.replace(day=1)
            last_of_prev_month = first_of_this_month - timedelta(days=1)
            target_date = last_of_prev_month.replace(day=1) - timedelta(days=1)
        else:
            target_date = today.replace(day=1) - timedelta(days=1)
            
        target_month = target_date.month
        target_year = target_date.year
        period = target_date.strftime("%B")
        
    # Calculate FY and Quarter identically for both paths
    financial_year = f"{target_year}-{str(target_year + 1)[-2:]}" if target_month >= 4 else f"{target_year - 1}-{str(target_year)[-2:]}"
    
    if target_month in [4, 5, 6]: quarter = "Quarter 1 (Apr - Jun)"
    elif target_month in [7, 8, 9]: quarter = "Quarter 2 (Jul - Sep)"
    elif target_month in [10, 11, 12]: quarter = "Quarter 3 (Oct - Dec)"
    else: quarter = "Quarter 4 (Jan - Mar)"
        
    print(f"🗓️ Target Period: FY {financial_year} | {quarter} | {period}")
    return financial_year, quarter, period, target_month, target_year

def solve_captcha_2captcha(driver, captcha_img_element):
    """Solves the visual GST CAPTCHA."""
    print("🤖 Sending CAPTCHA to 2Captcha API...")
    captcha_filename = os.path.join(DOWNLOAD_DIR, "gst_captcha.png")
    captcha_img_element.screenshot(captcha_filename)
    
    with open(captcha_filename, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        
    payload = {'key': TWOCAPTCHA_API_KEY, 'method': 'base64', 'body': encoded_string, 'json': 1}
    response = requests.post('http://2captcha.com/in.php', data=payload).json()
    
    if response.get('status') != 1: raise Exception(f"❌ 2Captcha Error: {response.get('request')}")
    request_id = response.get('request')
    
    fetch_url = f"http://2captcha.com/res.php?key={TWOCAPTCHA_API_KEY}&action=get&id={request_id}&json=1"
    for _ in range(20):
        time.sleep(5)
        res = requests.get(fetch_url).json()
        if res.get('status') == 1: return res.get('request')
        elif res.get('request') != 'CAPCHA_NOT_READY': raise Exception(f"❌ 2Captcha Error: {res.get('request')}")
    raise Exception("❌ CAPTCHA solving timed out.")


def select_angular_option(driver, wait, select_name, target_value):
    """Handles Angular Dropdown selections."""
    select_xpath = f"//select[@name='{select_name}']"
    wait.until(EC.presence_of_element_located((By.XPATH, select_xpath)))
    
    def options_loaded(d):
        try:
            s = Select(d.find_element(By.XPATH, select_xpath))
            opts = [o.text.strip() or o.get_attribute("label").strip() for o in s.options]
            return any(target_value in opt for opt in opts)
        except Exception: return False
    WebDriverWait(driver, 15).until(options_loaded)
    
    select = Select(driver.find_element(By.XPATH, select_xpath))
    try: select.select_by_visible_text(target_value)
    except Exception:
        for opt in select.options:
            opt_text = opt.text.strip() or opt.get_attribute("label").strip()
            if target_value in opt_text:
                opt.click()
                break
    time.sleep(1.5)


def wait_for_download(download_dir, timeout=60):
    """Watches the directory for the Excel file to finish downloading."""
    print(f"⏳ Monitoring {download_dir} for incoming download...")
    seconds = 0
    is_downloading = True
    
    while is_downloading and seconds < timeout:
        time.sleep(1)
        is_downloading = False
        for fname in os.listdir(download_dir):
            if fname.endswith('.crdownload'):
                is_downloading = True
                break
        seconds += 1
        
    if is_downloading: raise Exception("❌ Download timed out!")

    list_of_files = glob.glob(os.path.join(download_dir, '*.xlsx'))
    if not list_of_files: raise Exception("❌ Could not locate the downloaded Excel file.")
        
    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"✅ Download complete! File saved at: {latest_file}")
    return latest_file


def extract_tally_purchases_from_bq(target_month, target_year):
    """Loops through company datasets, maps friendly names, and extracts Purchases and Notes."""
    print(f"☁️ Fetching Tally Purchase & Note data from multiple datasets for {target_month}/{target_year}...")
    client = bigquery.Client(project=PROJECT_ID)
    all_tally_data = [] 
    
    for dataset, company_name in BQ_DATASETS.items():
        print(f"   -> Querying company dataset: {dataset} ({company_name})...")
        
        query = f"""
            SELECT 
                v.guid,
                v.date AS Voucher_Date,
                v.voucher_type AS Voucher_Type,
                v.party_name AS Particulars,
                v.reference_number AS Invoice_No,
                (SUM(ABS(a.amount)) / 2) AS Invoice_Amount
            FROM `{PROJECT_ID}.{dataset}.trn_voucher` AS v
            LEFT JOIN `{PROJECT_ID}.{dataset}.trn_accounting` AS a 
                ON v.guid = a.guid
            WHERE EXTRACT(MONTH FROM v.date) = {target_month}
              AND EXTRACT(YEAR FROM v.date) = {target_year}
              AND v.voucher_type IN ('Purchase', 'Credit Note', 'Debit Note', 'E Credit Note', 'E-Debit Note')
            GROUP BY 
                v.guid, v.date, v.voucher_type, v.party_name, v.reference_number
        """
        
        try:
            # 🔴 BULLETPROOF 403 BYPASS: Manually unpack rows to strictly force the REST API
            results = client.query(query).result()
            df = pd.DataFrame([dict(row) for row in results])
            
            if not df.empty:
                df['Company_Source'] = company_name 
                all_tally_data.append(df)
            print(f"      Found {len(df)} records in {dataset}.")
        except Exception as e:
            print(f"      ⚠️ Warning: Could not fetch from {dataset}. Error: {e}")
            
    if not all_tally_data:
        raise Exception("❌ No purchase/note data was found in any of the specified BigQuery datasets.")
        
    master_tally_df = pd.concat(all_tally_data, ignore_index=True)
    
    if 'Invoice_Amount' in master_tally_df.columns:
        master_tally_df['Invoice_Amount'] = pd.to_numeric(master_tally_df['Invoice_Amount'], errors='coerce')
        master_tally_df['Invoice_Amount'] = master_tally_df['Invoice_Amount'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "")
    
    print(f"✅ Extracted a total of {len(master_tally_df)} records.")
    return master_tally_df

def create_pdf_report(period_string, total_gst_count, total_tally_count, matched_count, miss_tally, miss_gst):
    """Generates a detailed multi-page PDF report with standardized data tables."""
    print("📝 Generating Detailed PDF Report...")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15) 
    pdf.add_page()
    
    # --- TITLE & SUMMARY ---
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, txt="GST vs Tally Detailed Reconciliation", ln=True, align='C')
    pdf.set_font("Arial", 'I', 12)
    pdf.cell(0, 10, txt=f"Period: {period_string}", ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, txt="EXECUTIVE SUMMARY", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 6, txt=f"Total GST Invoices & Notes: {total_gst_count}", ln=True)
    pdf.cell(0, 6, txt=f"Total Tally Records: {total_tally_count}", ln=True)
    pdf.cell(0, 6, txt=f"Successfully Matched: {matched_count}", ln=True)
    pdf.cell(0, 6, txt=f"Missing in Tally (ITC to claim): {len(miss_tally)}", ln=True)
    pdf.cell(0, 6, txt=f"Missing in GST (Vendor pending): {len(miss_gst)}", ln=True)
    pdf.ln(10)
    
    # --- TABLE GENERATOR HELPER ---
    def draw_table(title, df, columns_to_display):
        if df.empty: return
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt=f"{title} ({len(df)} Records)", ln=True)
        
        pdf.set_font("Arial", 'B', 8)
        col_width = 190 / len(columns_to_display)
        for col in columns_to_display:
            safe_col_name = str(col).encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(col_width, 8, txt=safe_col_name, border=1, align='C')
        pdf.ln()
        
        pdf.set_font("Arial", size=8)
        for _, row in df.iterrows():
            for col in columns_to_display:
                val = str(row.get(col, ""))
                safe_val = val.encode('latin-1', 'replace').decode('latin-1') 
                
                # 🔴 FIX: Dynamically measure and chop the text so it never overlaps the border
                while pdf.get_string_width(safe_val) > (col_width - 2):  # The -2 adds a 1px padding on the sides
                    safe_val = safe_val[:-1]
                    
                pdf.cell(col_width, 6, txt=safe_val, border=1)
            pdf.ln()
        pdf.ln(5)

    # 1. Missing in Tally 
    # 🔴 FIX: Removed 'Type' to stop text overlapping
    gst_cols = ['Vendor', 'Doc Number', 'Date', 'Amount'] 
    draw_table("1. MISSING IN TALLY (Invoices/Notes to Enter)", miss_tally, gst_cols)
    
    # 2. Missing in GST 
    # 🔴 FIX: Removed 'Voucher_Type' to stop text overlapping
    tally_cols = ['Particulars', 'Invoice_No', 'Voucher_Date', 'Invoice_Amount', 'Company_Source']
    draw_table("2. MISSING IN GST (Vendors Haven't Filed)", miss_gst, tally_cols)
    
    pdf_path = os.path.join(DOWNLOAD_DIR, f"Detailed_Reconciliation_{period_string}.pdf")
    pdf.output(pdf_path)
    return pdf_path
    
    # --- TABLE GENERATOR HELPER ---
    def draw_table(title, df, columns_to_display):
        if df.empty: return
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt=f"{title} ({len(df)} Records)", ln=True)
        
        pdf.set_font("Arial", 'B', 8)
        col_width = 190 / len(columns_to_display)
        for col in columns_to_display:
            safe_col_name = str(col)[:25].encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(col_width, 8, txt=safe_col_name, border=1, align='C')
        pdf.ln()
        
        pdf.set_font("Arial", size=8)
        for _, row in df.iterrows():
            for col in columns_to_display:
                val = str(row.get(col, ""))[:25]
                safe_val = val.encode('latin-1', 'replace').decode('latin-1') 
                pdf.cell(col_width, 6, txt=safe_val, border=1)
            pdf.ln()
        pdf.ln(5)

    # 1. Missing in Tally (Standardized Columns for both B2B and CDNR)
    gst_cols = ['Vendor', 'Doc Number', 'Date', 'Amount', 'Type']
    draw_table("1. MISSING IN TALLY (Invoices/Notes to Enter)", miss_tally, gst_cols)
    
    # 2. Missing in GST 
    tally_cols = ['Particulars', 'Invoice_No', 'Voucher_Date', 'Invoice_Amount', 'Voucher_Type', 'Company_Source']
    draw_table("2. MISSING IN GST (Vendors Haven't Filed)", miss_gst, tally_cols)
    
    pdf_path = os.path.join(DOWNLOAD_DIR, f"Detailed_Reconciliation_{period_string}.pdf")
    pdf.output(pdf_path)
    return pdf_path
    
    # --- TABLE GENERATOR HELPER ---
    def draw_table(title, df, columns_to_display):
        if df.empty:
            return
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, txt=f"{title} ({len(df)} Records)", ln=True)
        
        # Print Headers
        pdf.set_font("Arial", 'B', 8)
        col_width = 190 / len(columns_to_display)
        for col in columns_to_display:
            # Clean text to prevent PDF encoding crashes (e.g. Rupee symbols)
            safe_col_name = str(col)[:25].encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(col_width, 8, txt=safe_col_name, border=1, align='C')
        pdf.ln()
        
        # Print Rows
        pdf.set_font("Arial", size=8)
        for _, row in df.iterrows():
            for col in columns_to_display:
                val = str(row.get(col, ""))[:25]
                safe_val = val.encode('latin-1', 'replace').decode('latin-1') 
                pdf.cell(col_width, 6, txt=safe_val, border=1)
            pdf.ln()
        pdf.ln(5)

    # --- DRAW TABLES ---
    # 1. Missing in Tally (Data extracted from GST Portal Excel)
    gst_known_cols = ['Trade/Legal name', 'Invoice number', 'Invoice Date', 'Invoice Value(₹)']
    gst_cols = [c for c in gst_known_cols if c in miss_tally.columns]
    if not gst_cols: gst_cols = list(miss_tally.columns)[:4] # Fallback
    
    draw_table("1. MISSING IN TALLY (Invoices to Enter)", miss_tally, gst_cols)
    
    # 2. Missing in GST (Data extracted from BigQuery)
    tally_cols = ['Invoice_No', 'Voucher_Date', 'Particulars', 'Invoice_Amount', 'Company_Source']
    tally_cols = [c for c in tally_cols if c in miss_gst.columns]
    if not tally_cols: tally_cols = list(miss_gst.columns)[:4] # Fallback
    
    draw_table("2. MISSING IN GST (Vendors Haven't Filed)", miss_gst, tally_cols)
    
    pdf_path = os.path.join(DOWNLOAD_DIR, f"Detailed_Reconciliation_{period_string}.pdf")
    pdf.output(pdf_path)
    return pdf_path


def reconcile_and_upload(gst_file_path, tally_df, period_string, financial_year):
    """Cross-matches B2B and B2B-CDNR sheets and pushes to Workspace."""
    print("🔄 Starting Advanced Dual-Core Reconciliation Engine...")
    
    try: 
        # LOAD B2B
        gst_b2b_df = pd.read_excel(gst_file_path, sheet_name='B2B', skiprows=5)
        b2b_rename_map = {'Unnamed: 0': 'GSTIN of supplier', 'Unnamed: 1': 'Trade/Legal name', 'Unnamed: 6': 'Place of supply', 'Unnamed: 7': 'Reverse Charge', 'Unnamed: 8': 'Taxable Value (₹)', 'Unnamed: 13': 'GSTR-1 Period', 'Unnamed: 14': 'Filing Date', 'Unnamed: 15': 'ITC Availability', 'Unnamed: 16': 'Reason', 'Unnamed: 17': 'Applicable Tax Rate (%)', 'Unnamed: 18': 'Source', 'Unnamed: 19': 'IRN', 'Unnamed: 20': 'IRN Date'}
        gst_b2b_df.rename(columns=b2b_rename_map, inplace=True)
        
        # LOAD CDNR (With crash protection if there are no notes this month)
        try:
            gst_cdnr_df = pd.read_excel(gst_file_path, sheet_name='B2B-CDNR', skiprows=5)
            cdnr_rename_map = {'Unnamed: 0': 'GSTIN of supplier', 'Unnamed: 1': 'Trade/Legal name', 'Unnamed: 2': 'Note number', 'Unnamed: 3': 'Note type', 'Unnamed: 4': 'Note Supply type', 'Unnamed: 5': 'Note date', 'Unnamed: 6': 'Note Value (₹)', 'Unnamed: 7': 'Place of supply', 'Unnamed: 8': 'Reverse Charge', 'Unnamed: 9': 'Taxable Value (₹)'}
            gst_cdnr_df.rename(columns=cdnr_rename_map, inplace=True)
        except ValueError:
            print("   ℹ️ No B2B-CDNR sheet found in GST file (No notes this month).")
            gst_cdnr_df = pd.DataFrame(columns=['Trade/Legal name', 'Note number', 'Note date', 'Note Value (₹)'])
            
    except Exception as e: 
        raise Exception(f"❌ Failed to load GST Excel sheets. Error: {e}")
        
    print("⚖️ Splitting and matching data sets...")
    # SPLIT TALLY DATA
    tally_purchases = tally_df[tally_df['Voucher_Type'] == 'Purchase'].copy()
    tally_notes = tally_df[tally_df['Voucher_Type'] != 'Purchase'].copy()
    
    # --- ROUTINE 1: MATCH B2B PURCHASES (By Invoice Number) ---
    gst_b2b_df['Match_Key'] = gst_b2b_df.get('Invoice number', pd.Series()).astype(str).str.strip().str.upper()
    tally_purchases['Match_Key'] = tally_purchases['Invoice_No'].astype(str).str.strip().str.upper()
    merged_b2b = pd.merge(gst_b2b_df, tally_purchases, on='Match_Key', how='outer', indicator=True)
    
    miss_tally_b2b = merged_b2b[merged_b2b['_merge'] == 'left_only'].copy()
    miss_gst_b2b = merged_b2b[merged_b2b['_merge'] == 'right_only'].copy()
    matched_b2b = merged_b2b[merged_b2b['_merge'] == 'both'].copy()
    
    # --- ROUTINE 2: MATCH CDNR NOTES (By Vendor Name + Amount) ---
    gst_cdnr_df['Clean_Name'] = gst_cdnr_df.get('Trade/Legal name', pd.Series()).astype(str).str.strip().str.upper()
    gst_cdnr_df['Clean_Amount'] = pd.to_numeric(gst_cdnr_df.get('Note Value (₹)', pd.Series()), errors='coerce').apply(lambda x: f"{x:.2f}" if pd.notna(x) else "")
    gst_cdnr_df['Match_Key'] = gst_cdnr_df['Clean_Name'] + "_" + gst_cdnr_df['Clean_Amount']
    
    tally_notes['Clean_Name'] = tally_notes['Particulars'].astype(str).str.strip().str.upper()
    tally_notes['Clean_Amount'] = pd.to_numeric(tally_notes['Invoice_Amount'], errors='coerce').apply(lambda x: f"{x:.2f}" if pd.notna(x) else "")
    tally_notes['Match_Key'] = tally_notes['Clean_Name'] + "_" + tally_notes['Clean_Amount']
    
    merged_cdnr = pd.merge(gst_cdnr_df, tally_notes, on='Match_Key', how='outer', indicator=True)
    
    miss_tally_cdnr = merged_cdnr[merged_cdnr['_merge'] == 'left_only'].copy()
    miss_gst_cdnr = merged_cdnr[merged_cdnr['_merge'] == 'right_only'].copy()
    matched_cdnr = merged_cdnr[merged_cdnr['_merge'] == 'both'].copy()
    
    # --- CONSOLIDATE FOR REPORTING ---
    print("📊 Consolidating reports...")
    
    # Standardize 'Missing in Tally' columns for clean combined viewing
    def format_tally_missing(df_b2b, df_cdnr):
        res_b2b = df_b2b[['Trade/Legal name', 'Invoice number', 'Invoice Date', 'Invoice Value(₹)']].copy() if not df_b2b.empty else pd.DataFrame(columns=['Vendor', 'Doc Number', 'Date', 'Amount'])
        res_b2b.columns = ['Vendor', 'Doc Number', 'Date', 'Amount']
        res_b2b['Type'] = 'Purchase'
        
        res_cdnr = df_cdnr[['Trade/Legal name', 'Note number', 'Note date', 'Note Value (₹)']].copy() if not df_cdnr.empty else pd.DataFrame(columns=['Vendor', 'Doc Number', 'Date', 'Amount'])
        res_cdnr.columns = ['Vendor', 'Doc Number', 'Date', 'Amount']
        res_cdnr['Type'] = 'CDNR Note'
        
        return pd.concat([res_b2b, res_cdnr], ignore_index=True).fillna("")
        
    final_missing_tally = format_tally_missing(miss_tally_b2b, miss_tally_cdnr)
    
    # Standardize 'Missing in GST'
    final_missing_gst = pd.concat([miss_gst_b2b, miss_gst_cdnr], ignore_index=True)
    tally_keep_cols = ['Particulars', 'Invoice_No', 'Voucher_Date', 'Invoice_Amount', 'Voucher_Type', 'Company_Source']
    final_missing_gst = final_missing_gst[[c for c in tally_keep_cols if c in final_missing_gst.columns]].fillna("")
    
    # Combine Raw Matched data for the Excel file
    final_matched = pd.concat([matched_b2b, matched_cdnr], ignore_index=True).drop(columns=['_merge', 'Match_Key', 'Clean_Name', 'Clean_Amount'], errors='ignore').fillna("")

    # --- UPLOAD TO GOOGLE WORKSPACE ---
    print("☁️ Connecting to Google Workspace...")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    drive_service = build('drive', 'v3', credentials=creds)
    
    fy_folder_name = f"FY {financial_year}"
    query = f"name='{fy_folder_name}' and '{DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    
    results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)', includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
    items = results.get('files', [])
    
    if not items:
        print(f"📁 Creating new folder for {fy_folder_name}...")
        folder_metadata = {'name': fy_folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [DRIVE_FOLDER_ID]}
        folder = drive_service.files().create(body=folder_metadata, fields='id', supportsAllDrives=True).execute()
        fy_folder_id = folder.get('id')
    else:
        fy_folder_id = items[0]['id']
        print(f"📁 Found existing folder for {fy_folder_name}.")
        
    print(f"📈 Creating new spreadsheet for {period_string}...")
    gc = gspread.authorize(creds)
    sheet_name = f"{period_string.replace('_', ' ')} Reconciliation" 
    
    sheet_metadata = {'name': sheet_name, 'mimeType': 'application/vnd.google-apps.spreadsheet', 'parents': [fy_folder_id]}
    sheet_file = drive_service.files().create(body=sheet_metadata, fields='id', supportsAllDrives=True).execute()
    sh = gc.open_by_key(sheet_file.get('id'))
    
    def setup_tab(title, dataframe, is_first=False):
        if is_first:
            worksheet = sh.sheet1
            worksheet.update_title(title)
        else:
            worksheet = sh.add_worksheet(title=title, rows=max(100, len(dataframe)+10), cols=max(10, len(dataframe.columns)))
        if not dataframe.empty:
            clean_df = dataframe.astype(str)
            worksheet.update([clean_df.columns.values.tolist()] + clean_df.values.tolist())

    setup_tab("Missing in Tally", final_missing_tally, is_first=True)
    setup_tab("Missing in GST", final_missing_gst)
    setup_tab("Matched", final_matched)
    setup_tab("Raw GST B2B", gst_b2b_df.drop(columns=['Match_Key'], errors='ignore').fillna(""))
    setup_tab("Raw GST CDNR", gst_cdnr_df.drop(columns=['Match_Key', 'Clean_Name', 'Clean_Amount'], errors='ignore').fillna(""))
    setup_tab("Raw Tally Data", tally_df.drop(columns=['Match_Key', 'Clean_Name', 'Clean_Amount'], errors='ignore').fillna(""))
    
    # 🔴 GENERATE PDF
    total_gst_invoices = len(gst_b2b_df) + len(gst_cdnr_df)
    pdf_path = create_pdf_report(period_string, total_gst_invoices, len(tally_df), len(final_matched), final_missing_tally, final_missing_gst)
    
    # 🔴 GENERATE EXCEL FILE
    excel_path = os.path.join(DOWNLOAD_DIR, f"Reconciliation_{period_string}.xlsx")
    print("📊 Generating local Excel file for WhatsApp...")
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        final_missing_tally.to_excel(writer, sheet_name="Missing in Tally", index=False)
        final_missing_gst.to_excel(writer, sheet_name="Missing in GST", index=False)
        final_matched.to_excel(writer, sheet_name="Matched", index=False)
        gst_b2b_df.drop(columns=['Match_Key'], errors='ignore').to_excel(writer, sheet_name="Raw GST B2B", index=False)
        gst_cdnr_df.drop(columns=['Match_Key', 'Clean_Name', 'Clean_Amount'], errors='ignore').to_excel(writer, sheet_name="Raw GST CDNR", index=False)
        tally_df.drop(columns=['Match_Key', 'Clean_Name', 'Clean_Amount'], errors='ignore').to_excel(writer, sheet_name="Raw Tally Data", index=False)

    file_metadata = {'name': os.path.basename(pdf_path), 'parents': [fy_folder_id]}
    media = MediaFileUpload(pdf_path, mimetype='application/pdf')
    drive_service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
    
    print(f"🎉 SUCCESS! Data uploaded to Sheets and PDF/Excel generated inside {fy_folder_name}")
    return pdf_path, excel_path
    
    def setup_tab(title, dataframe, is_first=False):
        if is_first:
            worksheet = sh.sheet1
            worksheet.update_title(title)
        else:
            worksheet = sh.add_worksheet(title=title, rows=max(100, len(dataframe)+10), cols=max(20, len(dataframe.columns)))
        if not dataframe.empty:
            # 🔴 FIX: Cast the entire DataFrame to strings so JSON can securely transmit dates
            clean_df = dataframe.astype(str)
            worksheet.update([clean_df.columns.values.tolist()] + clean_df.values.tolist())

    setup_tab("Missing in Tally", missing_in_tally, is_first=True)
    setup_tab("Missing in GST", missing_in_gst)
    setup_tab("Matched", matched)
    setup_tab("Raw GST Data", gst_df.fillna(""))
    setup_tab("Raw Tally Data", tally_df.fillna(""))
    
    pdf_path = create_pdf_report(period_string, gst_df, tally_df, matched, missing_in_tally, missing_in_gst)
    
    file_metadata = {'name': os.path.basename(pdf_path), 'parents': [fy_folder_id]}
    media = MediaFileUpload(pdf_path, mimetype='application/pdf')
    
    # 🔴 Added supportsAllDrives=True
    uploaded_pdf = drive_service.files().create(
        body=file_metadata, media_body=media, fields='id', supportsAllDrives=True
    ).execute()
    
    print(f"🎉 SUCCESS! Data uploaded to Sheets and PDF generated inside {fy_folder_name}")
    return pdf_path

    def setup_tab(title, dataframe, is_first=False):
        if is_first:
            worksheet = sh.sheet1
            worksheet.update_title(title)
        else:
            worksheet = sh.add_worksheet(title=title, rows=max(100, len(dataframe)+10), cols=max(20, len(dataframe.columns)))
        if not dataframe.empty:
            worksheet.update([dataframe.columns.values.tolist()] + dataframe.values.tolist())

    setup_tab("Missing in Tally", missing_in_tally, is_first=True)
    setup_tab("Missing in GST", missing_in_gst)
    setup_tab("Matched", matched)
    setup_tab("Raw GST Data", gst_df.fillna(""))
    setup_tab("Raw Tally Data", tally_df.fillna(""))
    
    pdf_path = create_pdf_report(period_string, len(gst_df), len(tally_df), len(matched), len(missing_in_tally), len(missing_in_gst))
    
    file_metadata = {'name': os.path.basename(pdf_path), 'parents': [fy_folder_id]}
    media = MediaFileUpload(pdf_path, mimetype='application/pdf')
    
    # 🔴 Added supportsAllDrives=True
    uploaded_pdf = drive_service.files().create(
        body=file_metadata, media_body=media, fields='id', supportsAllDrives=True
    ).execute()
    
    print(f"🎉 SUCCESS! Data uploaded to Sheets and PDF generated inside {fy_folder_name}")
    return pdf_path
    

def send_document_via_whatsapp(file_path, period_string, mime_type="application/pdf"):
    """Uploads any document to WhatsApp's server and sends it to the target number."""
    doc_type = "PDF" if "pdf" in mime_type else "Excel"
    print(f"📲 Initiating WhatsApp API transfer for {doc_type}...")
    media_url = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/media"
    headers = {"Authorization": f"Bearer {WA_TOKEN}"}
    
    with open(file_path, "rb") as file_data:
        files = {
            "file": (os.path.basename(file_path), file_data, mime_type),
            "type": (None, "document"),
            "messaging_product": (None, "whatsapp")
        }
        upload_response = requests.post(media_url, headers=headers, files=files)
        
    upload_result = upload_response.json()
    media_id = upload_result.get("id")
    if not media_id: raise Exception(f"❌ WhatsApp Media Upload Failed: {upload_response.text}")
        
    message_url = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"
    
    # Attempt 1: Standard Document Message
    payload = {
        "messaging_product": "whatsapp",
        "to": SEND_TO_NUMBER,
        "type": "document",
        "document": {
            "id": media_id,
            "caption": f"📊 GST vs Tally {doc_type} Report for {period_string}",
            "filename": os.path.basename(file_path)
        }
    }
    
    msg_headers = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
    msg_response = requests.post(message_url, headers=msg_headers, json=payload)
    
    if msg_response.status_code == 200: 
        print(f"✅ SUCCESS! {doc_type} delivered via WhatsApp.")
    else: 
        print(f"⚠️ Direct Delivery Failed. Initiating Template Fallback...")
        # Attempt 2: Template Fallback (Bypasses 24-hour rule)
        template_payload = {
            "messaging_product": "whatsapp",
            "to": SEND_TO_NUMBER,
            "type": "template",
            "template": {
                "name": WA_TEMPLATE,
                "language": {"code": WA_LANG},
                "components": [{
                    "type": "header",
                    "parameters": [{
                        "type": "document",
                        "document": {"id": media_id, "filename": os.path.basename(file_path)}
                    }]
                }]
            }
        }
        temp_response = requests.post(message_url, headers=msg_headers, json=template_payload)
        if temp_response.status_code == 200:
            print(f"✅ SUCCESS! {doc_type} delivered via WhatsApp Template.")
        else:
            print(f"❌ Template Fallback Error: {temp_response.text}")

def run_master_bot():
    """Main Execution Flow Orchestrator"""
    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": DOWNLOAD_DIR, 
        "download.prompt_for_download": False,      
        "directory_upgrade": True,
        "safebrowsing.enabled": True                
    }
    options.add_experimental_option("prefs", prefs)
    
    # 🔴 READS YOUR TERMINAL COMMAND
    if "--visible" in sys.argv:
        print("Running Chrome in visible testing mode...")
    else:
        print("Running Chrome in invisible server mode...")
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-sandbox')
    
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 30)
    
    try:
        # 1. Start GST Scraping
        fin_year, qtr, month_period, target_month, target_year = get_dynamic_gst_dates(OVERRIDE_MONTH, OVERRIDE_YEAR)
        period_string = f"{month_period}_{target_year}"
        
        driver.get("https://services.gst.gov.in/services/login")
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(GST_USERNAME)
        driver.find_element(By.ID, "user_pass").send_keys(GST_PASSWORD)
        
        captcha_img = wait.until(EC.presence_of_element_located((By.ID, "imgCaptcha")))
        driver.find_element(By.ID, "captcha").send_keys(solve_captcha_2captcha(driver, captcha_img))
        
        login_btn = driver.find_element(By.XPATH, "//button[@type='submit' and contains(text(), 'Login')]")
        driver.execute_script("arguments[0].click();", login_btn)
        
        wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Services')]")))
        time.sleep(3)
        
        try:
            services_btn = driver.find_element(By.XPATH, "//a[contains(text(), 'Services') and contains(@class, 'dropdown-toggle')]")
            driver.execute_script("arguments[0].click();", services_btn)
            time.sleep(1.5)
            returns_tab = driver.find_element(By.XPATH, "//a[normalize-space(text())='Returns']")
            driver.execute_script("arguments[0].click();", returns_tab)
            time.sleep(1.5)
            returns_dashboard = driver.find_element(By.XPATH, "//a[normalize-space(text())='Returns Dashboard']")
            driver.execute_script("arguments[0].click();", returns_dashboard)
        except Exception:
            driver.get("https://return.gst.gov.in/returns/auth/dashboard")
            
        time.sleep(3) 
        
        select_angular_option(driver, wait, "fin", fin_year)
        select_angular_option(driver, wait, "quarter", qtr)
        select_angular_option(driver, wait, "mon", month_period)
        
        search_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'srchbtn') or contains(text(), 'Search')]")))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_btn)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", search_btn)
        time.sleep(6) 
        
        possible_xpaths = [
            "//p[contains(normalize-space(text()), 'GSTR-2B')]/following::button[contains(text(), 'View') or contains(text(), 'VIEW')][1]",
            "//*[contains(normalize-space(text()), 'GSTR-2B')]/following::button[contains(text(), 'View') or contains(text(), 'VIEW')][1]",
            "//div[contains(., 'GSTR-2B') and not(contains(., 'GSTR-1')) and not(contains(., 'GSTR-3B'))]//button[contains(text(), 'View') or contains(text(), 'VIEW')]"
        ]
        
        gstr2b_view_btn = None
        for xpath in possible_xpaths:
            try:
                gstr2b_view_btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                if gstr2b_view_btn: break
            except: continue
                
        if not gstr2b_view_btn: raise Exception("❌ Could not isolate the GSTR-2B View button.")
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", gstr2b_view_btn)
        time.sleep(1.5)
        driver.execute_script("arguments[0].click();", gstr2b_view_btn)
        time.sleep(3) 
        
        download_xpath = "//button[contains(normalize-space(text()), 'DOWNLOAD GSTR-2B DETAILS (EXCEL)')]"
        download_excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, download_xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", download_excel_btn)
        time.sleep(1.5)
        driver.execute_script("arguments[0].click();", download_excel_btn)
        
        time.sleep(2)
        driver.quit()
        
        # 2. Extract, Reconcile, Upload and Send
        downloaded_excel_path = wait_for_download(DOWNLOAD_DIR)
        tally_df = extract_tally_purchases_from_bq(target_month, target_year)
        
        # Unpack both the PDF and Excel file paths
        generated_pdf_path, generated_excel_path = reconcile_and_upload(downloaded_excel_path, tally_df, period_string, fin_year)
        
        # Send PDF
        send_document_via_whatsapp(generated_pdf_path, period_string, "application/pdf")
        # Send Excel
        send_document_via_whatsapp(generated_excel_path, period_string, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        # 🔴 CLEANUP ROUTINE
        print("\n🧹 Cleaning up local temporary files...")
        files_to_delete = [
            downloaded_excel_path, 
            generated_pdf_path,
            generated_excel_path,
            os.path.join(DOWNLOAD_DIR, "gst_captcha.png")
        ]
        
        for f_path in files_to_delete:
            if f_path and os.path.exists(f_path):
                try:
                    os.remove(f_path)
                    print(f"   -> Deleted: {os.path.basename(f_path)}")
                except Exception as del_err:
                    print(f"   ⚠️ Could not delete {os.path.basename(f_path)}: {del_err}")
                    
        print("🚀 Automation Complete! Environment is clean.")
        
    except Exception as e:
        print("\n❌ An error occurred during execution:")
        traceback.print_exc()
        try: driver.quit() 
        except: pass

if __name__ == "__main__":
    run_master_bot()