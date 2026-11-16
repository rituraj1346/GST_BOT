# GST Bot — GST vs Tally Reconciliation

Automates monthly reconciliation of GST portal data (GSTR-2B) against Tally purchase vouchers stored in BigQuery.

Each run:
1. Logs into the GST portal with Selenium (captcha solved via 2Captcha) and downloads the GSTR-2B Excel for the target month.
2. Pulls Tally purchase vouchers from BigQuery (`trn_voucher` across the Hardware, Paints, Tiles and Grocery datasets).
3. Matches invoices and finds entries missing from either side.
4. Uploads the results to Google Sheets/Drive, builds a PDF summary, and sends it over the WhatsApp Business API.

## Scripts

| Script | GSTIN / Drive folder env vars |
|---|---|
| `gst_bot.py` | `MAIN_*` |
| `gst_bot_AP.py` | `AP_*` |
| `gst_bot_P_R.py` | `PR_*` |
| `run_reconciliation.bat` | Runs `gst_bot.py` for scheduled (Task Scheduler) use |

## Setup

```bash
pip install pandas requests gspread google-cloud-bigquery google-auth google-api-python-client fpdf selenium python-dotenv openpyxl
```

Requires Google Chrome. Put the Google service-account JSON key in the project folder (filename is set in `SERVICE_ACCOUNT_FILE`).

Create a `.env`:

```env
TWOCAPTCHA_API_KEY=

MAIN_GST_USERNAME=
MAIN_GST_PASSWORD=
MAIN_DRIVE_FOLDER_ID=

AP_GST_USERNAME=
AP_GST_PASSWORD=
AP_DRIVE_FOLDER_ID=

PR_GST_USERNAME=
PR_GST_PASSWORD=
PR_DRIVE_FOLDER_ID=

WA_PHONE_ID=
WA_BUSINESS_ID=
WA_TOKEN=
SEND_TO_NUMBER=
```

`.env` and `*.json` are git-ignored — never commit credentials.

## Usage

```bash
python gst_bot.py            # headless Chrome (server mode)
python gst_bot.py --visible  # show the browser for debugging
```

The target month is calculated automatically. To re-run a past month, set `OVERRIDE_MONTH` / `OVERRIDE_YEAR` at the top of the script.

Logs are written to `server_logs.log`.

## License

[MIT](LICENSE)
