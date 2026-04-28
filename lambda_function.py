import json
import os
import urllib.request
import pikepdf
import pdfplumber
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from decimal import Decimal
from collections import defaultdict
import boto3
from boto3.dynamodb.conditions import Attr
import uuid
from datetime import datetime
import hashlib
import time
import calendar
import smtplib
from email.mime.text import MIMEText
from jinja2 import Template
from dateutil.relativedelta import relativedelta

# 👉 DynamoDB connection
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
table = dynamodb.Table("transactions")

FOLDER_ID = os.environ.get("FOLDER_ID")


# Google Drive से credentials fetch करने का function
def get_credentials():
    creds_json = os.environ.get("GOOGLE_CREDS")

    if not creds_json:
        raise Exception("GOOGLE_CREDS missing ❌")

    creds_dict = json.loads(creds_json)

    return service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive"]
    )

# Google Drive से file download करने का function
def download_file(file_id, filename):
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)

    request = drive.files().get_media(fileId=file_id)

    filepath = f"/tmp/{filename}"

    with open(filepath, "wb") as f:
        f.write(request.execute())

    return filepath

# PDF decryption function using pikepdf
def decrypt_pdf(input_path, output_path, password):
    if not password:
        raise Exception("PDF_PASSWORD missing ❌")

    with pikepdf.open(input_path, password=password) as pdf:
        pdf.save(output_path)

# Google Drive से सभी PDF files को list करने का function
def get_all_pdfs():
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)

    results = drive.files().list(
        q=f"'{FOLDER_ID}' in parents and mimeType='application/pdf'",
        fields="files(id, name)"
    ).execute()

    files = results.get("files", [])

    if not files:
        raise Exception("No PDF found in folder ❌")

    return files

# API hit करने का function (agar future me koi API call karna ho to)
def hit_endpoint():
    try:
        url = os.environ.get("GOOGLE_APP_URL")

        if not url:
            raise Exception("GOOGLE_APP_URL missing ❌")

        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())

        return data

    except Exception as e:
        print("❌ API Error:", str(e))
        return None

# Cleanup API hit karne ka function (agar future me koi cleanup API call karna ho to)
def clean_endpoint():
    try:
        url = os.environ.get("GOOGLE_APP_CLEAN_URL")

        if not url:
            raise Exception("GOOGLE_APP_CLEAN_URL missing ❌")

        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
      #print("✅ Cleanup API Response:", data)
        return data

    except Exception as e:
        print("❌ API Error:", str(e))
        return None

# helper to convert string amounts to Decimal (DynamoDB compatible)
def to_decimal(value):
    if not value:
        return Decimal("0.0")

    # remove commas + junk
    value = re.sub(r"[^\d.]", "", str(value))

    return Decimal(value) if value else Decimal("0.0")

# helper to generate unique transaction ID based on txn details
def generate_txn_id(txn):
    raw = f"{txn.get('date')}-{txn.get('balance')}-{txn.get('deposit')}-{txn.get('withdrawal')}"
    return hashlib.md5(raw.encode()).hexdigest()

# function to save transactions in bulk to DynamoDB
def save_transactions_bulk(transactions, bank, user_id=os.environ.get("DEVELOP_BY")):
    try:
      #print("🚀 Starting bulk insert of transactions")
      #print(transactions)
        with table.batch_writer() as batch:
            for txn in transactions:
              #print(f"Saving txn: {txn}")
                item = {
                    "user_id": user_id,
                    "bank": bank,
                    "txn_id": generate_txn_id(txn),
                    "date": txn.get("date"),
                    "particulars": txn.get("particulars"),
                    "deposit": to_decimal(txn.get("deposit")),
                    "withdrawal": to_decimal(txn.get("withdrawal")),
                    "balance": to_decimal(txn.get("balance")),
                }
                batch.put_item(Item=item)
      #print("🚀 Bulk insert done")

    except Exception as e:
        print("❌ Bulk Error:", str(e))

# function to read text from decrypted PDF using pdfplumber
def read_drive_files():
    try:
        import pdfplumber

        all_text = []

        with pdfplumber.open("/tmp/decrypted.pdf") as pdf:
          #print("📄 Extracted Text:\n")

            for i, page in enumerate(pdf.pages):
                text = page.extract_text()

                # print(f"--- Page {i+1} ---")
                # print(text if text else "[No text found]")

                if text:
                    all_text.append(text)

        return "\n".join(all_text)   # 👈 IMPORTANT

    except Exception as e:
        print("❌ read_drive_files:", str(e))
        return None

