from datetime import datetime
from collections import defaultdict
from dateutil.relativedelta import relativedelta
import calendar


def get_last_6_months():
    """
    Current month + previous 5 months
    Example:
    ['dec', 'jan', 'feb', 'mar', 'apr', 'may']
    """

    today = datetime.today()

    months = []

    for i in range(5, -1, -1):
        dt = today - relativedelta(months=i)
        months.append(dt.strftime("%b").lower())

    return months


def get_month_status(start_date, end_date):

    start_dt = datetime.strptime(start_date, "%d %b %Y")
    end_dt = datetime.strptime(end_date, "%d %b %Y")

    total_days = calendar.monthrange(
        start_dt.year,
        start_dt.month
    )[1]

    covered_days = (end_dt - start_dt).days + 1

    if covered_days >= total_days:
        return "Done"

    return "partial"


def get_stetement_coverage(data_list, user):

    months = get_last_6_months()

    result = {
        "complete": 0,
        "partial": 0,
        "missing": 0,
        "uploaded": 0,
        "banks": {}
    }

    user_records = [
        x for x in data_list
        if x["user"] == user
    ]

    result["uploaded"] = len(user_records)

    bank_map = defaultdict(dict)

    for item in user_records:

        bank = item["bank"].lower()

        period = item["file_range_period"]

        # Example:
        # 01 May 2026 - 08 May 2026

        start_str, end_str = period.split(" - ")

        start_dt = datetime.strptime(start_str, "%d %b %Y")

        month_name = start_dt.strftime("%b").lower()

        status = get_month_status(start_str, end_str)

        # Done should override partial
        existing = bank_map[bank].get(month_name)

        if existing != "Done":
            bank_map[bank][month_name] = status

    # Final response
    for bank in bank_map.keys():

        result["banks"][bank] = {}

        for month in months:

            status = bank_map[bank].get(month, "missing")

            result["banks"][bank][month] = status

            if status == "Done":
                result["complete"] += 1

            elif status == "partial":
                result["partial"] += 1

            else:
                result["missing"] += 1

    return result
