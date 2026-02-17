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

# Note: We now start at A1 to read the HEADERS
SHEET_RANGE = 'MAIN!A1:Z' 

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
    # print(f"   [+] Adding {user_email} -> {group_email}") 
    try:
        body = {'email': user_email, 'role': 'MEMBER'}
        service.members().insert(groupKey=group_email, body=body).execute()
        print(f"   [+] ADDED: {user_email} -> {group_email}")
    except HttpError as e:
        if e.resp.status == 409:
            # print(f"       (Already in {group_email})")
            pass # Silent success
        elif e.resp.status == 404:
            print(f"       [!] Group '{group_email}' not found in Workspace.")
        else:
            print(f"       [!] Error adding to {group_email}: {e}")

def safe_remove(service, group_email, user_email):
    """Removes user from group. Ignores if not in it."""
    # print(f"   [-] Removing {user_email} <- {group_email}")
    try:
        service.members().delete(groupKey=group_email, memberKey=user_email).execute()
        print(f"   [-] REMOVED: {user_email} <- {group_email}")
    except HttpError as e:
        if e.resp.status == 404:
            # print(f"       (Not in {group_email})")
            pass # Silent success
        else:
            print(f"       [!] Error removing from {group_email}: {e}")

def main():
    print("--- Starting Matrix Sync ---")
    
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
    result = service_sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=SHEET_RANGE).execute()
    rows = result.get('values', [])

    if len(rows) < 2:
        print("Sheet is empty or missing headers.")
        return

    # 3. Parse Headers (Row 1)
    headers = rows[0]
    
    # Create a map of {Column Index: Group Email}
    # We skip Col 0 (User) and Col 1 (Status) -> Start at index 2
    group_map = {}
    print("Found Groups in Headers:")
    for idx, header in enumerate(headers):
        if idx < 2: continue # Skip User/Status columns
        
        # Simple validation: Must look like an email
        if '@' in header:
            group_map[idx] = header.strip()
            print(f" - Col {idx}: {header.strip()}")
            
    print("-" * 30)

    # 4. Process Users (Rows 2 onwards)
    for row in rows[1:]:
        if not row: continue
        
        user_email = row[0].strip()
        if not user_email: continue

        # Read Status (Default to Inactive if missing)
        # Check if row has Col 1, otherwise default Inactive
        status = row[1].strip().lower() if len(row) > 1 else 'inactive'

        print(f"Processing: {user_email} [{status.upper()}]")

        # Iterate through every known group column
        for col_idx, group_email in group_map.items():
            
            # DEFAULT ACTION: REMOVE
            # We assume remove unless we find a specific "Yes"
            should_add = False 

            # Only check for "Yes" if the user is Active
            if status == 'active':
                # Get cell value safely (row might be shorter than headers)
                cell_value = ""
                if col_idx < len(row):
                    cell_value = row[col_idx].strip().lower()
                
                if cell_value == 'yes':
                    should_add = True
            
            # Execute Action
            if should_add:
                safe_add(service_admin, group_email, user_email)
            else:
                # Remove if Status=Inactive OR Cell != Yes OR Cell is Blank
                safe_remove(service_admin, group_email, user_email)

if __name__ == '__main__':
    main()