# Improved particulars cleaner with stronger regex to remove IDs, UPI refs, and trailing garbage
def clean_particulars(text, max_len=120):
    # remove long IDs
    text = re.sub(r'\b[A-Z0-9]{10,}\b', '', text)

    # remove UPI reference junk
    text = re.sub(r'IN/\d+/', '', text)

    # remove trailing garbage
    text = re.sub(r'[a-f0-9]{6,}', '', text)

    # clean spaces
    text = re.sub(r'\s+', ' ', text)

    return text.strip()[:max_len]

# Improved parser with better handling of multi-line particulars and stronger garbage filtering
def parse_bank_statement(input_text):
    date_pattern = r'^(\d{2}-\d{2}-\d{4})'
    amount_pattern = r'(\d+(?:,\d+)*(?:\.\d{2})?)'

    lines = input_text.split('\n')
    transactions = []
    current_tx = None
    prev_balance = 0.0

    before_buffer = []
    after_buffer = []
    collect_after = False

    def to_float(amt_str):
        return float(amt_str.replace(',', ''))

    # 🔥 strong garbage filter
    def is_garbage(line):
        line = line.strip().lower()

        # random ids / hashes
        if re.match(r'^[a-z0-9]{10,}$', line):
            return True

        # bank noise
        if any(x in line for x in ["bankp", "ibl", "upi//", "///"]):
            return True

        # only numbers
        if re.match(r'^\d+$', line):
            return True

        return False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        date_match = re.match(date_pattern, line)

        # =========================
        # 🔥 DATE LINE
        # =========================
        if date_match:
            # save previous
            if current_tx:
                transactions.append(current_tx)

            tx_date = date_match.group(1)
            amounts = re.findall(amount_pattern, line)

            # remove date
            line_text = re.sub(date_pattern, '', line).strip()

            # 🔥 combine CLEAN before + after
            clean_before = [l for l in before_buffer if not is_garbage(l)]
            clean_after = [l for l in after_buffer if not is_garbage(l)]

            full_text = " ".join(clean_before + [line_text] + clean_after).strip()

            # reset buffers
            before_buffer = []
            after_buffer = []
            collect_after = True

            # B/F skip
            if "B/F" in line or "BROUGHT FORWARD" in line.upper():
                if amounts:
                    prev_balance = to_float(amounts[-1])
                current_tx = None
                continue

            if amounts:
                current_balance = to_float(amounts[-1])
                change = round(current_balance - prev_balance, 2)

                deposit = change if change > 0 else 0.0
                withdrawal = abs(change) if change < 0 else 0.0

                current_tx = {
                    "date": tx_date,
                    "particulars": clean_particulars(full_text),
                    "deposit": deposit,
                    "withdrawal": withdrawal,
                    "balance": current_balance
                }

                prev_balance = current_balance

        # =========================
        # 🔥 NON-DATE LINE
        # =========================
        else:
            clean_line = line.strip()

            if any(x in clean_line for x in ["Page", "MR.", "TOTAL", "Statement"]):
                continue

            # BEFORE lines
            if not collect_after:
                before_buffer.append(clean_line)

            # AFTER lines
            else:
                after_buffer.append(clean_line)

    if current_tx:
        transactions.append(current_tx)

    return transactions

# function to determine PDF password based on file name
def get_file_password(file_name):
    try:
        # Example: "HDFC_Statement_March.pdf" → "March"
        if file_name.startswith("Account") and file_name.endswith(".pdf"):
            passwoord_val = os.environ.get("HDFC_PASSWORD")
        else:
            passwoord_val = os.environ.get("ICICI_PASSWORD")
        return passwoord_val
    except Exception as e:
        print("❌ Password Extraction Error:", str(e))
        return None

