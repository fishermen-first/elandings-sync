#!/usr/bin/env python3
"""
Migration Script: Local JSON files to Supabase

Migrates existing landing report JSON files to Supabase database.
Run this once after setting up Supabase tables to import historical data.

Usage:
    python scripts/migrate_to_supabase.py

Environment variables required:
    SUPABASE_URL - Your Supabase project URL
    SUPABASE_KEY - Your Supabase anon/service key
"""

import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "client"))

from dotenv import load_dotenv

load_dotenv()

from supabase_storage import SupabaseStorage


def migrate_reports(data_dir: str = "data/landing_reports", batch_size: int = 50):
    """Migrate all JSON reports to Supabase.

    Args:
        data_dir: Directory containing landing_report_*.json files
        batch_size: Number of reports to process before showing progress
    """
    # Initialize Supabase
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY environment variables required.")
        print("Set them in your .env file or export them.")
        sys.exit(1)

    print(f"Connecting to Supabase: {url[:40]}...")
    storage = SupabaseStorage(url=url, key=key)

    # Find all JSON files
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"ERROR: Data directory not found: {data_dir}")
        sys.exit(1)

    json_files = list(data_path.glob("landing_report_*.json"))
    total = len(json_files)

    if total == 0:
        print("No landing report files found to migrate.")
        sys.exit(0)

    print(f"Found {total} reports to migrate.")

    # Check what's already in Supabase
    existing_ids = storage.get_existing_report_ids()
    print(f"Already in Supabase: {len(existing_ids)} reports")

    # Migrate each file
    migrated = 0
    skipped = 0
    errors = []

    for i, file_path in enumerate(json_files, 1):
        report_id = file_path.stem.replace("landing_report_", "")

        # Skip if already exists
        if report_id in existing_ids:
            skipped += 1
            continue

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                report = json.load(f)

            success = storage.save_report(report)
            if success:
                migrated += 1
            else:
                errors.append({"id": report_id, "error": "save_report returned False"})

        except Exception as e:
            errors.append({"id": report_id, "error": str(e)})

        # Progress update
        if i % batch_size == 0 or i == total:
            print(f"Progress: {i}/{total} - Migrated: {migrated}, Skipped: {skipped}, Errors: {len(errors)}")

    # Final summary
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Total files:     {total}")
    print(f"Migrated:        {migrated}")
    print(f"Skipped (exist): {skipped}")
    print(f"Errors:          {len(errors)}")

    if errors:
        print("\nErrors:")
        for err in errors[:10]:  # Show first 10 errors
            print(f"  - Report {err['id']}: {err['error']}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    # Update sync state
    if migrated > 0:
        from datetime import datetime
        storage.save_sync_state(datetime.now().isoformat())
        print("\nSync state updated.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate JSON reports to Supabase")
    parser.add_argument(
        "--data-dir",
        default="data/landing_reports",
        help="Directory containing JSON files (default: data/landing_reports)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Progress update frequency (default: 50)"
    )

    args = parser.parse_args()
    migrate_reports(data_dir=args.data_dir, batch_size=args.batch_size)
