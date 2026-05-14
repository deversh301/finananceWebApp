import os
import re
from datetime import datetime
import boto3
from services.google_drive_service import (
    decrypt_pdf,
    get_all_pdfs,
    get_all_s3_pdfs,
    download_s3_file,
    read_drive_files,
    clean_s3_folder,
    download_file
)
from services.database_service import (
    save_transactions_bulk,
    save_file_metadata
)
from helpers.helper import ( 
    clean_particulars,
    build_period_from_transactions,
    get_file_password_from_array
    )


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


def format_date(date_str):
    """
    Convert different date formats into:
    01 Mar 2026
    """

    date_formats = [
        "%B %d, %Y",   # May 01, 2026
        "%d/%m/%Y",    # 01/05/2026
        "%d-%m-%Y",    # 01-05-2026
    ]

    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%d %b %Y")
        except:
            pass

    return date_str

def text_to_period(text: str, bank: str):
    """
    Extract statement period from bank statement text.
    
    Args:
        text (str): Extracted OCR/PDF text
        bank (str): Bank identifier (e.g. ICICI)
        
    Returns:
        str or None
    """

    BANK_PATTERNS = {
    "ICICI": r"for the period\s+([A-Za-z]+\s+\d{2},\s+\d{4})\s*-\s*([A-Za-z]+\s+\d{2},\s+\d{4})",
    "HDFC": r"From\s*:\s*(\d{2}/\d{2}/\d{4})\s*To\s*:\s*(\d{2}/\d{2}/\d{4})"
    }
    
    pattern = BANK_PATTERNS.get(bank.upper())

    if not pattern:
        raise ValueError(f"No pattern configured for bank: {bank}")

    match = re.search(pattern, text, re.IGNORECASE)

    if not match:
        return None

    start_date = format_date(match.group(1))
    end_date = format_date(match.group(2))

    return f"{start_date} - {end_date}"


# Main function to orchestrate the flow: download, decrypt, read, parse, and save
def download_and_decrypt_pdf(banks):    
    try:
       #👉 get PDF
        # pdf_files = get_all_pdfs()
        pdf_files = get_all_s3_pdfs()
        Dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
        table = Dynamodb.Table("period-wise-transaction")
        print(f"🚀 Found {len(pdf_files)} PDF(s) to process")

        for pdf in pdf_files:
            try:
                file_id = pdf["id"]
                file_name = pdf["name"]
                print(f"📄 Processing: {file_name}")
                # 👉 download
                input_path = download_s3_file(file_id, "input.pdf")
                output_path = f"/tmp/decrypted.pdf"
                print("banks array:", banks)
                #check if file is encrypted by trying to read it without decryption
                decrypt_pdf(input_path, output_path, get_file_password_from_array(banks, file_name))
                # print("✅ Decrypted file saved at:", output_path)
                text_data = read_drive_files()
                # Example usage:
                #print("📊 Extracted Text Data:\n", text_data)  # print first 500 chars
                bank = get_file_password_from_array(banks, file_name , 'bankName' )
                resultPeriod = text_to_period(text_data, bank)
                # print(resultPeriod)
                if bank == "hdfc":
                    print("📊 Parsing with HDFC logic")
                    json_output = parse_hdfc_text(text_data)
                else:
                    print("📊 Parsing with Generic logic")
                    json_output = parse_bank_statement(text_data)
              #print(f"✅ Parsed {build_period_from_transactions(json_output)} transactions for {file_name} - bank: {bank}")
                print(f"✅ Parsed transactions for {file_name} - bank: {bank}")
                period = build_period_from_transactions(json_output)   # ya jo bhi tera period logic hai
                final_period = f"{file_name}_{period}_{bank}"
                # 🔍 Check if exists
                response = table.get_item(
                    Key={
                        "user": os.environ.get("DEVELOP_BY"),
                        "period": final_period
                    }
                )

                print(f"🔍 Checking existence for period: {final_period}")

                if "Item" in response:
                    print("⏭️ Already exists, skipping:", final_period)
                    continue  # 🔥 skip to next loop
                print("✅ New period, saving data for:", final_period)
                save_file_metadata(final_period, file_name, bank, resultPeriod) # to_do need to fix this
                save_transactions_bulk(json_output, bank)
              #print("✅ Finished Decryption Only Flow")
            finally:
                # 🧹 cleanup (har baar chalega even if error aaye)
                for f in ["/tmp/input.pdf", "/tmp/decrypted.pdf"]:
                    if os.path.exists(f):
                        os.remove(f)
                        print(f"🧹 Deleted: {f}")
        
    except Exception as e:
        folder_prefix = "user-123/" # to_do - make it dynamic based on user or period if needed
        clean_s3_folder(folder_prefix)  # 🔥 cleanup S3 bucket after processing
        print("❌ Error in download_and_decrypt_pdf:", str(e))
        return False