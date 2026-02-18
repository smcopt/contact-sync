import os
import google.auth
import google.auth.transport.requests
from google.auth import iam
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- CONFIGURATION ---
SPREADSHEET_ID = os.environ.get('GOOGLE_SHEET_ID') 

# Hardcoding these to completely bypass any GitHub Secret loading glitches
ADMIN_EMAIL = 'info@smcopt.org'
SERVICE_ACCOUNT_EMAIL = 'group-sync-bot@internal-group-sync-automation.iam.gserviceaccount.com'

MAIN_SHEET_NAME = 'MAIN'
AUDIT_SHEET_NAME = 'AUDIT'
HEADER_ROW = 6

def get_service():
    creds, project = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    request = google.auth.transport.requests.Request()
    signer = iam.Signer(request, creds, SERVICE_ACCOUNT_EMAIL)

    # Using the broader scopes that your sync script likely already uses
    delegated_credentials = service_account.Credentials(
        signer,
        SERVICE_ACCOUNT_EMAIL,
        "https://oauth2.googleapis.com/token",
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/admin.directory.group.member' 
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
                # Using .get() prevents errors if a user is missing a specific attribute
                audit_data.append([group_email, m.get('email', ''), m.get('role', ''), m.get('type', '')])
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
