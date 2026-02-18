import os
import google.auth
from googleapiclient.discovery import build

# --- CONFIGURATION ---
SPREADSHEET_ID = os.environ.get('GCP_SPREADSHEET_ID')
MAIN_SHEET_NAME = 'MAIN'
AUDIT_SHEET_NAME = 'AUDIT'
HEADER_ROW = 6  # Your headers are on row 6

def get_service():
    # Uses the same Workload Identity Federation credentials
    credentials, project = google.auth.default(
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/admin.directory.group.member.readonly'
        ]
    )
    # Impersonate your admin user (same logic as sync_groups.py)
    delegated_credentials = credentials.with_subject('info@smcopt.org')
    
    sheets_service = build('sheets', 'v4', credentials=delegated_credentials)
    admin_service = build('admin', 'directory_v1', credentials=delegated_credentials)
    return sheets_service, admin_service

def main():
    sheets, admin = get_service()

    # 1. Get Group Emails from MAIN sheet header
    # Range starts from Column F (Index 5) on Row 6
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{MAIN_SHEET_NAME}!F{HEADER_ROW}:Z{HEADER_ROW}"
    ).execute()
    group_emails = result.get('values', [[]])[0]

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
    # First, clear the existing data
    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{AUDIT_SHEET_NAME}!A1:Z1000"
    ).execute()

    # Write new data
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{AUDIT_SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": audit_data}
    ).execute()

    print(f"Successfully audited {len(group_emails)} groups.")

if __name__ == "__main__":
    main()
