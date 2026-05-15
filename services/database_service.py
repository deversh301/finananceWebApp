import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from datetime import datetime
import calendar
from dateutil.relativedelta import relativedelta
import re

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


def save_file_metadata(period, file_name, bank , rangePeriod, user_id=os.environ.get("DEVELOP_BY")):
    try:
        print(f"Saving file metadata for period: {period}, file: {file_name}, bank: {bank}")
        final_period = f"{file_name}_{period}_{bank}"
        metadata_table = dynamodb.Table("period-wise-transaction")
        metadata_table.put_item(
            Item={
                "user": user_id,
                "file_name": file_name,
                "data_type": "file_metadata",
                "period": period,  # store period with bank to avoid conflicts with period metadata records
                "file_range_period": rangePeriod,
                'bank': bank
            }
        )
        print("✅ File metadata saved successfully")
    except Exception as e:
        print("❌ Metadata Save Error:", str(e))


def fetch_metadata(user_id , type_of_data):
    try:
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = dynamodb.Table('period-wise-transaction')

        response = table.query(
            KeyConditionExpression=Key("user").eq(user_id),
            FilterExpression=Attr("data_type").eq(type_of_data)
        )

        items = response.get("Items", [])
        return items
    except Exception as e:
        print("❌ Fetch Metadata Error fetch_period_metadata", str(e))
        return []


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
            **template_data,
            "user": user,
            "passive_change": calc_percentage_change(
                clean_amount(template_data.get("total_passive", 0)),
                clean_amount(prev_item.get("total_passive", 0))
                if prev_item else 0.0
            ),
            "spend_change": calc_percentage_change(
                clean_amount(template_data.get("total_spends", 0)),
                clean_amount(prev_item.get("total_spends", 0))
                if prev_item else 0.0
            ),
            "data_type": "period_metadata"
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


def clean_currency(value):
    try:
        """
        Converts:
        ₹4399 -> 4399
        ₹0 -> 0
        None -> 0
        """
        if not value:
            return 0

        value = str(value)
        value = re.sub(r"[^\d.]", "", value)

        return int(float(value)) if value else 0
    except Exception as e:
        print("❌ clean_currency:", str(e))
        return {}


def last_five_months_value(user, column_name, data_type):
    try:
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = dynamodb.Table('period-wise-transaction')
        # Last 5 months including current
        months = ["Jan", "Feb", "Mar", "Apr", "May",
                "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        current_month = datetime.now().month - 1

        required_months = []

        for i in range(4, -1, -1):
            index = (current_month - i) % 12
            required_months.append(months[index])

        # Fetch data from DynamoDB
        response = table.scan(
            FilterExpression=Key("user").eq(user)
            & Key("data_type").eq(data_type)
        )

        items = response.get("Items", [])

        # Default output
        result_map = {month: 0 for month in required_months}

        for item in items:
            period = item.get("period", "")

            # Example:
            # 01 Jan 2026 - 31 Jan 2026
            try:
                month = datetime.strptime(
                    period.split(" - ")[0],
                    "%d %b %Y"
                ).strftime("%b")

                if month in result_map:
                    result_map[month] = clean_currency(
                        item.get(column_name, 0)
                    )

            except Exception:
                pass

        return [
            {
                "value": result_map[month],
                "label": month
            }
            for month in required_months
        ]
    except Exception as e:
            print("❌ last_five_months_value:", str(e))
            return {}


def fetch_period_metadata():
    try:
        dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = dynamodb.Table('period-wise-transaction')

        current_month = datetime.now().strftime("%b")  # Apr

        response = table.scan(
            FilterExpression=
                Attr("period").contains(current_month) &
                Attr("data_type").eq("period_metadata")
        )

        items = response.get("Items", [])
        data = items[0] if items else {}
        month_status = build_month_status(items)
        incomeData =  last_five_months_value(os.environ.get("DEVELOP_BY"),"total_income", "period_metadata")
        expenseData = last_five_months_value(os.environ.get("DEVELOP_BY"),"total_spends", "period_metadata")
        data["month_status"] = month_status
        data["income_data"] = incomeData
        data["expense_data"] = expenseData
        return data
    except Exception as e:
        print("❌ Fetch Metadata Error:", str(e))
        return {}