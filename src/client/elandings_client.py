"""
eLandings SOAP Client

A simple client for the eLandings ReportManagementService SOAP API.
"""

import os
import html
import requests
import xml.etree.ElementTree as ET
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

# Configuration
ENDPOINT = "https://elandingst.alaska.gov/elandings/ReportManagementService"
TARGET_NS = "http://webservices.er.psmfc.org/"
USER = os.getenv("ELANDINGS_USER")
PWD = os.getenv("ELANDINGS_PASSWORD")
SCHEMA_VERSION = os.getenv("ELANDINGS_SCHEMA_VERSION", "1.0")


class ELandingsClient:
    """Client for eLandings SOAP web services."""

    def __init__(
        self,
        endpoint: str = ENDPOINT,
        user: str = USER,
        password: str = PWD,
        schema_version: str = SCHEMA_VERSION,
    ):
        self.endpoint = endpoint
        self.user = user
        self.password = password
        self.schema_version = schema_version
        self.target_ns = TARGET_NS

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/xml,text/xml,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        })

    def _build_envelope(self, operation: str, args: list[str]) -> str:
        """Build a SOAP 1.1 envelope for the given operation."""
        args_xml = "\n      ".join(
            f"<arg{i}>{self._escape(arg)}</arg{i}>" for i, arg in enumerate(args)
        )
        return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:tns="{self.target_ns}">
  <soapenv:Header/>
  <soapenv:Body>
    <tns:{operation}>
      {args_xml}
    </tns:{operation}>
  </soapenv:Body>
</soapenv:Envelope>"""

    def _escape(self, value: str) -> str:
        """Escape XML special characters."""
        if value is None:
            return ""
        return html.escape(str(value))

    def _call(self, operation: str, args: list[str]) -> str:
        """Make a SOAP call and return the raw response body."""
        envelope = self._build_envelope(operation, args)
        resp = self.session.post(self.endpoint, data=envelope.encode("utf-8"), timeout=60)
        resp.raise_for_status()
        return resp.text

    def _parse_response(self, xml_text: str, response_element: str) -> Optional[str]:
        """Parse SOAP response and extract the return value (often HTML-escaped XML)."""
        root = ET.fromstring(xml_text)

        # Find the response element (e.g., getUserInfoResponse)
        for elem in root.iter():
            if elem.tag.endswith(response_element):
                # Find the <return> element inside
                for child in elem:
                    if child.tag == "return" or child.tag.endswith("}return"):
                        # The return value is often HTML-escaped XML
                        return html.unescape(child.text or "")
        return None

    def _call_and_parse(self, operation: str, args: list[str]) -> Optional[str]:
        """Call operation and parse the response."""
        raw = self._call(operation, args)
        return self._parse_response(raw, f"{operation}Response")

    # ==================== API Methods ====================

    def get_user_info(self) -> Optional[str]:
        """Get user profile and authorized operations."""
        return self._call_and_parse("getUserInfo", [
            self.user,
            self.password,
            self.schema_version,
        ])

    def get_operations(self) -> Optional[str]:
        """Get list of operations for the user."""
        return self._call_and_parse("getOperations", [
            self.user,
            self.password,
            self.schema_version,
        ])

    def find_user_landing_reports(
        self,
        operation_id: str = "",
        report_type: str = "",
        report_status: str = "",
        adfg_number: str = "",
        cfec_file: str = "",
        uscg_doc: str = "",
        state_reg: str = "",
        cfec_permit: str = "",
        ifq_permit: str = "",
        ifq_batch_confirmation: str = "",
        tender_vessel: str = "",
        processor_number: str = "",
        federal_processor: str = "",
        registered_buyer: str = "",
        landing_report_number: str = "",
        landing_report_short_id: str = "",
        fish_ticket: str = "",
        date_landed_start: str = "",  # Format: YYYY-MM-DDTHH:MM:SS (ISO)
        date_landed_end: str = "",
        date_created_start: str = "",
        date_created_end: str = "",
        date_modified_start: str = "",
        date_modified_end: str = "",
    ) -> Optional[str]:
        """
        Search for landing reports.

        Uses findUserLandingReports_001 which supports date range filtering.
        Date parameters should be ISO format: YYYY-MM-DDTHH:MM:SS
        """
        return self._call_and_parse("findUserLandingReports_001", [
            self.user,              # arg0
            self.password,          # arg1
            self.schema_version,    # arg2
            operation_id,           # arg3
            report_type,            # arg4
            report_status,          # arg5
            adfg_number,            # arg6
            cfec_file,              # arg7
            uscg_doc,               # arg8
            state_reg,              # arg9
            cfec_permit,            # arg10
            ifq_permit,             # arg11
            ifq_batch_confirmation, # arg12
            tender_vessel,          # arg13
            processor_number,       # arg14
            federal_processor,      # arg15
            registered_buyer,       # arg16
            landing_report_number,  # arg17
            landing_report_short_id,# arg18
            fish_ticket,            # arg19
            date_landed_start,      # arg20
            date_landed_end,        # arg21
            date_created_start,     # arg22
            date_created_end,       # arg23
            date_modified_start,    # arg24
            date_modified_end,      # arg25
        ])

    def get_landing_report(
        self,
        landing_report_number: str,
    ) -> Optional[str]:
        """Get a specific landing report by its number."""
        return self._call_and_parse("getLandingReport", [
            self.user,
            self.password,
            self.schema_version,
            landing_report_number,
            "",  # arg4 - possibly version or format
        ])

    def find_user_production_reports(
        self,
        operation_id: str = "",
        week_ending_date: str = "",
        report_number: str = "",
        report_status: str = "",
        date_created_start: str = "",
        date_created_end: str = "",
        date_modified_start: str = "",
        date_modified_end: str = "",
    ) -> Optional[str]:
        """Search for production reports."""
        return self._call_and_parse("findUserProductionReports_001", [
            self.user,              # arg0
            self.password,          # arg1
            self.schema_version,    # arg2
            operation_id,           # arg3
            week_ending_date,       # arg4
            report_number,          # arg5
            report_status,          # arg6
            "",                     # arg7-11 unknown filters
            "",
            "",
            "",
            "",
            date_created_start,     # arg12
            date_created_end,       # arg13
            date_modified_start,    # arg14
            date_modified_end,      # arg15
        ])

    def get_production_report(
        self,
        production_report_number: str,
    ) -> Optional[str]:
        """Get a specific production report by its number."""
        return self._call_and_parse("getProductionReport", [
            self.user,
            self.password,
            self.schema_version,
            production_report_number,
            "",  # arg4
        ])


def pretty_print_xml(xml_string: str) -> str:
    """Pretty print XML string."""
    try:
        root = ET.fromstring(xml_string)
        ET.indent(root)
        return ET.tostring(root, encoding="unicode")
    except ET.ParseError:
        return xml_string


if __name__ == "__main__":
    client = ELandingsClient()

    print("=" * 60)
    print("Fetching Full Landing Report")
    print("=" * 60)

    # Get a full landing report - using report ID 304327 from the test data
    print("\n--- getLandingReport (304327) ---")
    landing_report = client.get_landing_report("304327")
    if landing_report:
        formatted = pretty_print_xml(landing_report)
        print(formatted)

        # Save to file for analysis
        with open("landing_report_304327.xml", "w", encoding="utf-8") as f:
            f.write(formatted)
        print("\n[Saved to landing_report_304327.xml]")
    else:
        print("No report returned")