# Improved HDFC parser with better handling of multi-line narration and balance difference logic
def parse_hdfc_text(text):
    lines = text.split("\n")
    transactions = []

    prev_balance = None
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if re.match(r"\d{2}/\d{2}/\d{2}", line):
            parts = line.split()

            try:
                date_raw = parts[0]
                date_obj = datetime.strptime(date_raw, "%d/%m/%y")
                date = date_obj.strftime("%d-%m-%Y")

                # balance (last column)
                balance = float(parts[-1].replace(",", ""))

                # narration
                narration = " ".join(parts[1:-2])

                # multiline narration
                if i + 1 < len(lines) and not re.match(r"\d{2}/\d{2}/\d{2}", lines[i+1]):
                    narration += " " + lines[i+1].strip()
                    i += 1

                # 🔥 NEW LOGIC (balance difference)
                deposit = 0.0
                withdrawal = 0.0

                if prev_balance is not None:
                    diff = round(balance - prev_balance, 2)

                    if diff > 0:
                        deposit = diff
                    elif diff < 0:
                        withdrawal = abs(diff)

                # first transaction fallback
                else:
                    amount = float(parts[-2].replace(",", ""))
                    if "CREDIT" in line.upper():
                        deposit = amount
                    else:
                        withdrawal = amount

                transactions.append({
                    "date": date,
                    "particulars": narration.strip(),
                    "deposit": deposit,
                    "withdrawal": withdrawal,
                    "balance": balance
                })

                prev_balance = balance

            except Exception:
                pass

        i += 1

    return transactions

# Main function to orchestrate the flow: download, decrypt, read, parse, and save
def download_and_decrypt_pdf():
    try:
       #👉 get PDF
        pdf_files = get_all_pdfs()
      #print("📄 Found PDFs:", pdf_files)

        for pdf in pdf_files:
            try:
                file_id = pdf["id"]
                file_name = pdf["name"]

              #print(f"📄 Processing: {file_name}")

                # 👉 download
                input_path = download_file(file_id, "input.pdf")

                output_path = f"/tmp/decrypted.pdf"

                decrypt_pdf(input_path, output_path, get_file_password(file_name))
                # print("✅ Decrypted file saved at:", output_path)
                text_data = read_drive_files()
                # Example usage:
              #print("📊 Extracted Text Data:\n", text_data)  # print first 500 chars
                if file_name.startswith("Account") and file_name.endswith(".pdf"):
                    # print("📊 Parsing with HDFC logic")
                    bank = "hdfc"
                    json_output = parse_hdfc_text(text_data)
                else:
                  #print("📊 Parsing with Generic logic")
                    bank = "icici"
                    json_output = parse_bank_statement(text_data)
                save_transactions_bulk(json_output, bank)
              #print("✅ Finished Decryption Only Flow")
            finally:
                # 🧹 cleanup (har baar chalega even if error aaye)
                for f in ["/tmp/input.pdf", "/tmp/decrypted.pdf"]:
                    if os.path.exists(f):
                        os.remove(f)
                        print(f"🧹 Deleted: {f}")
        
    except Exception as e:
        print("❌ Error in download_and_decrypt_pdf:", str(e))
        return None

# helper to calculate percentage change between two values (for SES reporting)
def calc_percentage_change(current, previous):
    if previous == 0:
        return "0%"   # ya handle separately
    
    change = ((current - previous) / previous) * 100
    
    sign = "+" if change >= 0 else ""
    return f"{sign}{round(change, 2)}%"


# SES template creation function (run once to create template in SES)
def create_ses_template():
    try:
        client = boto3.client("sesv2", region_name="ap-south-1")
        with open("template.html", "r", encoding="utf-8") as f:
            html = f.read()
        client.create_email_template(
            TemplateName="financial-report-template",
            TemplateContent={
                "Subject": "Your Financial Report",
                "Html": html
            }
        )
      #print("Template created ✅")
    except Exception as e:
        print("❌ SES Template Error:", str(e))

# function to send email using SES with the prepared template data
def send_to_ses(template_data):
    try:
        # SES client
        client = boto3.client("sesv2", region_name="ap-south-1")

        response = client.send_email(
            FromEmailAddress=os.environ.get("FROM_EMAIL"),
            Destination={
                "ToAddresses": [os.environ.get("RECIPIENT_EMAIL")]  # receiver (sandbox me verified hona chahiye)
            },
            Content={
                "Template": {
                    "TemplateName": os.environ.get("TEMPLATE_NAME"),  # jo template create kiya hai SES me
                    "TemplateData": json.dumps(template_data)  # data to fill in template
                }
            }
        )

      #print("Email sent ✅", response)
    except Exception as e:
        print("❌ SES Error:", str(e)) 

