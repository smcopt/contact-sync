import os
import time
import google.auth
import google.auth.transport.requests
import google.auth.iam
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURATION ---
# 1. SCOPES: Permissions we need
SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.group',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

# 2. SHEET SETTINGS
# "MAIN" is your tab name. "A2:L" covers User(A), Status(B), and Groups(C-L)
SHEET_RANGE = 'MAIN!A2:L'

def get_delegated_credentials():
    """
    Authenticates using Workload Identity (Keyless) and then 
    impersonates the Admin user to manage Groups.
    """
    admin_email = os.environ.get('WORKSPACE_ADMIN_EMAIL')
    
    # 1. Get the Service Account credentials from the GitHub environment
    # We ask for 'cloud-platform' scope so we can call the IAM API to sign things
    creds, project_id = google.auth.default(
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    
    # 2. Create a "Signer"
    # Since we don't have a private key file, we ask Google's IAM API to sign for us.
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    signer = google.auth.iam.Signer(auth_req, creds, creds.service_account_email)

    # 3. Create the final credentials that act as the Admin
    delegated_creds = service_account.Credentials(
        signer,
        creds.service_account_email,
        'https://oauth2.googleapis.com/token',
        scopes=SCOPES,
        subject=admin_email
    )
    
    return delegated_creds

def safe_add(service, group_email, user_email):
    """Adds a user to a group. Skips if already there."""
    print(f"   [+] Adding {user_email} to {group_email}...")
    try:
        body = {'email': user_email, 'role': 'MEMBER'}
        service.members().insert(groupKey=group_email, body=body).execute()
        print("       -> Success.")
    except HttpError as e:
        if e.resp.status == 409: # 409 Conflict = Already exists
            print("       -> Already a member.")
        elif e.resp.status == 404:
            print(f"       -> Error: Group '{group_email}' not found.")
        else:
            print(f"       -> Error: {e}")

def safe_remove(service, group_email, user_email):
    """Removes a user from a group. Skips if they aren't in it."""
    print(f"   [-] Removing {user_email} from {group_email}...")
    try:
        service.members().delete(groupKey=group_email, memberKey=user_email).execute()
        print("       -> Success.")
    except HttpError as e:
        if e.resp.status == 404: # 404 = Member or Group not found
            print("       -> Not a member (or group doesn't exist).")
        else:
            print(f"       -> Error: {e}")

def main():
    print("--- Starting Sync Engine ---")
    
    # 1. Authenticate
    try:
        creds = get_delegated_credentials()
        service_sheets = build('sheets', 'v4', credentials=creds)
        service_admin = build('admin', 'directory_v1', credentials=creds)
    except Exception as e:
        print(f"FATAL: Authentication failed. Check Secrets. Error: {e}")
        return

    # 2. Read Sheet
    sheet_id = os.environ.get('GOOGLE_SHEET_ID')
    print(f"Reading Sheet ID: {sheet_id} | Range: {SHEET_RANGE}")
    
    try:
        result = service_sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=SHEET_RANGE).execute()
        rows = result.get('values', [])
    except HttpError as e:
        print(f"FATAL: Could not read sheet. Check permissions. Error: {e}")
        return

    if not rows:
        print("No data found in the sheet.")
        return

    # 3. Build 'Master List' of Groups
    # We scan columns C through L (index 2 to end) of every row to find ALL groups mentioned.
    all_known_groups = set()
    for row in rows:
        if len(row) > 2:
            # Check every cell from Column C onwards
            for cell in row[2:]:
                cleaned_group = cell.strip()
                if cleaned_group: # If cell is not empty
                    all_known_groups.add(cleaned_group)
    
    print(f"Found {len(all_known_groups)} unique groups in the sheet.")
    print("-" * 40)

    # 4. Process Each User
    for row in rows:
        # Basic validation
        if not row: continue
        
        user_email = row[0].strip()
        if not user_email: continue # Skip empty rows

        # Read Status (Default to Inactive if missing)
        status = row[1].strip().lower() if len(row) > 1 else 'inactive'

        # Read Desired Groups (From Col C onwards)
        desired_groups = set()
        if len(row) > 2:
            for cell in row[2:]:
                if cell.strip():
                    desired_groups.add(cell.strip())

        print(f"Processing: {user_email} [{status.upper()}]")

        # LOGIC ENGINE
        if status == 'inactive':
            # Rule: Remove from EVERYTHING found in the sheet
            for group in all_known_groups:
                safe_remove(service_admin, group, user_email)

        elif status == 'active':
            # Rule 1: Add to desired groups
            for group in desired_groups:
                safe_add(service_admin, group, user_email)
            
            # Rule 2: Remove from groups they are NOT supposed to be in
            # (Any group in 'all_known_groups' that is NOT in 'desired_groups')
            groups_to_remove = all_known_groups - desired_groups
            for group in groups_to_remove:
                safe_remove(service_admin, group, user_email)
        
        print("-" * 20)

if __name__ == '__main__':
    main()
