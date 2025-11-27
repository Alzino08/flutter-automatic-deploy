#!/usr/bin/env python3
"""
=============================================================================
Flutter Automatic Deploy - Google Play Store Auto-Upload Script
=============================================================================

Built by Filip Kowalski
X: @filippkowalski
Website: fkowalski.com
Support: https://buymeacoffee.com/filipkowalski

Uploads an Android App Bundle (AAB) to Google Play and optionally
submits it to a release track (internal, alpha, beta, production).

=============================================================================

Usage:
    python3 submit_to_google_play.py <version> [options]

Options:
    --project-path PATH    Path to Flutter project (default: current directory)
    --track TRACK          Release track: internal, alpha, beta, production (default: production)
    --rollout PERCENT      Rollout percentage for production (default: 100)
    --draft                Create as draft (don't submit for review)
    --release-notes TEXT   Release notes (default: "Bug fixes and improvements")

Examples:
    python3 submit_to_google_play.py 1.13.0+32
    python3 submit_to_google_play.py 1.13.0+32 --track internal
    python3 submit_to_google_play.py 1.13.0+32 --track production --rollout 10
    python3 submit_to_google_play.py 1.13.0+32 --draft

Environment Variables:
    GOOGLE_PLAY_SERVICE_ACCOUNT    Path to service account JSON (default: ~/.google-play/service-account.json)

Requirements:
    pip3 install google-api-python-client google-auth
"""

import os
import sys
import glob
import argparse
import time
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("\033[91mError: Missing required dependencies\033[0m")
    print("Install with: pip3 install google-api-python-client google-auth")
    sys.exit(1)

# Colors for terminal output
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
NC = '\033[0m'  # No Color

# Configuration
SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_PLAY_SERVICE_ACCOUNT",
    os.path.expanduser("~/.google-play/service-account.json")
)
SCOPES = ['https://www.googleapis.com/auth/androidpublisher']


def get_package_name(project_path: str) -> str:
    """Extract package name from build.gradle or AndroidManifest.xml"""

    # Try build.gradle first
    gradle_paths = [
        os.path.join(project_path, "android/app/build.gradle"),
        os.path.join(project_path, "android/app/build.gradle.kts"),
    ]

    for gradle_path in gradle_paths:
        if os.path.exists(gradle_path):
            with open(gradle_path, 'r') as f:
                content = f.read()
                # Look for applicationId
                import re
                match = re.search(r'applicationId\s*[=:]\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)

    # Try AndroidManifest.xml
    manifest_path = os.path.join(project_path, "android/app/src/main/AndroidManifest.xml")
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r') as f:
            content = f.read()
            import re
            match = re.search(r'package="([^"]+)"', content)
            if match:
                return match.group(1)

    return None


def find_aab_file(project_path: str) -> str:
    """Find the release AAB file"""
    aab_pattern = os.path.join(project_path, "build/app/outputs/bundle/release/*.aab")
    aab_files = glob.glob(aab_pattern)

    if not aab_files:
        return None

    # Return the most recently modified file
    return max(aab_files, key=os.path.getmtime)


def upload_to_google_play(
    package_name: str,
    aab_path: str,
    track: str = "production",
    rollout_percentage: float = 100.0,
    release_notes: str = "Bug fixes and improvements",
    draft: bool = False
):
    """Upload AAB to Google Play and create a release"""

    print(f"{CYAN}Authenticating with Google Play API...{NC}")

    # Check if service account file exists
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"{RED}Error: Service account file not found{NC}")
        print(f"{YELLOW}Expected location: {SERVICE_ACCOUNT_FILE}{NC}")
        print(f"\n{CYAN}Setup instructions:{NC}")
        print("1. Go to Google Cloud Console (console.cloud.google.com)")
        print("2. Create a new project or select existing one")
        print("3. Enable 'Google Play Android Developer API'")
        print("4. Go to IAM & Admin > Service Accounts")
        print("5. Create a Service Account and download JSON key")
        print("6. Go to Google Play Console > Users and permissions")
        print("7. Invite the service account email with 'Release manager' access")
        print(f"8. Save the JSON key to {SERVICE_ACCOUNT_FILE}")
        return False

    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )

        service = build('androidpublisher', 'v3', credentials=credentials)

        print(f"{GREEN}✓ Authenticated successfully{NC}")

        # Create a new edit
        print(f"{CYAN}Creating new edit...{NC}")
        edit_request = service.edits().insert(body={}, packageName=package_name)
        edit = edit_request.execute()
        edit_id = edit['id']
        print(f"{GREEN}✓ Edit created: {edit_id}{NC}")

        # Upload the AAB
        print(f"{CYAN}Uploading AAB file...{NC}")
        print(f"{BLUE}   File: {os.path.basename(aab_path)}{NC}")
        print(f"{BLUE}   Size: {os.path.getsize(aab_path) / (1024*1024):.1f} MB{NC}")

        media = MediaFileUpload(aab_path, mimetype='application/octet-stream', resumable=True)

        bundle_request = service.edits().bundles().upload(
            packageName=package_name,
            editId=edit_id,
            media_body=media
        )

        # Handle resumable upload with progress
        response = None
        while response is None:
            status, response = bundle_request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                print(f"\r{BLUE}   Progress: {progress}%{NC}", end='')

        print(f"\n{GREEN}✓ Upload complete{NC}")

        version_code = response['versionCode']
        print(f"{BLUE}   Version code: {version_code}{NC}")

        # Create release
        print(f"{CYAN}Creating release on '{track}' track...{NC}")

        release_config = {
            'versionCodes': [version_code],
            'releaseNotes': [
                {
                    'language': 'en-US',
                    'text': release_notes
                }
            ]
        }

        if draft:
            release_config['status'] = 'draft'
            print(f"{YELLOW}   Creating as DRAFT (won't be submitted){NC}")
        else:
            if track == 'production' and rollout_percentage < 100:
                release_config['status'] = 'inProgress'
                release_config['userFraction'] = rollout_percentage / 100.0
                print(f"{BLUE}   Staged rollout: {rollout_percentage}%{NC}")
            else:
                release_config['status'] = 'completed'

        track_request = service.edits().tracks().update(
            packageName=package_name,
            editId=edit_id,
            track=track,
            body={'releases': [release_config]}
        )
        track_request.execute()

        print(f"{GREEN}✓ Release created on '{track}' track{NC}")

        # Commit the edit
        print(f"{CYAN}Committing changes...{NC}")
        commit_request = service.edits().commit(
            packageName=package_name,
            editId=edit_id
        )
        commit_request.execute()

        print(f"{GREEN}✓ Changes committed to Google Play{NC}")

        # Summary
        print()
        print(f"{GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")
        print(f"{GREEN}Google Play submission complete!{NC}")
        print(f"{GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")
        print(f"{BLUE}   Package: {package_name}{NC}")
        print(f"{BLUE}   Track: {track}{NC}")
        print(f"{BLUE}   Version code: {version_code}{NC}")

        if draft:
            print(f"{YELLOW}   Status: DRAFT - go to Play Console to submit{NC}")
        elif track == 'production':
            if rollout_percentage < 100:
                print(f"{BLUE}   Rollout: {rollout_percentage}% staged rollout{NC}")
            else:
                print(f"{BLUE}   Status: Submitted for review{NC}")
        else:
            print(f"{BLUE}   Status: Published to {track}{NC}")

        return True

    except Exception as e:
        print(f"{RED}Error: {str(e)}{NC}")

        if "403" in str(e):
            print(f"\n{YELLOW}Permission denied. Check that:{NC}")
            print("1. Service account has 'Release manager' or 'Admin' access in Play Console")
            print("2. The service account was invited via Users and permissions")
            print("3. The app package name is correct")
        elif "404" in str(e):
            print(f"\n{YELLOW}App not found. Check that:{NC}")
            print("1. The package name matches your app in Play Console")
            print("2. The app has been created in Play Console")

        return False