# helper to safely parse numbers from strings (handles commas, currency symbols, and empty values)
def parse_number(value):
    if value is None:
        return 0.0

    # अगर already Decimal है
    if isinstance(value, Decimal):
        return float(value)

    # अगर string है
    if isinstance(value, str):
        value = value.strip()

        # handle "Decimal(123.45)"
        if value.startswith("Decimal("):
            value = value.replace("Decimal(", "").replace(")", "")

        try:
            return float(value)
        except ValueError:
            return 0.0

    # अगर int/float है
    if isinstance(value, (int, float)):
        return float(value)

    return 0.0

# helper to clean amount strings (remove ₹, commas, and convert to int)
def clean_amount(val):
    if not val:
        return 0
    
    return int(
        val.replace("₹", "")
           .replace(",", "")
           .strip()
    )

# function to save period-wise summary data in DynamoDB (for SES reporting)
def save_period_data(user, template_data):
    dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
    table = dynamodb.Table('period-wise-transaction')

     # extract "Apr 2026"
    month_str = template_data["period"].split("-")[0].strip()[3:]   # "Apr 2026"
    current_date = datetime.strptime(month_str, "%b %Y")

    prev_date = current_date - relativedelta(months=1)

    current_month = current_date.strftime("%b %Y")   # Apr 2026
    prev_month = prev_date.strftime("%b %Y")         # Mar 2026

    response = table.scan()

    prev_items = [
        item for item in response.get("Items", [])
        if prev_month in item.get("period", "")
    ]

    prev_item = prev_items[0] if prev_items else None
    item = {
        "user": user,
        "period": template_data["period"],
        "passive_change": calc_percentage_change( clean_amount(template_data["total_passive"]), clean_amount(prev_item['total_passive']) if prev_item else 0.0),  # example change calculation
        "spend_change": calc_percentage_change(clean_amount(template_data["total_spends"]), clean_amount(prev_item['total_spends']) if prev_item else 0.0),  # example change calculation
        "hdfc_name": template_data["hdfc_name"],
        "hdfc_balance": template_data["hdfc_balance"],
        "hdfc_salary": template_data["hdfc_salary"],
        "hdfc_passive": template_data["hdfc_passive"],
        "hdfc_spends": template_data["hdfc_spends"],
        "hdfc_highest": template_data["hdfc_highest"],

        "icici_name": template_data["icici_name"],
        "icici_balance": template_data["icici_balance"],
        "icici_salary": template_data["icici_salary"],
        "icici_passive": template_data["icici_passive"],
        "icici_spends": template_data["icici_spends"],
        "icici_highest": template_data["icici_highest"],

        "total_balance": template_data["total_balance"],
        "total_income": template_data["total_income"],
        "total_passive": template_data["total_passive"],
        "total_spends": template_data["total_spends"],
        "net_savings": template_data["net_savings"]
    }

    table.put_item(Item=item)

  #  print("✅ Saved:",template_data["period"])

def get_list_env(key):
    try:
        return [k.lower() for k in json.loads(os.environ.get(key, "[]"))]
    except:
        return []

