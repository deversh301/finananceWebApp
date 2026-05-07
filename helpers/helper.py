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
from boto3.dynamodb.conditions import Key, Attr
import uuid
from datetime import datetime
import hashlib
import time
import calendar
import smtplib
from email.mime.text import MIMEText
from jinja2 import Template
from dateutil.relativedelta import relativedelta

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

# function to get password from array using filename
def get_file_password_from_array(files_array, file_name):
    try:

        for file in files_array:

            if file.get("filename") == file_name:
                return file.get("password")

        return None

    except Exception as e:
        print("❌ Password Extraction Error:", str(e))
        return None


# helper to calculate percentage change between two values (for SES reporting)
def calc_percentage_change(current, previous):
    if previous == 0:
        return "0%"   # ya handle separately
    
    change = ((current - previous) / previous) * 100
    
    sign = "+" if change >= 0 else ""
    return f"{sign}{round(change, 2)}%"


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

def get_list_env(key):
    try:
        return [k.lower() for k in json.loads(os.environ.get(key, "[]"))]
    except:
        return []

# helper to prepare record for SES template data based on transactions (which banks are present)
def prepare_record(transactions):
    banks = set(txn["bank"] for txn in transactions)

    return {
        "bank1": 1 if "hdfc" in banks else 0,
        "bank2": 1 if "icici" in banks else 0
    }

# helper to generate HTML for month-wise status in email
def generate_month_html(status_dict):
    html = ""

    for (year, month), status in status_dict.items():
        month_name = calendar.month_abbr[month]

        if status:
            icon = "✔️"
            color = "#28a745"
        else:
            icon = "❌"
            color = "#ff4d4f"

        html += f'''
        <td style="font-size: 12px; color: #334155; font-weight: 500;">
            {month_name} <span style="color: {color}; margin-left: 4px;">{icon}</span>
        </td>
        '''

    return html



def get_last_4_months():
    months = []
    now = datetime.now()

    for i in range(4):
        m = now.month - i
        y = now.year

        if m <= 0:
            m += 12
            y -= 1

        months.append((y, m))

    return list(reversed(months))


def extract_key(period):
    # Example input: "01 Apr 2026 - 30 Apr 2026"
    start_date = period.split(" - ")[0]
    dt = datetime.strptime(start_date, "%d %b %Y")
    return f"{dt.year}-{str(dt.month).zfill(2)}"


def get_item_by_month(table, user_id, month_str):
  #print(f"🔹 Querying for user: {user_id}, month: {month_str}")
    prefix = f"01 {month_str}"   # "01 Apr", "01 Mar"
    response = table.query(
        KeyConditionExpression=(
            Key("user").eq(user_id) &
            Key("period").begins_with(prefix)
        )
    )

    items = response.get("Items", [])
    return items[0] if items else None

def build_month_status(items):
    data_map = {extract_key(item["period"]): item for item in items}
  #print("🔹 Data Map Keys:", data_map.keys())

    result = []
    dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
    table = dynamodb.Table("period-wise-transaction")


    for y, m in get_last_4_months():
        key = f"{y}-{str(m).zfill(2)}"
        month_str = calendar.month_abbr[m]  # "Apr", "Mar"
        item = get_item_by_month(table, os.environ.get("DEVELOP_BY"), month_str)
      #print("🔹 Checking period:")
      #print(item)
        if item:
            bank1 = int(item.get("is_bank_one_present", 0))
            bank2 = int(item.get("is_bank_two_present", 0))
          #print("🔹 Checking:", key, bank1, bank2)
            status = bank1 == 1 and bank2 == 1
        else:
          #print("🔹 No data for:", key)
            status = False

        result.append({
            "month": calendar.month_abbr[m],
            "status": status
        })

    return result

def build_period_from_transactions(data):
    if not data:
        return None

    dates = []

    for item in data:
        date_str = item.get("date")
        if date_str:
            dt = datetime.strptime(date_str, "%d-%m-%Y")
            dates.append(dt)

    if not dates:
        return None

    start_date = min(dates)
    end_date = max(dates)

    # format like: 01 Feb 2026
    start_str = start_date.strftime("%d %b %Y")
    end_str = end_date.strftime("%d %b %Y")

    return f"{start_str} - {end_str}"

# Helper to convert Decimal to int/float
def decimal_default(obj):
    if isinstance(obj, Decimal):
        # Convert to int if no decimal point, else float
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError