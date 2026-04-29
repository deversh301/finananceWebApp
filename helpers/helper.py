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