def main():
    parser = argparse.ArgumentParser(
        description='Upload and submit Android app to Google Play Store',
        epilog='Built by Filip Kowalski | @filippkowalski | fkowalski.com'
    )
    parser.add_argument('version', help='Version string (e.g., 1.13.0+32)')
    parser.add_argument('--project-path', default='.', help='Path to Flutter project')
    parser.add_argument('--track', default='production',
                       choices=['internal', 'alpha', 'beta', 'production'],
                       help='Release track (default: production)')
    parser.add_argument('--rollout', type=float, default=100,
                       help='Rollout percentage for production (default: 100)')
    parser.add_argument('--draft', action='store_true',
                       help='Create as draft without submitting')
    parser.add_argument('--release-notes', default='Bug fixes and improvements',
                       help='Release notes text')
    parser.add_argument('--package-name', help='Override package name detection')

    args = parser.parse_args()

    project_path = os.path.abspath(args.project_path)

    print()
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")
    print(f"{CYAN}Google Play Auto-Upload{NC}")
    print(f"{CYAN}Built by Filip Kowalski | @filippkowalski | fkowalski.com{NC}")
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{NC}")
    print(f"{BLUE}   Version: {args.version}{NC}")
    print(f"{BLUE}   Track: {args.track}{NC}")
    print()

    # Get package name
    if args.package_name:
        package_name = args.package_name
    else:
        package_name = get_package_name(project_path)

    if not package_name:
        print(f"{RED}Error: Could not detect package name{NC}")
        print(f"{YELLOW}Use --package-name to specify manually{NC}")
        sys.exit(1)

    print(f"{BLUE}Package: {package_name}{NC}")

    # Find AAB file
    aab_path = find_aab_file(project_path)

    if not aab_path:
        print(f"{RED}Error: No AAB file found{NC}")
        print(f"{YELLOW}Run 'flutter build appbundle --release' first{NC}")
        sys.exit(1)

    print(f"{BLUE}AAB: {os.path.basename(aab_path)}{NC}")
    print()

    # Upload and submit
    success = upload_to_google_play(
        package_name=package_name,
        aab_path=aab_path,
        track=args.track,
        rollout_percentage=args.rollout,
        release_notes=args.release_notes,
        draft=args.draft
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
