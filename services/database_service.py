import os
import boto3
from datetime import datetime
import calendar
from dateutil.relativedelta import relativedelta

from helpers.helper import ( 
    generate_txn_id,
    calc_percentage_change,
    clean_amount,
    to_decimal)

# 👉 DynamoDB connection
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
table = dynamodb.Table("transactions")

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