# 📊 Financial Email Automation (Docker + Lambda Style)

## 🚀 Overview

Kuch complicated nahi hai bhai 😄
Bas repo download karo, Docker run karo aur system chal jayega.

Ye project:

* Google Drive se PDF fetch karta hai
* Decrypt karta hai
* Transactions process karta hai
* DynamoDB me save karta hai
* Email report bhejta hai

---

## ⚙️ Setup (Step-by-Step)

### 1. Docker install karo (Windows)

Pehle system me Docker install hona chahiye.

---

### 2. Env file banao

Project root me ek file banao:

```
env.txt
```

Usme ye values daal do:

```
FOLDER_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GOOGLE_APP_CLEAN_URL=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GOOGLE_APP_URL=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GOOGLE_CREDS=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ICICI_PASSWORD=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
HDFC_PASSWORD=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_ACCESS_KEY_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_REGION=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FROM_EMAIL=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RECIPIENT_EMAIL=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TEMPLATE_NAME=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

KEYWORDS_SALARY=["xxxx","xxxx"]
INCLUDE_PASSIVE=["xxxx","xxxx"]
EXCLUDE_PASSIVE=["xxxx","xxxx"]
EXCLUDE_WITHDRAWAL=["xxxx","xxxx"]

DEVELOP_BY=xxxxxx
```

---

### 3. Docker Build karo

PowerShell me ye command run karo:

```
$env:DOCKER_BUILDKIT=0
```

Phir:

```
docker build --no-cache --platform linux/amd64 -t drive-lambda .
```

---

### 4. Container run karo

(agar required ho to env pass karo)

```
docker run --env-file env.txt -p 9000:8080 drive-lambda
```

---

### 5. Endpoint hit karo

PowerShell se ye command run karo:

```
Invoke-WebRequest -Uri http://localhost:9000/2015-03-31/functions/function/invocations -Method POST -Body "{}"
```

---

## 📌 Notes

* Ensure Docker properly installed hai
* Env file me correct credentials hone chahiye
* Gmail ke liye App Password use karo (normal password nahi)
* AWS credentials valid hone chahiye

---

## ⚠️ Important

* `.env` ya `env.txt` GitHub pe push mat karna ❌
* Sensitive data secure rakho

---

## 👨‍💻 Developed By

Shubham 🚀
