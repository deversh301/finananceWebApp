import json
import os
import urllib.request
import pikepdf
from google.oauth2 import service_account
from googleapiclient.discovery import build

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
    




