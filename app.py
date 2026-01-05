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
    page_icon="=",
    layout="wide",
)

st.title("= eLandings Sync Prototype")
st.markdown("""
This prototype demonstrates **automated landing report sync** from the eLandings API.
Instead of manually entering data from fish tickets, reports are pulled directly via the API.
""")


def get_credentials():
    """Get eLandings credentials from Streamlit secrets or environment."""
    # Try Streamlit secrets first (for cloud deployment)
    if hasattr(st, "secrets") and "ELANDINGS_USER" in st.secrets:
        return {
            "user": st.secrets["ELANDINGS_USER"],
            "password": st.secrets["ELANDINGS_PASSWORD"],
            "schema_version": st.secrets.get("ELANDINGS_SCHEMA_VERSION", "1.0"),
        }
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

    return {
        "Report ID": extract_value(report.get("landing_report_id")),
        "Status": extract_value(report.get("status", {}).get("@desc", "")),
        "Type": extract_value(report.get("type_of_landing_report", {}).get("@name", "")),
        "Vessel": extract_value(header.get("vessel", {}).get("@name", "")),
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

    **Benefits:**
    - Automated data sync
    - Scoped access (processors see only their data)
    - Complete report data including IFQ info
    - Date-based incremental sync
    """)

# Main content
tab1, tab2, tab3 = st.tabs(["=Ê Landing Reports", "= Sync Data", "=Ë Report Details"])

with tab1:
    st.header("Landing Reports")

    # Check for local data
    data_dir = Path("data/landing_reports")

    if data_dir.exists():
        json_files = list(data_dir.glob("landing_report_*.json"))

        if json_files:
            st.info(f"Found **{len(json_files)}** landing reports in local storage")

            # Load and display reports
            reports = []
            for f in json_files[:100]:  # Limit for performance
                try:
                    with open(f) as fp:
                        report = json.load(fp)
                        reports.append(landing_report_to_row(report))
                except Exception:
                    pass

            if reports:
                df = pd.DataFrame(reports)

                # Filters
                col1, col2 = st.columns(2)
                with col1:
                    vessel_filter = st.multiselect(
                        "Filter by Vessel",
                        options=sorted(df["Vessel"].unique()),
                    )
                with col2:
                    species_filter = st.text_input("Filter by Species (contains)")

                # Apply filters
                filtered_df = df.copy()
                if vessel_filter:
                    filtered_df = filtered_df[filtered_df["Vessel"].isin(vessel_filter)]
                if species_filter:
                    filtered_df = filtered_df[
                        filtered_df["Species"].str.contains(species_filter, case=False, na=False)
                    ]

                st.dataframe(
                    filtered_df,
                    use_container_width=True,
                    hide_index=True,
                )

                # Summary stats
                st.subheader("Summary")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Reports", len(filtered_df))
                col2.metric("Unique Vessels", filtered_df["Vessel"].nunique())
                col3.metric("Unique Ports", filtered_df["Port"].nunique())
                col4.metric("Report Types", filtered_df["Type"].nunique())
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
            days_back = st.number_input(
                "Days to look back",
                min_value=1,
                max_value=365,
                value=30,
            )
        with col2:
            full_refresh = st.checkbox("Full refresh (ignore last sync date)")

        if st.button("= Start Sync", type="primary"):
            with st.spinner("Syncing landing reports..."):
                try:
                    sync = LandingReportSync(output_dir="data/landing_reports")

                    if full_refresh:
                        since = None
                    else:
                        since_date = datetime.now() - timedelta(days=days_back)
                        since = since_date.strftime("%Y-%m-%d")

                    result = sync.sync(since=since, full_refresh=full_refresh)

                    st.success(f"""
                    **Sync Complete!**
                    - Reports found: {result['reports_found']}
                    - Reports synced: {result['reports_synced']}
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

            selected_id = st.selectbox(
                "Select Report ID",
                options=sorted(report_ids, reverse=True),
            )

            if selected_id:
                report_file = data_dir / f"landing_report_{selected_id}.json"
                if report_file.exists():
                    with open(report_file) as f:
                        report = json.load(f)

                    # Display key info
                    col1, col2, col3 = st.columns(3)

                    header = report.get("header", {})

                    with col1:
                        st.markdown("### Header")
                        st.write(f"**Vessel:** {extract_value(header.get('vessel', {}).get('@name'))}")
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

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: #666;'>
    eLandings Sync Prototype | Fishermen First
</div>
""", unsafe_allow_html=True)
