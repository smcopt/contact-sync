import os
import google.auth
import google.auth.transport.requests
from google.auth import iam
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIGURATION (Updated to match your GitHub Secrets) ---
SPREADSHEET_ID = os.environ.get('GOOGLE_SHEET_ID') 
ADMIN_EMAIL = os.environ.get('WORKSPACE_ADMIN_EMAIL')
SERVICE_ACCOUNT_EMAIL = os.environ.get('GCP_SERVICE_ACCOUNT')

MAIN_SHEET_NAME = 'MAIN'
AUDIT_SHEET_NAME = 'AUDIT'
HEADER_ROW = 6

def get_service():
    # 1. Get base Workload Identity credentials with Cloud Platform scope
    creds, project = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    request = google.auth.transport.requests.Request()

    # 2. Use the IAM Signer to act as the Service Account
    signer = iam.Signer(request, creds, SERVICE_ACCOUNT_EMAIL)

    # 3. Generate the Delegated Credentials (impersonating the Workspace Admin)
    delegated_credentials = service_account.Credentials(
        signer,
        SERVICE_ACCOUNT_EMAIL,
        "https://oauth2.googleapis.com/token",
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/admin.directory.group.member.readonly'
        ],
        subject=ADMIN_EMAIL
    )
    
    sheets_service = build('sheets', 'v4', credentials=delegated_credentials)
    admin_service = build('admin', 'directory_v1', credentials=delegated_credentials)
    return sheets_service, admin_service

def main():
    sheets, admin = get_service()

    # 1. Get Group Emails from MAIN sheet header (starts at Column F)
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{MAIN_SHEET_NAME}!F{HEADER_ROW}:Z{HEADER_ROW}"
    ).execute()
    
    group_emails = result.get('values', [[]])[0] if result.get('values') else []

    audit_data = [["Group Email", "Member Email", "Role", "Type"]]

    # 2. Fetch members for each group
    for group_email in group_emails:
        if not group_email or '@' not in group_email: continue
        
        try:
            members_result = admin.members().list(groupKey=group_email).execute()
            members = members_result.get('members', [])
            
            for m in members:
                audit_data.append([group_email, m['email'], m['role'], m['type']])
        except Exception as e:
            print(f"Error fetching {group_email}: {e}")

    # 3. Write to AUDIT sheet
    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{AUDIT_SHEET_NAME}!A1:Z1000"
    ).execute()

    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{AUDIT_SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": audit_data}
    ).execute()

    print(f"Successfully audited {len(group_emails)} groups.")

if __name__ == "__main__":
    main()
