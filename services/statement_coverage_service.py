from datetime import datetime
from collections import defaultdict
from dateutil.relativedelta import relativedelta
import calendar


def get_last_6_months():
    """
    Current month + previous 5 months

    Example:
    [
        {"key": "dec", "month": 12, "year": 2025},
        {"key": "jan", "month": 1, "year": 2026},
    ]
    """

    today = datetime.today()

    months = []

    for i in range(5, -1, -1):

        dt = today - relativedelta(months=i)

        months.append({
            "key": dt.strftime("%b").lower(),
            "month": dt.month,
            "year": dt.year
        })

    return months


def get_month_status(month_dt, start_dt, end_dt):

    today = datetime.today()

    # =========================
    # CURRENT MONTH LOGIC
    # =========================

    if (
        month_dt.month == today.month
        and month_dt.year == today.year
    ):

        # current date covered
        if end_dt.date() >= today.date():
            return "Done"

        return "partial"

    # =========================
    # OLD MONTHS
    # =========================

    total_days = calendar.monthrange(
        month_dt.year,
        month_dt.month
    )[1]

    # calculate actual covered days
    month_start = month_dt.replace(day=1)

    month_end = month_dt.replace(day=total_days)

    actual_start = max(start_dt, month_start)

    actual_end = min(end_dt, month_end)

    covered_days = (
        actual_end - actual_start
    ).days + 1

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

    # =========================
    # GET ALL BANKS
    # =========================

    banks = set()

    for item in user_records:

        bank = item.get("bank", "").lower()

        if bank:
            banks.add(bank)

    # =========================
    # DEFAULT ALL MONTHS = missing
    # =========================

    bank_map = defaultdict(dict)

    for bank in banks:

        for m in months:

            bank_map[bank][m["key"]] = "missing"

    # =========================
    # PROCESS FILES
    # =========================

    for item in user_records:

        bank = item["bank"].lower()

        period = item["file_range_period"]

        try:

            start_str, end_str = period.split(" - ")

            start_dt = datetime.strptime(
                start_str.strip(),
                "%d %b %Y"
            )

            end_dt = datetime.strptime(
                end_str.strip(),
                "%d %b %Y"
            )

        except Exception:
            continue

        # =========================
        # ITERATE MONTH BY MONTH
        # =========================

        temp_dt = start_dt.replace(day=1)

        while temp_dt <= end_dt:

            for month_data in months:

                if (
                    temp_dt.month == month_data["month"]
                    and temp_dt.year == month_data["year"]
                ):

                    month_key = month_data["key"]

                    status = get_month_status(
                        temp_dt,
                        start_dt,
                        end_dt
                    )

                    existing = bank_map[bank].get(month_key)

                    # Done overrides partial
                    if existing != "Done":

                        bank_map[bank][month_key] = status

            temp_dt += relativedelta(months=1)

    # =========================
    # FINAL RESPONSE
    # =========================

    for bank in bank_map.keys():

        result["banks"][bank] = {}

        for month in months:

            month_key = month["key"]

            status = bank_map[bank].get(
                month_key,
                "missing"
            )

            result["banks"][bank][month_key] = status

            if status == "Done":

                result["complete"] += 1

            elif status == "partial":

                result["partial"] += 1

            else:

                result["missing"] += 1

    return result