import json
import os
from collections import defaultdict
import boto3
from boto3.dynamodb.conditions import Attr
from datetime import datetime

import smtplib
from email.mime.text import MIMEText
from jinja2 import Template

from services.database_service import (
    get_monthly_periods, save_period_data, get_items_for_period
)
from helpers.helper import ( get_list_env, parse_number)


def gmail_send_email():
    try:
        # 📁 Load HTML template
        with open("emailtemplate.html", "r", encoding="utf-8") as f:
            template = Template(f.read())
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
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

