import os
import google.auth
import google.auth.transport.requests
import google.auth.iam
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURATION ---
SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.group',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

# TARGET SHEET: Tab 'MAIN', starting at Row 6
SHEET_RANGE = 'MAIN!A6:Z'

# SAFETY LIST: Emails the script will NEVER remove
PROTECTED_EMAILS = [
    'info@smcopt.org',
    'sujanpaudel@iom.int'
]

def get_delegated_credentials():
    """Authenticates using Workload Identity + Domain-Wide Delegation."""
    admin_email = os.environ.get('WORKSPACE_ADMIN_EMAIL')
    creds, project_id = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    signer = google.auth.iam.Signer(auth_req, creds, creds.service_account_email)

    return service_account.Credentials(
        signer, creds.service_account_email, 'https://oauth2.googleapis.com/token',
        scopes=SCOPES, subject=admin_email
    )

def safe_add(service, group_email, user_email):
    """Adds user to group. Ignores if already there."""
    try:
        body = {'email': user_email, 'role': 'MEMBER'}
        service.members().insert(groupKey=group_email, body=body).execute()
        print(f"   [+] ADDED: {user_email} -> {group_email}")
    except HttpError as e:
        if e.resp.status == 409:
            pass # Silent success (Already exists)
        elif e.resp.status == 404:
            print(f"       [!] Group '{group_email}' not found.")
        else:
            print(f"       [!] Error adding to {group_email}: {e}")

def safe_remove(service, group_email, user_email):
    """Removes user from group. Ignores if not in it."""
    
    if user_email in PROTECTED_EMAILS:
        print(f"       [!] PROTECTED USER: {user_email} (Skipping removal)")
        return

    try:
        service.members().delete(groupKey=group_email, memberKey=user_email).execute()
        print(f"   [-] REMOVED: {user_email} <- {group_email}")
    except HttpError as e:
        if e.resp.status == 404:
            pass # Silent success (Not in group)
        else:
            print(f"       [!] Error removing from {group_email}: {e}")

def main():
    print("--- Starting Matrix Sync (Row 6 Headers) ---")
    
    # 1. Authenticate
    try:
        creds = get_delegated_credentials()
        service_sheets = build('sheets', 'v4', credentials=creds)
        service_admin = build('admin', 'directory_v1', credentials=creds)
    except Exception as e:
        print(f"FATAL: Auth failed. {e}")
        return

    # 2. Read Sheet
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    
    try:
        result = service_sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=SHEET_RANGE).execute()
        rows = result.get('values', [])
    except HttpError as e:
        print(f"FATAL: Could not read sheet 'MAIN'. Check permissions. Error: {e}")
        return

    if len(rows) < 2:
        print("Sheet data is too short (needs header row + data rows).")
        return

    # 3. Parse Headers (The first row we pulled is Row 6 of the sheet)
    headers = rows[0]
    
    # Create a map of {Column Index: Group Email}
    # We skip cols A(0), B(1), C(2), D(3=User), E(4=Status)
    group_map = {}
    print("Found Groups in Headers (Row 6):")
    
    for idx, header in enumerate(headers):
        if idx < 5: continue # Skip non-group columns
        
        clean_header = header.strip()
        if '@' in clean_header:
            group_map[idx] = clean_header
            print(f" - Col {idx}: {clean_header}")
            
    print("-" * 30)

    # 4. Process Users (Starting from Row 7 onwards)
    for row in rows[1:]:
        if not row: continue
        
        # Check if row has enough columns to contain an email (Index 3)
        if len(row) <= 3: continue 
        
        user_email = row[3].strip() # Column D is Index 3
        if not user_email: continue

        # Status is Column E (Index 4). Default to 'inactive' if missing.
        status = 'inactive'
        if len(row) > 4:
            status = row[4].strip().lower()

        print(f"Processing: {user_email} [{status.upper()}]")

        # Iterate through every group column found in headers
        for col_idx, group_email in group_map.items():
            
            should_add = False 

            if status == 'active':
                cell_value = ""
                # Check if this specific row has data in this column
                if col_idx < len(row):
                    cell_value = row[col_idx].strip().lower()
                
                # Check for "Yes"
                if cell_value == 'yes':
                    should_add = True
            
            # Execute
            if should_add:
                safe_add(service_admin, group_email, user_email)
            else:
                # Remove if Inactive, Blank, or "No"
                safe_remove(service_admin, group_email, user_email)

if __name__ == '__main__':
    main()