# function to prepare SES template data from raw transactions (DynamoDB items)
def make_ses_data(items, period):
    # 👉 DynamoDB से data fetch karo
    try:
        data = {
            "hdfc": defaultdict(float),
            "icici": defaultdict(float)
        }

        highest_spend = {
            "hdfc": {"amount": 0, "name": ""},
            "icici": {"amount": 0, "name": ""}
        }

        latest_balance = {
            "hdfc": {"date": None, "balance": 0},
            "icici": {"date": None, "balance": 0}
        }



        keywords_salary  = get_list_env("KEYWORDS_SALARY")
        include_passive = get_list_env("INCLUDE_PASSIVE")
        exclude_passive = get_list_env("EXCLUDE_PASSIVE")
        exclude_withdrawal = get_list_env("EXCLUDE_WITHDRAWAL")
        print("✅ Classification Keywords Loaded:")
        print("Salary Keywords:", keywords_salary)
        print("Include in Passive:", include_passive)   
        print("Exclude from Passive:", exclude_passive)
        print("Exclude from Withdrawal (Self Deposit):", exclude_withdrawal)
        # print("📊 Raw Data from DynamoDB:", items)
        for item in items:
            bank = item.get('bank')
            date_str = item.get('date')
            balance = parse_number(item.get('balance'))

            # ❌ skip invalid data
            if not bank or not date_str:
                continue

            try:
                date_obj = datetime.strptime(date_str.strip(), "%d-%m-%Y")
            except Exception:
                continue  # invalid date skip
            # print(f"Processing: Bank={bank}, Date={date_obj.date()}, Balance={balance}")
            # ✅ update latest
            if (
                latest_balance[bank]["date"] is None
                or date_obj >= latest_balance[bank]["date"]
            ):
                latest_balance[bank]["date"] = date_obj
                latest_balance[bank]["balance"] = balance

          #  print("📊 Raw Data from DynamoDB:", item)
            deposit = parse_number(item.get('deposit'))
            withdrawal = parse_number(item.get('withdrawal'))
            balance = parse_number(item.get('balance'))
            particulars = item.get('particulars', '').lower()
            print(f"Processing particulars: {particulars} with deposit: {deposit} and withdrawal: {withdrawal}")
            if deposit > 0:
                    # ✅ total deposit
                data[bank]["total_deposit"] += deposit

                # ✅ salary
                if any(k in particulars for k in keywords_salary):
                    print(f"Identified salary: {date_str}", deposit)
                    data[bank]["salary"] += deposit

                # ✅ passive income (dividend / interest / achc)
                elif any(k in particulars for k in include_passive):
                    # print(f"Identified passive income: {date_str}", deposit)
                    data[bank]["passive"] += deposit

                # ✅ self transfer (own money movement)
                elif any(k in particulars for k in exclude_passive):
                    print(f"Identified self transfer: {date_str}", deposit)
                    data[bank]["self_transfer"] += deposit

                # ✅ fallback (unknown deposit)
                else:
                    # print(f"Unclassified deposit: {date_str}", deposit, particulars)
                    data[bank]["others"] += deposit
            # spends
            # print(f"Processing particulars: {particulars} with withdrawal: {withdrawal}")
            if any(k in particulars for k in exclude_withdrawal):
              #print(f"Identified self deposit: {date_str}", withdrawal)
                data[bank]["self_deposit"] += withdrawal
            # ✅ remaining → spends
            else:
              #print(f"Identified spend: {date_str}", withdrawal)
                data[bank]["spends"] += withdrawal

            # latest balance (max date assumption)
            # highest spend
            if withdrawal > highest_spend[bank]["amount"]:
                highest_spend[bank]["amount"] = withdrawal
                highest_spend[bank]["name"] = particulars[:20]
        # print("📊 Processed Data:", data)
        # 🔥 FINAL FORMAT (SES ke liye)

        template_data = {
            "period": period,
            "passive_change": "+14%", # future me calculate karega
            "spend_change": "+14%",  # future me calculate karega

            "hdfc_name": "HDFC Bank",
            "hdfc_balance": f"₹{int(latest_balance['hdfc']['balance'])}",
            "hdfc_salary": f"₹{int(data['hdfc']['salary'])}",
            "hdfc_passive": f"₹{int(data['hdfc']['passive'])}",  # future logic
            "hdfc_spends": f"₹{int(data['hdfc']['spends'])}",
            "hdfc_highest": highest_spend["hdfc"]["name"],

            "icici_name": "ICICI Bank",
            "icici_balance": f"₹{int(latest_balance['icici']['balance'])}",
            "icici_salary": f"₹{int(data['icici']['salary'])}",
            "icici_passive": f"₹{int(data['icici']['passive'])}",
            "icici_spends": f"₹{int(data['icici']['spends'])}",
            "icici_highest": highest_spend["icici"]["name"],
            "total_balance": f"₹{int(latest_balance['hdfc']['balance'] + latest_balance['icici']['balance'])}",
            "total_income": f"₹{int(data['hdfc']['salary'] + data['icici']['salary']) + int(data['hdfc']['passive'] + data['icici']['passive'])}",
            "total_passive": f"₹{int(data['hdfc']['passive'] + data['icici']['passive'])}",
            "total_spends": f"₹{int(data['hdfc']['spends'] + data['icici']['spends'])}",
            "net_savings": f"₹{int(data['hdfc']['salary'] + data['icici']['salary']) + int(data['hdfc']['passive'] + data['icici']['passive']) - int(data['hdfc']['spends'] + data['icici']['spends'])}"
        }

        return template_data
    except Exception as e:
        print("❌ DynamoDB Error:", str(e))
        return []

