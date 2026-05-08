import json
import os
import urllib.request
import pikepdf
import boto3
from google.oauth2 import service_account
from googleapiclient.discovery import build

FOLDER_ID = os.environ.get("FOLDER_ID")
s3 = boto3.client('s3')
BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")

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


def download_s3_file(file_id, filename):
    """
    file_id: This is now the S3 Key (e.g., 'user-123/statement.pdf')
    filename: The local name to save as in /tmp
    """
    # Lambda allows writing files only to the /tmp directory
    filepath = f"/tmp/{filename}"
    try:
        print(f"Downloading {file_id} from {BUCKET_NAME}...")
        
        # Download the object directly to the /tmp path
        s3.download_file(BUCKET_NAME, file_id, filepath)
        
        print(f"File saved to: {filepath}")
        return filepath

    except Exception as e:
        print(f"Error downloading from S3: {str(e)}")
        raise e

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
        raise Exception("No PDF found in folders ❌")

    return files

def get_all_s3_pdfs():
    # Ensure the prefix ends with a slash if it's a folder
    FOLDER_PREFIX = "user-123/" 
    print(f"🚀 Starting S3 PDF fetch with Bucket: {BUCKET_NAME} and Prefix: {FOLDER_PREFIX}")
    # 2. Check if BUCKET_NAME is still None (safety check)
    if not BUCKET_NAME:
        raise Exception("CONFIG ERROR: S3_BUCKET_NAME environment variable is not set!")
    
    try:
        print(f"Searching in Bucket: {BUCKET_NAME} with Prefix: {FOLDER_PREFIX}")
        
        response = s3.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix=FOLDER_PREFIX
        )

        # 2. Extract contents
        s3_files = response.get('Contents', [])
        
        # DEBUG: See exactly what keys were found
        print(f"Raw S3 Response 'Contents': {s3_files}")

        if not s3_files:
            # This happens if the folder is empty or bucket name is wrong
            raise Exception("No objects found in the specified S3 path ❌")

        formatted_files = []
        for obj in s3_files:
            key = obj['Key']
            
            # 3. Filter: Ignore the folder placeholder itself and non-PDFs
            if key.lower().endswith('.pdf'):
                formatted_files.append({
                    "id": key,
                    "name": key.split('/')[-1]
                })

        if not formatted_files:
            raise Exception("No PDF files found in folder ❌")

        return formatted_files

    except Exception as e:
        print(f"Error: {str(e)}")
        raise e


def clean_s3_folder(folder_prefix):
    """
    Delete all files inside an S3 folder/prefix
    """

    print(f"🧹 Cleaning S3 folder: {folder_prefix}")

    if not BUCKET_NAME:
        raise Exception("CONFIG ERROR: S3_BUCKET_NAME is not set!")

    try:
        # Fetch all objects inside folder
        response = s3.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix=folder_prefix
        )

        # No files found
        if 'Contents' not in response:
            print("⚠️ No files found in folder")
            return {
                "success": True,
                "message": "Folder already empty"
            }

        # Prepare delete list
        objects_to_delete = [
            {"Key": obj["Key"]}
            for obj in response["Contents"]
        ]

        print(f"🗑️ Deleting {len(objects_to_delete)} files...")

        # Delete all objects
        delete_response = s3.delete_objects(
            Bucket=BUCKET_NAME,
            Delete={
                "Objects": objects_to_delete
            }
        )

        print("✅ Folder cleaned successfully")

        return {
            "success": True,
            "message": f"Deleted {len(objects_to_delete)} files"
        }

    except Exception as e:
        print(f"❌ Error cleaning folder: {str(e)}")

        return {
            "success": False,
            "error": str(e)
        }

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
    




