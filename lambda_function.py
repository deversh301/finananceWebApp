import json
from services.google_drive_service import (
    hit_endpoint,
    clean_endpoint
)
from services.parse_decrypted_pdf_service import (
    download_and_decrypt_pdf
)
from services.email_service import (
    gmail_send_email,
    ses_template_data_prep
)

from services.database_service import (
    fetch_period_metadata
)


# main Lambda handler function to orchestrate the entire workflow
def lambda_handler(event, context):
    try:
      #print("🚀 Start Decryption Only Flow")
        # step 1: hit endpoint to trigger the flow for downloading the pdf in google drive
        # hit_endpoint()
        # step 2: get PDF from drive and decrypt and store it in tmp folder and insert data in dynomo db transactions table
        download_and_decrypt_pdf()
        # step 3: prepare SES template data by fetching transactions period-wise and processing them and save in another table for Email reporting
        ses_template_data_prep()
        # step 4: send email using SES with the prepared template data
        # gmail_send_email()
        data = fetch_period_metadata()
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Workflow completed successfully",
                "data": data
            })
        }

    except Exception as e:
        print("❌ Error:", str(e))
        return {
            "statusCode": 500,
            "body": str(e)
        }
    # finally:
    #     print("🧹 Cleanup always runs")
    #     # clean_endpoint()