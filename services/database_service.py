import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime
import calendar
from dateutil.relativedelta import relativedelta

from helpers.helper import ( 
    generate_txn_id,
    calc_percentage_change,
    build_month_status,
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


def save_file_metadata(period, file_name, bank , user_id=os.environ.get("DEVELOP_BY")):
    try:
        metadata_table = dynamodb.Table("period-wise-transaction")
        metadata_table.put_item(
            Item={
                "user": user_id,
                "file_name": file_name,
                "data_type": "file_metadata",
                "period": period + "_" + bank,  # store period with bank to avoid conflicts with period metadata records
                'bank': bank
            }
        )
    except Exception as e:
        print("❌ Metadata Save Error:", str(e))


def fetch_bankpwd_metadata(user_id):
    try:
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = dynamodb.Table('period-wise-transaction')

        response = table.query(
            KeyConditionExpression=Key("user").eq(user_id),
            FilterExpression=Attr("data_type").eq("password_metadata")
        )

        items = response.get("Items", [])
        return items
    except Exception as e:
        print("❌ Fetch Metadata Error fetch_bankpwd_metadata:", str(e))
        return []
    
def delete_bankpwd(user_id, payload):
    try:
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = dynamodb.Table('period-wise-transaction')
        print(f"Attempting to delete bank password metadata for user: {user_id} with payload: {payload}")
        response = table.query(
            KeyConditionExpression=Key("user").eq(user_id),
            FilterExpression=Attr("bank_password").eq(payload.get("password")) & Attr("bank").eq(payload.get("bank")) & Attr("data_type").eq("password_metadata"),
        )

        items = response.get("Items", [])
        if items:
            item = items[0]
            table.delete_item(
                Key={
                    "user": item["user"],
                    "period": item["period"]
                }
            )
    except Exception as e:
        print("❌ Delete Metadata Error delete_bankpwd:", str(e))


def save_bankpwd_metadata(payload , user_id=os.environ.get("DEVELOP_BY")):
    try:
        metadata_table = dynamodb.Table("period-wise-transaction")
        metadata_table.put_item(
            Item={
                "user": user_id,
                "title": payload['title'],
                "bank_password": payload['password'],
                'bank': payload['bank'],
                "data_type": "password_metadata",
                "period":  payload['title'] + "_" + payload['bank'],  # store period with bank to avoid conflicts with period metadata records
            }
        )
    except Exception as e:
        print("❌ Metadata Save Error save_bankpwd_metadata:", str(e))




# function to save period-wise summary data in DynamoDB (for SES reporting)
def save_period_data(user, template_data):
    try:
        dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
        table = dynamodb.Table('period-wise-transaction')

        # extract "Apr 2026"
        month_str = template_data["period"].split("-")[0].strip()[3:]   # "Apr 2026"
        current_date = datetime.strptime(month_str, "%b %Y")

        prev_date = current_date - relativedelta(months=1)

        current_month = current_date.strftime("%b")   # Apr 2026
        prev_month = prev_date.strftime("%b %Y")         # Mar 2026

        prefix = f"01 {current_month}"   # "01 Apr", "01 Mar"
        response_item = table.query(
            KeyConditionExpression=(
                Key("user").eq(user) &
                Key("period").begins_with(prefix)
            )
        )
        items = response_item.get("Items", [])
        
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(
                    Key={
                        "user": item["user"],
                        "period": item["period"]
                    }
                )

        response = table.scan()

        prev_items = [
            item for item in response.get("Items", [])
            if prev_month in item.get("period", "")
        ]

        prev_item = prev_items[0] if prev_items else None
        item = {
            "user": user,
            "period": template_data["period"],
            "passive_change": calc_percentage_change( clean_amount(template_data["total_passive"]), clean_amount(prev_item.get('total_passive', 0)) if prev_item else 0.0),  # example change calculation
            "spend_change": calc_percentage_change(clean_amount(template_data["total_spends"]), clean_amount(prev_item.get('total_spends', 0)) if prev_item else 0.0),  # example change calculation
            "hdfc_name": template_data["hdfc_name"],
            "hdfc_balance": template_data["hdfc_balance"],
            "hdfc_salary": template_data["hdfc_salary"],
            "hdfc_passive": template_data["hdfc_passive"],
            "hdfc_spends": template_data["hdfc_spends"],
            "hdfc_highest": template_data["hdfc_highest"],
            "is_bank_one_present": template_data["is_bank_one_present"],
            "is_bank_two_present": template_data["is_bank_two_present"],
            "icici_name": template_data["icici_name"],
            "icici_balance": template_data["icici_balance"],
            "icici_salary": template_data["icici_salary"],
            "icici_passive": template_data["icici_passive"],
            "icici_spends": template_data["icici_spends"],
            "icici_highest": template_data["icici_highest"],
            "data_type": "period_metadata",
            "total_balance": template_data["total_balance"],
            "total_income": template_data["total_income"],
            "total_passive": template_data["total_passive"],
            "total_spends": template_data["total_spends"],
            "net_savings": template_data["net_savings"]
        }

        table.put_item(Item=item)
    except Exception as e:
        print("❌ Period Data Save Error:", str(e))


  ##print("✅ Saved:",template_data["period"])

  
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

    # ✅ FIXED START DATE
    start_date = datetime(2026, 1, 1)
    end_date = max(dates)

    periods = []
    current = start_date

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


def fetch_period_metadata():
    try:
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = dynamodb.Table('period-wise-transaction')

        current_month = datetime.now().strftime("%b")  # Apr

        response = table.scan(
            FilterExpression=Attr("period").contains(current_month)
        )

        items = response.get("Items", [])
        data = items[0] if items else {}
        month_status = build_month_status(items)
        data["month_status"] = month_status
        return data
    except Exception as e:
        print("❌ Fetch Metadata Error:", str(e))
        return {}