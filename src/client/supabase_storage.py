"""
Supabase Storage Backend for eLandings Sync

Provides storage abstraction for landing reports using Supabase PostgreSQL.
Supports normalized schema with 3 tables: landing_reports, landing_report_items, landing_report_stat_areas.
"""

import os
from datetime import datetime
from typing import Any, Optional

from supabase import create_client, Client


class SupabaseStorage:
    """Storage backend using Supabase for landing reports."""

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        """Initialize Supabase client.

        Args:
            url: Supabase project URL. Falls back to SUPABASE_URL env var.
            key: Supabase anon/service key. Falls back to SUPABASE_KEY env var.
        """
        self.url = url or os.getenv("SUPABASE_URL")
        self.key = key or os.getenv("SUPABASE_KEY")

        if not self.url or not self.key:
            raise ValueError("Supabase URL and key are required. Set SUPABASE_URL and SUPABASE_KEY.")

        self.client: Client = create_client(self.url, self.key)

    def _extract_value(self, obj: Any, default: str = "") -> str:
        """Extract text value from dict or return string directly."""
        if isinstance(obj, dict):
            return obj.get("#text", obj.get("@name", str(obj)))
        return str(obj) if obj else default

    def _extract_attr(self, obj: Any, attr: str, default: str = "") -> str:
        """Extract attribute value from dict."""
        if isinstance(obj, dict):
            return obj.get(f"@{attr}", default)
        return default

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse date string to ISO format for PostgreSQL."""
        if not date_str:
            return None
        # Handle various date formats from eLandings
        # e.g., "2017-01-02-09:00", "2017-01-01", "2017-02-02T10:12:47.000-09:00"
        try:
            # Remove timezone suffix like "-09:00" from date-only strings
            if len(date_str) == 16 and date_str[10] == '-':
                date_str = date_str[:10]
            # Parse ISO datetime
            if 'T' in date_str:
                return date_str  # Already ISO format
            # Parse date only
            return date_str[:10]
        except Exception:
            return None

    def _parse_timestamp(self, ts_str: str) -> Optional[str]:
        """Parse timestamp string to ISO format."""
        if not ts_str:
            return None
        try:
            return ts_str  # Supabase handles ISO timestamps
        except Exception:
            return None

    def _flatten_report(self, report: dict) -> dict:
        """Extract flat fields from nested landing report JSON."""
        header = report.get("header", {})
        vessel = header.get("vessel", {})
        port = header.get("port_of_landing", {})
        gear = header.get("gear", {})
        proc_code_owner = header.get("proc_code_owner", {})
        proc_code = proc_code_owner.get("proc_code", {}) if isinstance(proc_code_owner, dict) else {}
        permit_ws = header.get("permit_worksheet", {})

        # Handle permit_worksheet as list or dict
        if isinstance(permit_ws, list):
            permit_ws = permit_ws[0] if permit_ws else {}

        fish_ticket = permit_ws.get("fish_ticket_number", "")

        return {
            "id": int(report.get("landing_report_id", 0)),
            "report_type": self._extract_value(report.get("type_of_landing_report", {})),
            "report_type_name": self._extract_attr(report.get("type_of_landing_report", {}), "name"),
            "status": self._extract_value(report.get("status", {})),
            "status_desc": self._extract_attr(report.get("status", {}), "desc"),
            "vessel_adfg_number": self._extract_value(vessel),
            "vessel_name": self._extract_attr(vessel, "name"),
            "port_code": self._extract_value(port),
            "port_name": self._extract_attr(port, "name"),
            "gear_code": self._extract_value(gear),
            "gear_name": self._extract_attr(gear, "name"),
            "date_of_landing": self._parse_date(header.get("date_of_landing", "")),
            "date_fishing_began": self._parse_date(header.get("date_fishing_began", "")),
            "crew_size": int(header.get("crew_size", 0)) if header.get("crew_size") else None,
            "processor_code": self._extract_value(proc_code),
            "processor_name": self._extract_attr(proc_code, "processor"),
            "fish_ticket_number": fish_ticket,
            "data_entry_user": report.get("@data_entry_user", ""),
            "data_entry_date": self._parse_timestamp(report.get("@data_entry_submit_date", "")),
            "last_change_user": report.get("@last_change_user", ""),
            "last_change_date": self._parse_timestamp(report.get("@last_change_date", "")),
            "raw_json": report,
        }

    def _extract_line_items(self, report: dict) -> list[dict]:
        """Extract line items from landing report."""
        report_id = int(report.get("landing_report_id", 0))
        line_items = report.get("line_item", [])

        # Handle single item as dict
        if isinstance(line_items, dict):
            line_items = [line_items]

        items = []
        for item in line_items:
            species = item.get("species", {})
            condition = item.get("condition_code", {})
            disposition = item.get("disposition_code", {})

            items.append({
                "landing_report_id": report_id,
                "item_number": int(item.get("item_number", 0)),
                "species_code": self._extract_value(species),
                "species_name": self._extract_attr(species, "name"),
                "weight": float(item.get("weight", 0)) if item.get("weight") else None,
                "condition_code": self._extract_value(condition),
                "condition_name": self._extract_attr(condition, "name"),
                "disposition_code": self._extract_value(disposition),
                "disposition_name": self._extract_attr(disposition, "name"),
                "fish_ticket_number": item.get("fish_ticket_number", ""),
            })

        return items

    def _extract_stat_areas(self, report: dict) -> list[dict]:
        """Extract stat areas from landing report."""
        report_id = int(report.get("landing_report_id", 0))
        header = report.get("header", {})
        stat_areas = header.get("stat_area_worksheet", [])

        # Handle single area as dict
        if isinstance(stat_areas, dict):
            stat_areas = [stat_areas]

        areas = []
        for area in stat_areas:
            stat_area = area.get("stat_area", {})

            areas.append({
                "landing_report_id": report_id,
                "item_number": int(area.get("item_number", 0)),
                "stat_area": self._extract_value(stat_area),
                "fed_area": self._extract_attr(stat_area, "fed_area"),
                "iphc_area": self._extract_attr(stat_area, "iphc_area"),
                "percent": int(area.get("percent", 0)) if area.get("percent") else None,
            })

        return areas

    def save_report(self, report: dict) -> bool:
        """Save a landing report to Supabase (upsert).

        Args:
            report: Parsed landing report dict from XML.

        Returns:
            True if successful, False otherwise.
        """
        try:
            report_id = int(report.get("landing_report_id", 0))

            # Flatten and upsert main report
            flat_report = self._flatten_report(report)
            self.client.table("landing_reports").upsert(flat_report).execute()

            # Delete existing child records before inserting new ones
            self.client.table("landing_report_items").delete().eq(
                "landing_report_id", report_id
            ).execute()
            self.client.table("landing_report_stat_areas").delete().eq(
                "landing_report_id", report_id
            ).execute()

            # Insert line items
            line_items = self._extract_line_items(report)
            if line_items:
                self.client.table("landing_report_items").insert(line_items).execute()

            # Insert stat areas
            stat_areas = self._extract_stat_areas(report)
            if stat_areas:
                self.client.table("landing_report_stat_areas").insert(stat_areas).execute()

            return True
        except Exception as e:
            print(f"Error saving report {report.get('landing_report_id')}: {e}")
            return False

    def get_report(self, report_id: int) -> Optional[dict]:
        """Fetch a single report by ID.

        Returns the raw_json field which contains the full original report.
        """
        try:
            result = self.client.table("landing_reports").select("raw_json").eq(
                "id", report_id
            ).single().execute()
            return result.data.get("raw_json") if result.data else None
        except Exception:
            return None

    def get_all_reports(self) -> list[dict]:
        """Fetch all reports (flat data, not full JSON).

        Returns list of flattened report dicts for index building.
        """
        try:
            result = self.client.table("landing_reports").select(
                "id, report_type, report_type_name, status, status_desc, "
                "vessel_adfg_number, vessel_name, port_code, port_name, "
                "gear_code, gear_name, date_of_landing, fish_ticket_number, "
                "last_change_date"
            ).order("date_of_landing", desc=True).execute()
            return result.data or []
        except Exception as e:
            print(f"Error fetching reports: {e}")
            return []

    def get_report_with_items(self, report_id: int) -> Optional[dict]:
        """Fetch report with its line items and stat areas."""
        try:
            # Get main report
            report_result = self.client.table("landing_reports").select("*").eq(
                "id", report_id
            ).single().execute()

            if not report_result.data:
                return None

            report = report_result.data

            # Get line items
            items_result = self.client.table("landing_report_items").select("*").eq(
                "landing_report_id", report_id
            ).order("item_number").execute()
            report["line_items"] = items_result.data or []

            # Get stat areas
            areas_result = self.client.table("landing_report_stat_areas").select("*").eq(
                "landing_report_id", report_id
            ).order("item_number").execute()
            report["stat_areas"] = areas_result.data or []

            return report
        except Exception as e:
            print(f"Error fetching report {report_id}: {e}")
            return None

    def get_existing_report_ids(self) -> set[str]:
        """Get set of all report IDs in the database."""
        try:
            result = self.client.table("landing_reports").select("id").execute()
            return {str(r["id"]) for r in (result.data or [])}
        except Exception as e:
            print(f"Error fetching report IDs: {e}")
            return set()

    def get_sync_state(self) -> dict:
        """Get sync state from database."""
        try:
            result = self.client.table("sync_state").select("*").eq("id", 1).execute()
            if result.data:
                return {
                    "last_sync": result.data[0].get("last_sync"),
                    "synced_reports": list(self.get_existing_report_ids()),
                }
            return {"last_sync": None, "synced_reports": []}
        except Exception:
            return {"last_sync": None, "synced_reports": []}

    def save_sync_state(self, last_sync: str) -> bool:
        """Save sync state to database."""
        try:
            self.client.table("sync_state").upsert({
                "id": 1,
                "last_sync": last_sync,
            }).execute()
            return True
        except Exception as e:
            print(f"Error saving sync state: {e}")
            return False

    def get_report_items_by_species(self, species_code: str) -> list[dict]:
        """Query line items by species code."""
        try:
            result = self.client.table("landing_report_items").select(
                "*, landing_reports(vessel_name, port_name, date_of_landing)"
            ).eq("species_code", species_code).execute()
            return result.data or []
        except Exception:
            return []

    def get_reports_by_vessel(self, vessel_adfg_number: str) -> list[dict]:
        """Query reports by vessel ADF&G number."""
        try:
            result = self.client.table("landing_reports").select("*").eq(
                "vessel_adfg_number", vessel_adfg_number
            ).order("date_of_landing", desc=True).execute()
            return result.data or []
        except Exception:
            return []
