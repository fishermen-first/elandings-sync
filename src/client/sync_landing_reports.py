"""
eLandings Landing Report Sync

Pulls landing reports from eLandings and saves them locally.
Supports incremental sync based on last modified date.
"""

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from elandings_client import ELandingsClient


def xml_to_dict(element: ET.Element) -> dict[str, Any]:
    """Convert XML element to dictionary, preserving attributes."""
    result: dict[str, Any] = {}

    # Add attributes with @ prefix
    for key, value in element.attrib.items():
        result[f"@{key}"] = value

    # Process child elements
    children = list(element)
    if children:
        child_dict: dict[str, Any] = {}
        for child in children:
            child_data = xml_to_dict(child)
            tag = child.tag

            # Handle multiple elements with same tag
            if tag in child_dict:
                if not isinstance(child_dict[tag], list):
                    child_dict[tag] = [child_dict[tag]]
                child_dict[tag].append(child_data)
            else:
                child_dict[tag] = child_data

        result.update(child_dict)
    elif element.text and element.text.strip():
        # Element has text content
        if result:  # Has attributes
            result["#text"] = element.text.strip()
        else:
            return element.text.strip()  # type: ignore

    return result


def parse_landing_report_summary(xml_str: str) -> list[dict[str, Any]]:
    """Parse landing report search results into list of report summaries."""
    root = ET.fromstring(xml_str)
    reports = []

    for summary in root.findall(".//landing_report_summary"):
        report = xml_to_dict(summary)
        reports.append(report)

    return reports


def parse_landing_report(xml_str: str) -> dict[str, Any]:
    """Parse a full landing report XML into dictionary."""
    root = ET.fromstring(xml_str)
    return xml_to_dict(root)


class LandingReportSync:
    """Syncs landing reports from eLandings to local storage."""

    def __init__(self, output_dir: str = "data/landing_reports"):
        self.client = ELandingsClient()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.output_dir / ".sync_state.json"

    def _load_state(self) -> dict[str, Any]:
        """Load sync state from file."""
        if self.state_file.exists():
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        return {"last_sync": None, "synced_reports": []}

    def _save_state(self, state: dict[str, Any]) -> None:
        """Save sync state to file."""
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str, ensure_ascii=False)

    def _save_report(self, report: dict[str, Any]) -> Path:
        """Save a landing report to JSON file."""
        report_id = report.get("landing_report_id", "unknown")
        if isinstance(report_id, dict):
            report_id = report_id.get("#text", "unknown")

        filename = self.output_dir / f"landing_report_{report_id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str, ensure_ascii=False)
        return filename

    def _get_existing_report_ids(self) -> set[str]:
        """Get set of report IDs already saved locally."""
        existing = set()
        for f in self.output_dir.glob("landing_report_*.json"):
            report_id = f.stem.replace("landing_report_", "")
            existing.add(report_id)
        return existing

    def sync(
        self,
        since: str | None = None,
        operation_id: str = "",
        full_refresh: bool = False,
        skip_existing: bool = True,
        progress_callback=None,
    ) -> dict[str, Any]:
        """
        Sync landing reports from eLandings.

        Args:
            since: ISO date string (YYYY-MM-DD) to sync reports modified since.
                   If None, uses last sync date from state file.
            operation_id: Filter to specific operation (optional)
            full_refresh: If True, ignores last sync date and pulls all reports
            skip_existing: If True, skip reports already saved locally
            progress_callback: Optional callback(current, total, report_id) for progress updates

        Returns:
            Summary of sync results
        """
        state = self._load_state()

        # Determine the date to sync from
        if full_refresh:
            date_modified_start = ""
        elif since:
            date_modified_start = f"{since}T00:00:00"
        elif state.get("last_sync"):
            date_modified_start = state["last_sync"]
        else:
            # First sync - get last 30 days by default
            thirty_days_ago = datetime.now() - timedelta(days=30)
            date_modified_start = thirty_days_ago.strftime("%Y-%m-%dT00:00:00")

        sync_start = datetime.now()
        print(f"Syncing landing reports modified since: {date_modified_start or 'all time'}")

        # Step 1: Find reports
        print("Searching for reports...")
        reports_xml = self.client.find_user_landing_reports(
            operation_id=operation_id,
            date_modified_start=date_modified_start,
        )

        if not reports_xml:
            print("No response from server")
            return {"error": "No response", "reports_synced": 0}

        summaries = parse_landing_report_summary(reports_xml)
        print(f"Found {len(summaries)} reports to sync")

        # Get existing reports to skip
        existing_ids = self._get_existing_report_ids() if skip_existing else set()

        # Step 2: Fetch full details for each report
        synced = []
        skipped = []
        errors = []

        for i, summary in enumerate(summaries, 1):
            report_id = summary.get("landing_report_id", {})
            if isinstance(report_id, dict):
                report_id = report_id.get("#text", "")

            # Skip if already exists locally
            if skip_existing and str(report_id) in existing_ids:
                skipped.append(report_id)
                print(f"  [{i}/{len(summaries)}] Skipping report {report_id} (already exists)")
                if progress_callback:
                    progress_callback(i, len(summaries), report_id, "skipped")
                continue

            print(f"  [{i}/{len(summaries)}] Fetching report {report_id}...", end=" ")
            if progress_callback:
                progress_callback(i, len(summaries), report_id, "fetching")

            try:
                report_xml = self.client.get_landing_report(str(report_id))
                if report_xml:
                    report = parse_landing_report(report_xml)
                    filepath = self._save_report(report)
                    synced.append({
                        "report_id": report_id,
                        "file": str(filepath),
                    })
                    print("OK")
                else:
                    errors.append({"report_id": report_id, "error": "Empty response"})
                    print("EMPTY")
            except Exception as e:
                errors.append({"report_id": report_id, "error": str(e)})
                print(f"ERROR: {e}")

        # Update state
        state["last_sync"] = sync_start.strftime("%Y-%m-%dT%H:%M:%S")
        state["synced_reports"] = list(set(
            state.get("synced_reports", []) +
            [r["report_id"] for r in synced]
        ))
        self._save_state(state)

        result = {
            "sync_date": sync_start.isoformat(),
            "date_filter": date_modified_start,
            "reports_found": len(summaries),
            "reports_synced": len(synced),
            "reports_skipped": len(skipped),
            "reports_failed": len(errors),
            "synced": synced,
            "errors": errors,
        }

        print(f"\nSync complete: {len(synced)} synced, {len(skipped)} skipped, {len(errors)} failed")
        return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync eLandings landing reports")
    parser.add_argument("--since", help="Sync reports modified since date (YYYY-MM-DD)")
    parser.add_argument("--operation", default="", help="Filter by operation ID")
    parser.add_argument("--full", action="store_true", help="Full refresh (ignore last sync)")
    parser.add_argument("--output", default="data/landing_reports", help="Output directory")

    args = parser.parse_args()

    sync = LandingReportSync(output_dir=args.output)
    result = sync.sync(
        since=args.since,
        operation_id=args.operation,
        full_refresh=args.full,
    )

    print("\n" + "=" * 60)
    print("SYNC SUMMARY")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))
