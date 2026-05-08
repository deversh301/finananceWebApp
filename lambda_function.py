import json
from decimal import Decimal
import os
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
    fetch_period_metadata,
    fetch_bankpwd_metadata,
    delete_bankpwd,
    save_bankpwd_metadata
)

from helpers.helper import (
    decimal_default
)



# main Lambda handler function to orchestrate the entire workflow
def lambda_handler(event, context):
    try:
        print("🚀 Lambda function started with event:", event)
        query_params = event.get("queryStringParameters") or {}
        action = query_params.get("action")
        path = event["path"]
        method = event["httpMethod"]
        if path == "/bank-passwords" and method == "POST":
            if action == "fetchdata":
                data = fetch_bankpwd_metadata(os.environ.get("DEVELOP_BY"))
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "message": "Data fetched successfully",
                        "data": data
                    }, default=decimal_default) # Add 'default' here
                }
            elif action == "deletePwd":
                body = json.loads(event.get("body", "{}"))
                delete_bankpwd(os.environ.get("DEVELOP_BY"),body)
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "message": "Data deleted successfully"
                    })
                }

            else:
                body = json.loads(event.get("body", "{}"))
                save_bankpwd_metadata(body)
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "message": "Data saved successfully"
                    })
                }
        elif action == "fetchdata":
            data = fetch_period_metadata()
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Data fetched successfully",
                    "data": data
                }, default=decimal_default) # Add 'default' here
            }
        else:
            body = json.loads(event.get("body", "{}"))
            banks = body.get("banks", [])
            #print("🚀 Start Decryption Only Flow")
            # step 1: hit endpoint to trigger the flow for downloading the pdf in google drive
            # hit_endpoint()
            # step 2: get PDF from drive and decrypt and store it in tmp folder and insert data in dynomo db transactions table
            res = download_and_decrypt_pdf(banks)
            print("🚀 Decryption flow result:", res)
            if res == False:
                response = {
                    "statusCode": 500,
                    "body": json.dumps({
                        "message": "Please check your bank password data, it seems some error in decryption step"
                    })
                }
                print("❌ Decryption flow failed:", response)
                return response
            # # step 3: prepare SES template data by fetching transactions period-wise and processing them and save in another table for Email reporting
            ses_template_data_prep()
            # step 4: send email using SES with the prepared template data
            # gmail_send_email()
            return { "statusCode": 200, "body": "workflow logic" };

    except Exception as e:
        print("❌ Error:", str(e))
        return {
            "statusCode": 500,
            "body": str(e)
        }
    # finally:
    #     print("🧹 Cleanup always runs")
    #     # clean_endpoint()