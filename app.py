"""
eLandings Sync - Streamlit Demo

A prototype demonstrating automated landing report sync from eLandings.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src" / "client"))

from elandings_client import ELandingsClient, pretty_print_xml
from sync_landing_reports import LandingReportSync, parse_landing_report

st.set_page_config(
    page_title="eLandings Sync",
    page_icon="",
    layout="wide",
)

# App credentials
APP_LOGIN = "eSync_demo"
APP_PASSWORD = "demo_123"


def check_login():
    """Display login form and validate credentials."""
    if st.session_state.get("authenticated"):
        return True

    st.title("eLandings Sync")
    st.markdown("Please log in to continue.")

    with st.form("login_form"):
        username = st.text_input("Login")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

        if submitted:
            if username == APP_LOGIN and password == APP_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid login or password")

    return False


# Check authentication before showing the app
if not check_login():
    st.stop()

st.title("eLandings Sync Prototype")
st.markdown("""
This prototype demonstrates **automated landing report sync** from the eLandings API.
Instead of manually entering data from fish tickets, reports are pulled directly via the API.
""")


def get_credentials():
    """Get eLandings credentials from Streamlit secrets or environment."""
    # Try Streamlit secrets first (for cloud deployment)
    try:
        if hasattr(st, "secrets") and len(st.secrets) > 0 and "ELANDINGS_USER" in st.secrets:
            return {
                "user": st.secrets["ELANDINGS_USER"],
                "password": st.secrets["ELANDINGS_PASSWORD"],
                "schema_version": st.secrets.get("ELANDINGS_SCHEMA_VERSION", "1.0"),
            }
    except Exception:
        pass  # No secrets file, fall through to environment variables

    # Fall back to environment variables
    return {
        "user": os.getenv("ELANDINGS_USER"),
        "password": os.getenv("ELANDINGS_PASSWORD"),
        "schema_version": os.getenv("ELANDINGS_SCHEMA_VERSION", "1.0"),
    }


def extract_value(obj, default=""):
    """Extract text value from dict or return string directly."""
    if isinstance(obj, dict):
        return obj.get("#text", obj.get("@name", str(obj)))
    return str(obj) if obj else default


def landing_report_to_row(report: dict) -> dict:
    """Convert a landing report JSON to a flat row for display."""
    header = report.get("header", {})
    line_items = report.get("line_item", [])
    if isinstance(line_items, dict):
        line_items = [line_items]

    # Sum up weights from all line items
    total_weight = 0
    species_list = []
    for item in line_items:
        try:
            weight = float(item.get("weight", 0))
            total_weight += weight
        except (ValueError, TypeError):
            pass
        species = item.get("species", {})
        species_name = species.get("@name", "") if isinstance(species, dict) else ""
        if species_name and species_name not in species_list:
            species_list.append(species_name)

    # Get vessel number (the #text value) - this is the ADF&G vessel number
    vessel_obj = header.get("vessel", {})
    vessel_num = vessel_obj.get("#text", "") if isinstance(vessel_obj, dict) else ""

    return {
        "Report ID": extract_value(report.get("landing_report_id")),
        "Status": extract_value(report.get("status", {}).get("@desc", "")),
        "Type": extract_value(report.get("type_of_landing_report", {}).get("@name", "")),
        "Vessel": extract_value(header.get("vessel", {}).get("@name", "")),
        "ADF&G Vessel #": vessel_num,
        "Port": extract_value(header.get("port_of_landing", {}).get("@name", "")),
        "Landing Date": extract_value(header.get("date_of_landing", "")),
        "Species": ", ".join(species_list),
        "Total Weight (lbs)": f"{total_weight:,.0f}",
        "Last Modified": report.get("@last_change_date", "")[:10],
    }


# Sidebar for configuration
with st.sidebar:
    st.header("Configuration")

    creds = get_credentials()

    if not creds["user"]:
        st.warning("No credentials found. Using demo mode with sample data.")
        demo_mode = True
    else:
        st.success(f"Connected as: **{creds['user']}**")
        demo_mode = False

    st.divider()

    st.markdown("""
    ### About
    This prototype pulls landing reports directly from the eLandings SOAP API,
    eliminating manual data entry from fish tickets.
    """)

    st.divider()

    if st.button("Logout"):
        st.session_state["authenticated"] = False
        st.rerun()

# Main content
tab1, tab2, tab3, tab4 = st.tabs(["Landing Reports", "Sync Data", "Report Details", "Data Dictionary"])

@st.cache_data
def build_report_index(data_dir: str) -> pd.DataFrame:
    """Build a lightweight index of all reports for fast filtering."""
    data_path = Path(data_dir)
    index_data = []

    for f in data_path.glob("landing_report_*.json"):
        try:
            with open(f, encoding="utf-8", errors="replace") as fp:
                report = json.load(fp)
                header = report.get("header", {})

                # Extract vessel number - this is the ADF&G vessel number
                vessel_obj = header.get("vessel", {})
                vessel_num = vessel_obj.get("#text", "") if isinstance(vessel_obj, dict) else ""

                # Extract species list
                line_items = report.get("line_item", [])
                if isinstance(line_items, dict):
                    line_items = [line_items]
                species_list = []
                for item in line_items:
                    species = item.get("species", {})
                    species_name = species.get("@name", "") if isinstance(species, dict) else ""
                    if species_name and species_name not in species_list:
                        species_list.append(species_name)

                index_data.append({
                    "file": str(f),
                    "Report ID": extract_value(report.get("landing_report_id")),
                    "Vessel": extract_value(header.get("vessel", {}).get("@name", "")),
                    "ADF&G Vessel #": vessel_num,
                    "Species": ", ".join(species_list),
                    "Landing Date": extract_value(header.get("date_of_landing", "")),
                    "Last Modified": report.get("@last_change_date", "")[:10] if report.get("@last_change_date") else "",
                })
        except Exception:
            pass

    df = pd.DataFrame(index_data)
    # Sort by landing date descending (most recent first)
    if not df.empty and "Landing Date" in df.columns:
        df = df.sort_values("Landing Date", ascending=False)
    return df


def load_full_reports(file_paths: list[str]) -> pd.DataFrame:
    """Load full report data for display."""
    reports = []
    for f in file_paths:
        try:
            with open(f, encoding="utf-8", errors="replace") as fp:
                report = json.load(fp)
                reports.append(landing_report_to_row(report))
        except Exception:
            pass
    return pd.DataFrame(reports)


with tab1:
    st.header("Landing Reports")

    # Check for local data
    data_dir = Path("data/landing_reports")

    if data_dir.exists():
        json_files = list(data_dir.glob("landing_report_*.json"))

        if json_files:
            # Build cached index of all reports (with spinner on first load)
            with st.spinner("Building report index..."):
                index_df = build_report_index(str(data_dir))

            if not index_df.empty:
                st.info(f"Found **{len(index_df)}** landing reports in local storage")

                # Filters - use index for filter options (all reports)
                col1, col2 = st.columns(2)
                with col1:
                    all_vessels = sorted(index_df["Vessel"].dropna().unique())
                    vessel_filter = st.multiselect(
                        "Filter by Vessel",
                        options=all_vessels,
                    )
                with col2:
                    species_filter = st.text_input("Filter by Species (contains)")

                # Apply filters to index
                filtered_index = index_df.copy()
                if vessel_filter:
                    filtered_index = filtered_index[filtered_index["Vessel"].isin(vessel_filter)]
                if species_filter:
                    filtered_index = filtered_index[
                        filtered_index["Species"].str.contains(species_filter, case=False, na=False)
                    ]

                # Determine which reports to load
                has_filter = bool(vessel_filter or species_filter)
                if has_filter:
                    # Show all matching reports when filtered
                    files_to_load = filtered_index["file"].tolist()
                    showing_msg = f"Showing all **{len(files_to_load)}** matching reports"
                else:
                    # Show top 100 most recent when no filter
                    files_to_load = filtered_index.head(100)["file"].tolist()
                    if len(filtered_index) > 100:
                        showing_msg = f"Showing **100** most recent reports (use filters to see all **{len(filtered_index)}**)"
                    else:
                        showing_msg = f"Showing all **{len(files_to_load)}** reports"

                st.caption(showing_msg)

                # Load full data only for displayed reports
                if files_to_load:
                    df = load_full_reports(files_to_load)

                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True,
                    )

                    # Summary stats
                    st.subheader("Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Total Reports", len(df))
                    col2.metric("Unique Vessels", df["Vessel"].nunique())
                    col3.metric("Unique Ports", df["Port"].nunique())
                    col4.metric("Report Types", df["Type"].nunique())
                else:
                    st.warning("No reports match your filters.")
            else:
                st.warning("No landing reports found. Use the **Sync Data** tab to pull reports.")
        else:
            st.warning("No landing reports found. Use the **Sync Data** tab to pull reports.")
    else:
        st.warning("No data directory found. Use the **Sync Data** tab to pull reports.")

with tab2:
    st.header("Sync Landing Reports")

    if demo_mode:
        st.error("Cannot sync without valid credentials. Set ELANDINGS_USER and ELANDINGS_PASSWORD.")
    else:
        st.markdown("""
        Pull landing reports from eLandings. The sync will:
        1. Search for reports matching your filters
        2. Download full details for each report
        3. Save to local JSON files
        """)

        col1, col2 = st.columns(2)
        with col1:
            days_options = [7, 14, 30, 60, 90, 180, 365]
            days_back = st.selectbox(
                "Days to look back",
                options=days_options,
                index=2,  # Default to 30
                placeholder="Select or type days...",
            )
        with col2:
            full_refresh = st.checkbox("Full refresh (ignore last sync date)")

        if st.button("Start Sync", type="primary"):
            try:
                sync = LandingReportSync(output_dir="data/landing_reports")

                if full_refresh:
                    since = None
                else:
                    since_date = datetime.now() - timedelta(days=days_back)
                    since = since_date.strftime("%Y-%m-%d")

                # Progress bar and status
                progress_bar = st.progress(0)
                status_text = st.empty()

                def update_progress(current, total, report_id, action):
                    progress_bar.progress(current / total)
                    if action == "skipped":
                        status_text.text(f"[{current}/{total}] Skipped {report_id} (already exists)")
                    else:
                        status_text.text(f"[{current}/{total}] Fetching {report_id}...")

                status_text.text("Searching for reports...")
                result = sync.sync(
                    since=since,
                    full_refresh=full_refresh,
                    skip_existing=True,
                    progress_callback=update_progress,
                )

                progress_bar.progress(1.0)
                status_text.empty()

                # Clear index cache if new reports were synced
                if result.get('reports_synced', 0) > 0:
                    st.cache_data.clear()

                st.success(f"""
                **Sync Complete!**
                - Reports found: {result['reports_found']}
                - Reports synced: {result['reports_synced']}
                - Reports skipped: {result.get('reports_skipped', 0)}
                - Errors: {result['reports_failed']}
                """)

                if result['errors']:
                    with st.expander("View Errors"):
                        st.json(result['errors'])

            except Exception as e:
                st.error(f"Sync failed: {e}")

with tab3:
    st.header("Report Details")

    data_dir = Path("data/landing_reports")
    if data_dir.exists():
        json_files = list(data_dir.glob("landing_report_*.json"))

        if json_files:
            # Extract report IDs for dropdown
            report_ids = []
            for f in json_files:
                report_id = f.stem.replace("landing_report_", "")
                report_ids.append(report_id)

            # Combobox: type to filter/enter or select from dropdown
            selected_id = st.selectbox(
                "Select or enter Report ID",
                options=sorted(report_ids, reverse=True),
                index=None,
                placeholder="Type or select a report ID...",
            )

            if selected_id:
                report_file = data_dir / f"landing_report_{selected_id}.json"
                if report_file.exists():
                    with open(report_file, encoding="utf-8", errors="replace") as f:
                        report = json.load(f)

                    # Display key info
                    col1, col2, col3 = st.columns(3)

                    header = report.get("header", {})

                    with col1:
                        st.markdown("### Header")
                        vessel_obj = header.get('vessel', {})
                        vessel_name = extract_value(vessel_obj.get('@name')) if isinstance(vessel_obj, dict) else ""
                        vessel_num = vessel_obj.get('#text', '') if isinstance(vessel_obj, dict) else ""
                        st.write(f"**Vessel:** {vessel_name}")
                        st.write(f"**ADF&G Vessel #:** {vessel_num}")
                        st.write(f"**Port:** {extract_value(header.get('port_of_landing', {}).get('@name'))}")
                        st.write(f"**Landing Date:** {extract_value(header.get('date_of_landing'))}")
                        st.write(f"**Gear:** {extract_value(header.get('gear', {}).get('@name'))}")

                    with col2:
                        st.markdown("### Processor")
                        proc_code = header.get("proc_code_owner", {}).get("proc_code", {})
                        st.write(f"**Proc Code:** {extract_value(proc_code)}")
                        st.write(f"**Processor:** {extract_value(proc_code.get('@processor') if isinstance(proc_code, dict) else '')}")
                        st.write(f"**Fed Processor #:** {extract_value(header.get('federal_processor_number'))}")

                    with col3:
                        st.markdown("### Status")
                        st.write(f"**Status:** {extract_value(report.get('status', {}).get('@desc'))}")
                        st.write(f"**Type:** {extract_value(report.get('type_of_landing_report', {}).get('@name'))}")
                        st.write(f"**Last Modified:** {report.get('@last_change_date', '')[:19]}")

                    # Line items
                    st.markdown("### Catch (Line Items)")
                    line_items = report.get("line_item", [])
                    if isinstance(line_items, dict):
                        line_items = [line_items]

                    if line_items:
                        items_df = pd.DataFrame([
                            {
                                "Item #": item.get("item_number", ""),
                                "Fish Ticket": extract_value(item.get("fish_ticket_number")),
                                "Species": extract_value(item.get("species", {}).get("@name")),
                                "Condition": extract_value(item.get("condition_code", {}).get("@name")),
                                "Weight": extract_value(item.get("weight")),
                                "Disposition": extract_value(item.get("disposition_code", {}).get("@name")),
                            }
                            for item in line_items
                        ])
                        st.dataframe(items_df, use_container_width=True, hide_index=True)

                    # Raw JSON
                    with st.expander("View Raw JSON"):
                        st.json(report)
        else:
            st.info("No reports available. Sync data first.")
    else:
        st.info("No data directory. Sync data first.")

with tab4:
    st.header("Data Dictionary")

    st.markdown("""
    This table documents all fields available in eLandings landing reports.

    **Definition Sources:**
    - **Confirmed**: Field name is self-explanatory or matches official Alaska fisheries terminology
    - **Inferred**: Definition inferred from field name and sample data values
    - **Unknown**: Purpose unclear, needs verification with eLandings documentation

    *Note: These definitions are based on analysis of the XML schema and test data.
    Official definitions should be verified with ADF&G/eLandings documentation.*
    """)

    # Data dictionary as a dataframe
    data_dict = [
        # Report-level fields
        {"Section": "Report", "Field": "landing_report_id", "JSON Path": "landing_report_id", "Definition": "Unique identifier for the landing report", "Source": "Confirmed"},
        {"Section": "Report", "Field": "type_of_landing_report", "JSON Path": "type_of_landing_report.@name", "Definition": "Report type: Groundfish (G), Salmon (S), Shellfish (C), etc.", "Source": "Confirmed"},
        {"Section": "Report", "Field": "status", "JSON Path": "status.@desc", "Definition": "Report status: Draft, Initial Report Submitted, Final Report Submitted, etc.", "Source": "Confirmed"},
        {"Section": "Report", "Field": "data_entry_user", "JSON Path": "@data_entry_user", "Definition": "eLandings user ID who created the report", "Source": "Confirmed"},
        {"Section": "Report", "Field": "data_entry_submit_date", "JSON Path": "@data_entry_submit_date", "Definition": "Timestamp when report was first submitted", "Source": "Confirmed"},
        {"Section": "Report", "Field": "last_change_user", "JSON Path": "@last_change_user", "Definition": "eLandings user ID who last modified the report", "Source": "Confirmed"},
        {"Section": "Report", "Field": "last_change_date", "JSON Path": "@last_change_date", "Definition": "Timestamp of last modification", "Source": "Confirmed"},
        {"Section": "Report", "Field": "no_change_after_date", "JSON Path": "@no_change_after_date", "Definition": "Date after which report cannot be modified (locked)", "Source": "Inferred"},

        # Header fields
        {"Section": "Header", "Field": "vessel", "JSON Path": "header.vessel.@name", "Definition": "Vessel name; #text contains ADF&G vessel number", "Source": "Confirmed"},
        {"Section": "Header", "Field": "crew_size", "JSON Path": "header.crew_size", "Definition": "Number of crew members on the vessel", "Source": "Confirmed"},
        {"Section": "Header", "Field": "observers_onboard", "JSON Path": "header.observers_onboard", "Definition": "Number of fisheries observers aboard", "Source": "Confirmed"},
        {"Section": "Header", "Field": "port_of_landing", "JSON Path": "header.port_of_landing.@name", "Definition": "Port where fish was landed; @ifq_port_code is NMFS port code", "Source": "Confirmed"},
        {"Section": "Header", "Field": "gear", "JSON Path": "header.gear.@name", "Definition": "Fishing gear type (e.g., Longline, Trawl, Pot)", "Source": "Confirmed"},
        {"Section": "Header", "Field": "date_fishing_began", "JSON Path": "header.date_fishing_began", "Definition": "Date when fishing trip started", "Source": "Confirmed"},
        {"Section": "Header", "Field": "days_fished", "JSON Path": "header.days_fished", "Definition": "Number of days actively fishing", "Source": "Confirmed"},
        {"Section": "Header", "Field": "date_of_landing", "JSON Path": "header.date_of_landing", "Definition": "Date and time fish was delivered/landed", "Source": "Confirmed"},
        {"Section": "Header", "Field": "partial_delivery", "JSON Path": "header.partial_delivery", "Definition": "True if this is a partial delivery (more to come)", "Source": "Inferred"},
        {"Section": "Header", "Field": "last_delivery_for_trip", "JSON Path": "header.last_delivery_for_trip", "Definition": "True if this is the final delivery for the trip", "Source": "Inferred"},
        {"Section": "Header", "Field": "multiple_ifq_permits", "JSON Path": "header.multiple_ifq_permits", "Definition": "True if catch involves multiple IFQ permits", "Source": "Inferred"},

        # Processor fields
        {"Section": "Processor", "Field": "proc_code", "JSON Path": "header.proc_code_owner.proc_code", "Definition": "ADF&G processor code; @processor attribute has processor name", "Source": "Confirmed"},
        {"Section": "Processor", "Field": "federal_processor_number", "JSON Path": "header.federal_processor_number", "Definition": "NMFS federal processor permit number", "Source": "Confirmed"},
        {"Section": "Processor", "Field": "registered_buyer_number", "JSON Path": "header.registered_buyer_number", "Definition": "NMFS registered buyer permit number (for IFQ fish)", "Source": "Confirmed"},
        {"Section": "Processor", "Field": "buying_station_name", "JSON Path": "header.buying_station_name", "Definition": "Name of buying station if applicable", "Source": "Confirmed"},

        # Permit worksheet
        {"Section": "Permits", "Field": "cfec_permit", "JSON Path": "header.permit_worksheet.cfec_permit", "Definition": "CFEC (Commercial Fisheries Entry Commission) permit info", "Source": "Confirmed"},
        {"Section": "Permits", "Field": "cfec_permit.fishery", "JSON Path": "header.permit_worksheet.cfec_permit.fishery", "Definition": "CFEC fishery code (e.g., B06B = Prince William Sound halibut)", "Source": "Confirmed"},
        {"Section": "Permits", "Field": "cfec_permit.permit_number", "JSON Path": "header.permit_worksheet.cfec_permit.permit_number", "Definition": "CFEC permit number", "Source": "Confirmed"},
        {"Section": "Permits", "Field": "cfec_permit.@holder", "JSON Path": "header.permit_worksheet.cfec_permit.@holder", "Definition": "Name of CFEC permit holder", "Source": "Confirmed"},
        {"Section": "Permits", "Field": "fish_ticket_number", "JSON Path": "header.permit_worksheet.fish_ticket_number", "Definition": "State of Alaska fish ticket number (e.g., E17 203114)", "Source": "Confirmed"},
        {"Section": "Permits", "Field": "management_program", "JSON Path": "header.permit_worksheet.management_program.program", "Definition": "Management program: IFQ, CDQ, Open Access, etc.", "Source": "Confirmed"},
        {"Section": "Permits", "Field": "ifq_permit_number", "JSON Path": "header.permit_worksheet.ifq_permit_worksheet.ifq_permit_number", "Definition": "NMFS IFQ (Individual Fishing Quota) permit number", "Source": "Confirmed"},
        {"Section": "Permits", "Field": "nmfs_person_id", "JSON Path": "header.permit_worksheet.ifq_permit_worksheet.nmfs_person_id", "Definition": "NMFS person ID for IFQ holder", "Source": "Confirmed"},

        # Stat area
        {"Section": "Stat Area", "Field": "stat_area", "JSON Path": "header.stat_area_worksheet.stat_area", "Definition": "ADF&G statistical area code (6-digit)", "Source": "Confirmed"},
        {"Section": "Stat Area", "Field": "fed_area", "JSON Path": "header.stat_area_worksheet.stat_area.@fed_area", "Definition": "Federal reporting area code", "Source": "Confirmed"},
        {"Section": "Stat Area", "Field": "iphc_area", "JSON Path": "header.stat_area_worksheet.stat_area.@iphc_area", "Definition": "IPHC (International Pacific Halibut Commission) regulatory area", "Source": "Confirmed"},
        {"Section": "Stat Area", "Field": "coar_area", "JSON Path": "header.stat_area_worksheet.stat_area.@coar_area", "Definition": "COAR (Catch-in-Areas) reporting area", "Source": "Inferred"},
        {"Section": "Stat Area", "Field": "percent", "JSON Path": "header.stat_area_worksheet.percent", "Definition": "Percentage of catch from this stat area", "Source": "Confirmed"},

        # Line items (catch)
        {"Section": "Line Items", "Field": "item_number", "JSON Path": "line_item.item_number", "Definition": "Line item sequence number", "Source": "Confirmed"},
        {"Section": "Line Items", "Field": "species", "JSON Path": "line_item.species.@name", "Definition": "Species name; #text is ADF&G species code", "Source": "Confirmed"},
        {"Section": "Line Items", "Field": "condition_code", "JSON Path": "line_item.condition_code.@name", "Definition": "Fish condition: Whole (1), Gutted (4), H+G (5), etc.", "Source": "Confirmed"},
        {"Section": "Line Items", "Field": "weight", "JSON Path": "line_item.weight", "Definition": "Weight in pounds (may include ice/slime)", "Source": "Confirmed"},
        {"Section": "Line Items", "Field": "weight_modifier", "JSON Path": "line_item.weight_modifier.@description", "Definition": "Weight adjustment type: With Ice/Slime (I/S), etc.", "Source": "Confirmed"},
        {"Section": "Line Items", "Field": "disposition_code", "JSON Path": "line_item.disposition_code.@name", "Definition": "Disposition: Sold (60), Personal Use (43), Discarded, etc.", "Source": "Confirmed"},

        # IFQ Report
        {"Section": "IFQ Report", "Field": "net_ifq_weight", "JSON Path": "ifq_report.@net_ifq_weight", "Definition": "Net weight after ice/slime deduction for IFQ debit", "Source": "Confirmed"},
        {"Section": "IFQ Report", "Field": "tran_number", "JSON Path": "ifq_report.@tran_number", "Definition": "NMFS RAM transaction number for IFQ debit", "Source": "Confirmed"},
        {"Section": "IFQ Report", "Field": "tran_date_time", "JSON Path": "ifq_report.@tran_date_time", "Definition": "Timestamp of IFQ transaction", "Source": "Confirmed"},
        {"Section": "IFQ Report", "Field": "permit_holder", "JSON Path": "ifq_report.@permit_holder", "Definition": "Name of IFQ permit holder", "Source": "Confirmed"},
        {"Section": "IFQ Report", "Field": "card_holder", "JSON Path": "ifq_report.@card_holder", "Definition": "Name of IFQ card holder (may differ from permit holder)", "Source": "Inferred"},
        {"Section": "IFQ Report", "Field": "return_code", "JSON Path": "ifq_report.@return_code", "Definition": "NMFS RAM system return code", "Source": "Inferred"},
        {"Section": "IFQ Report", "Field": "return_msg", "JSON Path": "ifq_report.@return_msg", "Definition": "NMFS RAM system return message", "Source": "Inferred"},
        {"Section": "IFQ Report", "Field": "iphc_regulatory_area", "JSON Path": "ifq_report.ifq_item.iphc_regulatory_area", "Definition": "IPHC area for IFQ accounting (2C, 3A, 3B, 4A, etc.)", "Source": "Confirmed"},
        {"Section": "IFQ Report", "Field": "ifq_fishery", "JSON Path": "ifq_report.ifq_item.@ifq_fishery", "Definition": "IFQ fishery designation", "Source": "Confirmed"},
        {"Section": "IFQ Report", "Field": "ice_and_slime", "JSON Path": "ifq_report.ifq_item.ice_and_slime", "Definition": "True if ice/slime deduction was applied", "Source": "Confirmed"},
        {"Section": "IFQ Report", "Field": "sold_weight", "JSON Path": "ifq_report.ifq_item.sold_weight", "Definition": "Sold weight before ice/slime deduction", "Source": "Inferred"},
        {"Section": "IFQ Report", "Field": "price", "JSON Path": "ifq_report.ifq_item.price", "Definition": "Price per pound (often 0 in test data)", "Source": "Confirmed"},
    ]

    df_dict = pd.DataFrame(data_dict)

    # Filter by section
    sections = ["All"] + sorted(df_dict["Section"].unique().tolist())
    selected_section = st.selectbox("Filter by Section", sections)

    if selected_section != "All":
        df_dict = df_dict[df_dict["Section"] == selected_section]

    # Filter by source
    source_filter = st.multiselect(
        "Filter by Definition Source",
        options=["Confirmed", "Inferred", "Unknown"],
        default=["Confirmed", "Inferred", "Unknown"],
    )
    df_dict = df_dict[df_dict["Source"].isin(source_filter)]

    st.dataframe(
        df_dict,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Section": st.column_config.TextColumn("Section", width="small"),
            "Field": st.column_config.TextColumn("Field", width="medium"),
            "JSON Path": st.column_config.TextColumn("JSON Path", width="large"),
            "Definition": st.column_config.TextColumn("Definition", width="large"),
            "Source": st.column_config.TextColumn("Source", width="small"),
        },
    )

    st.markdown(f"**Total fields:** {len(df_dict)}")

    st.divider()

    st.subheader("Common Code Values")

    st.markdown("#### Report Types")
    st.code("""
G = Groundfish
S = Salmon
C = Shellfish (Crab)
H = Herring
    """)

    st.markdown("#### Condition Codes")
    st.code("""
1 = Whole
3 = Bled
4 = Gutted
5 = H+G (Head and Gutted)
8 = Eastern Cut
21 = Fillets with Skin
    """)

    st.markdown("#### Disposition Codes")
    st.code("""
60 = Sold
43 = Personal Use
61 = Discarded at Sea
    """)

    st.markdown("#### IPHC Regulatory Areas")
    st.code("""
2C = Southeast Alaska
3A = Central Gulf of Alaska
3B = Western Gulf of Alaska
4A = Eastern Bering Sea
4B = Northern Bering Sea
4C/4D/4E = Aleutian Islands
    """)

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: #666;'>
    eLandings Sync Prototype | Fishermen First
</div>
""", unsafe_allow_html=True)

