import os
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv

# ============================
# Config
# ============================
load_dotenv(override=True)

WSDL_URL = os.getenv("ELANDINGS_WSDL")  # e.g. http://elandingst.alaska.gov/elandings/ReportManagementService?wsdl
USER = os.getenv("ELANDINGS_USER")
PWD = os.getenv("ELANDINGS_PASSWORD")
SCHEMA_VERSION = os.getenv("ELANDINGS_SCHEMA_VERSION", "1.0")

if not WSDL_URL:
    raise ValueError("Missing ELANDINGS_WSDL in .env")
if not USER or not PWD:
    raise ValueError("Missing ELANDINGS_USER or ELANDINGS_PASSWORD in .env")

PUBLIC_HOST = "elandingst.alaska.gov"

print("SCRIPT STARTED")
print("Using WSDL:", WSDL_URL)

# ============================
# Session (browser-like)
# ============================
session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/xml,text/xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
)

# ============================
# 1) Fetch WSDL
# ============================
wsdl_resp = session.get(WSDL_URL, timeout=30, allow_redirects=True)
print("WSDL HTTP status:", wsdl_resp.status_code)
wsdl_resp.raise_for_status()

wsdl_text = wsdl_resp.text
with open("wsdl_debug.xml", "w", encoding="utf-8") as f:
    f.write(wsdl_text)

print("WSDL length:", len(wsdl_text))
print("WSDL first 120 chars:", wsdl_text[:120].replace("\n", "\\n"))

# ============================
# 2) Parse WSDL + extract info
# ============================
try:
    root = ET.fromstring(wsdl_text)
except Exception as e:
    raise RuntimeError(f"WSDL XML parse failed: {repr(e)} (saved wsdl_debug.xml)")

target_ns = root.attrib.get("targetNamespace")
if not target_ns:
    raise RuntimeError("Could not find targetNamespace on WSDL root")
print("targetNamespace:", target_ns)

soap_addresses = []
for el in root.iter():
    if el.tag.endswith("address") and "location" in el.attrib:
        soap_addresses.append(el.attrib["location"])

print("\nsoap:address locations found:")
for loc in soap_addresses:
    print(" -", loc)

# ============================
# 3) Build candidate endpoints
#    IMPORTANT: eLandings is mounted under /elandings/ publicly.
#    We'll try those first.
# ============================
candidates = []

base_http = f"http://{PUBLIC_HOST}"
base_https = f"https://{PUBLIC_HOST}"

# Most likely correct public SOAP endpoints
preferred_paths = [
    "/elandings/ReportManagementService",
    "/elandings/ReportManagementService/",
    "/elandings/ReportManagementV1Service",
    "/elandings/ReportManagementV1Service/",
]

for p in preferred_paths:
    candidates.append(base_http + p)
    candidates.append(base_https + p)

# Also try "swap host" versions of any WSDL soap:address, but keep their paths
def swap_host_keep_path(url: str, host: str, scheme: str) -> str:
    p = urlparse(url)
    return urlunparse(p._replace(scheme=scheme, netloc=host))

for loc in soap_addresses:
    candidates.append(swap_host_keep_path(loc, PUBLIC_HOST, "http"))
    candidates.append(swap_host_keep_path(loc, PUBLIC_HOST, "https"))

# Finally, less-likely root-mounted paths (put last)
fallback_paths = [
    "/ReportManagementService",
    "/ReportManagementService/",
]
for p in fallback_paths:
    candidates.append(base_http + p)
    candidates.append(base_https + p)

# de-dupe, preserve order
seen = set()
candidates = [u for u in candidates if not (u in seen or seen.add(u))]

print("\n=== Candidate SOAP endpoints to test ===")
for u in candidates:
    print(" -", u)

# ============================
# 4) SOAP envelopes (1.1 and 1.2)
# ============================
# Note: The XSD schema uses arg0, arg1, arg2 (not userId, password, schemaVersion)
soap11_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:tns="{target_ns}">
  <soapenv:Header/>
  <soapenv:Body>
    <tns:getUserInfo>
      <arg0>{USER}</arg0>
      <arg1>{PWD}</arg1>
      <arg2>{SCHEMA_VERSION}</arg2>
    </tns:getUserInfo>
  </soapenv:Body>
</soapenv:Envelope>
"""

soap12_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://www.w3.org/2003/05/soap-envelope"
                  xmlns:tns="{target_ns}">
  <soapenv:Header/>
  <soapenv:Body>
    <tns:getUserInfo>
      <arg0>{USER}</arg0>
      <arg1>{PWD}</arg1>
      <arg2>{SCHEMA_VERSION}</arg2>
    </tns:getUserInfo>
  </soapenv:Body>
</soapenv:Envelope>
"""

# Common SOAPAction variations
soap_actions = [
    "",  # some services want empty
    "getUserInfo",
    '"getUserInfo"',  # quoted
    f"{target_ns}getUserInfo",
    f"{target_ns}/getUserInfo",
]

def looks_like_html(text: str) -> bool:
    t = (text or "").lower()
    return ("<html" in t) or ("no xml-ws context" in t) or ("temporarily unavailable" in t)

def save_response(filename: str, content: str):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content or "")

def try_endpoint(url: str) -> bool:
    print("\n========================================")
    print("TESTING ENDPOINT:", url)
    print("========================================")

    # SOAP 1.1 attempts
    for action in soap_actions:
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": action,
        }

        print("\n--- SOAP 1.1 ATTEMPT ---")
        print("SOAPAction:", repr(action))

        try:
            resp = session.post(url, data=soap11_envelope.encode("utf-8"), headers=headers, timeout=60)
        except Exception as e:
            print("Request error:", repr(e))
            continue

        ct = resp.headers.get("Content-Type", "")
        print("HTTP:", resp.status_code, "| Content-Type:", ct)
        preview = (resp.text or "")[:400].replace("\n", "\\n")
        print("Preview:", preview)

        save_response("soap_response_debug.xml", resp.text or "")

        if resp.status_code in (200, 500) and not looks_like_html(resp.text or ""):
            print("\n✅ Non-HTML response (SOAP or SOAP Fault) — stopping.")
            return True

    # SOAP 1.2 attempt
    print("\n--- SOAP 1.2 ATTEMPT ---")
    headers12 = {
        "Content-Type": 'application/soap+xml; charset=utf-8; action="getUserInfo"',
    }

    try:
        resp12 = session.post(url, data=soap12_envelope.encode("utf-8"), headers=headers12, timeout=60)
    except Exception as e:
        print("Request error:", repr(e))
        return False

    ct12 = resp12.headers.get("Content-Type", "")
    print("HTTP:", resp12.status_code, "| Content-Type:", ct12)
    preview12 = (resp12.text or "")[:400].replace("\n", "\\n")
    print("Preview:", preview12)

    save_response("soap_response_debug.xml", resp12.text or "")

    if resp12.status_code in (200, 500) and not looks_like_html(resp12.text or ""):
        print("\n✅ Non-HTML response (SOAP or SOAP Fault) — stopping.")
        return True

    return False

print("\nStarting endpoint tests...")
for url in candidates:
    if try_endpoint(url):
        print("\n🎯 SUCCESS endpoint:", url)
        print("Saved last response to soap_response_debug.xml")
        break
else:
    print("\n❌ No endpoint returned a recognizable SOAP response.")
    print("Last response saved to soap_response_debug.xml")