# function to get unique monthly periods from transaction dates (for SES reporting)
def get_monthly_periods():
    dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
    table = dynamodb.Table('transactions')

    response = table.scan()
    items = response.get('Items', [])

    if not items:
        return []

    # 🔹 extract dates
    dates = []
    for item in items:
        try:
            d = datetime.strptime(item['date'], "%d-%m-%Y")
            dates.append(d)
        except:
            continue

    if not dates:
        return []

    start_date = min(dates)
    end_date = max(dates)

    periods = []
    current = start_date.replace(day=1)

    while current <= end_date:
        year = current.year
        month = current.month

        last_day = calendar.monthrange(year, month)[1]

        month_start = current
        month_end = current.replace(day=last_day)

        # 🔥 last month adjust
        if month_end > end_date:
            month_end = end_date

        # ✅ WITH YEAR
        periods.append(
            f"{month_start.strftime('%d %b %Y')} - {month_end.strftime('%d %b %Y')}"
        )

        # next month
        if month == 12:
            current = current.replace(year=year+1, month=1)
        else:
            current = current.replace(month=month+1)

    return periods

# function to get transactions for a specific period (used in SES reporting)
def get_items_for_period(start, end):
    dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
    table = dynamodb.Table('transactions')
    start_date = datetime.strptime(start, "%d %b %Y").date()
    end_date = datetime.strptime(end, "%d %b %Y").date()

    items = []

    response = table.scan()

    while True:
        for item in response.get('Items', []):
            try:
                date_str = item['date'].strip()
                d = datetime.strptime(date_str, "%d-%m-%Y").date()

                if start_date <= d <= end_date:
                    # print(f"Adding item with date {date_str} to period {start} - {end}")
                    # print("Item details:", item)
                    items.append(item)

            except Exception as e:
                print("Error:", item.get('date'), e)

        if 'LastEvaluatedKey' in response:
            response = table.scan(
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
        else:
            break

    return items


# main function to prepare SES template data by fetching transactions period-wise and processing them
def ses_template_data_prep():
    try:
      #print(get_monthly_periods())
        periods = get_monthly_periods()
      #print("Available periods:", periods)

        for period in periods:
            # print(f"Processing period: {period}")
            start, end = period.split(" - ")
            items = get_items_for_period(start, end)
            # print(f"Items for {period}:", items)
            template_data = make_ses_data(items, period)
          #print(f"Template data for {period}:", template_data)
            save_period_data(os.environ.get("DEVELOP_BY"), template_data)
        
    except Exception as e:
        print("❌ SES Data Prep Error:", str(e))

def gmail_send_email():
    try:
        # 📁 Load HTML template
        with open("emailtemplate.html", "r", encoding="utf-8") as f:
            template = Template(f.read())

        table = dynamodb.Table('period-wise-transaction')

        current_month = datetime.now().strftime("%b")  # Apr

        response = table.scan(
            FilterExpression=Attr("period").contains(current_month)
        )

        items = response.get("Items", [])
        # print(items)

        # 🎯 Render HTML
        html_content = template.render(**items[0]) if items else "<h1>No data available for this month</h1>"

        # 📧 Email config
        sender_email = os.environ.get("FROM_EMAIL")  # use environment variable for security
        app_password =  os.environ.get("GMAIL_APP_PASSWORD")  # use environment variable for security
        receiver_email = os.environ.get("RECIPIENT_EMAIL")
        msg = MIMEText(html_content, "html")
        msg["Subject"] = f"📊 Monthly Financial Report - {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
        msg["From"] = sender_email
        msg["To"] = receiver_email

        # 🚀 Send mail
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()

      #print("✅ Mail sent successfully")
    except Exception as e:
        print("❌ Gmail Error:", str(e))

# main Lambda handler function to orchestrate the entire workflow
def lambda_handler(event, context):
    try:
      #print("🚀 Start Decryption Only Flow")
        # step 1: hit endpoint to trigger the flow for downloading the pdf in google drive
        hit_endpoint()
        # step 2: get PDF from drive and decrypt and store it in tmp folder and insert data in dynomo db transactions table
        download_and_decrypt_pdf()
        # step 3: prepare SES template data by fetching transactions period-wise and processing them and save in another table for Email reporting
        ses_template_data_prep()
        # step 4: send email using SES with the prepared template data
        gmail_send_email()
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Workflow completed successfully"
            })
        }

    except Exception as e:
        print("❌ Error:", str(e))
        return {
            "statusCode": 500,
            "body": str(e)
        }
    finally:
        print("🧹 Cleanup always runs")
        clean_endpoint()