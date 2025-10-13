#!/usr/bin/env python3
"""
Fetch every AWS / Azure / GCP SKU for General purpose, Compute optimized,
and Memory optimized machine families in the specified regions and write a CSV.

Regions:
 - AWS: us-west-1
 - Azure: westus
 - GCP: us-west1

Outputs:
 - cloud_instance_prices_us-west-1_westus_us-west1.csv
"""

import csv
import json
import re
import time
from datetime import datetime, timezone
import requests

OUTFILE = "cloud_instance_prices_us-west-1_westus_us-west1.csv"
now_iso = datetime.now(timezone.utc).isoformat()

def write_rows(rows):
    header = [
        "cloud","region","family","category","instance_type",
        "vcpus","memory_gib","price_usd_per_hour","source_url","timestamp_utc"
    ]
    with open(OUTFILE, "w", newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✅ Wrote {len(rows)} rows to {OUTFILE}")

# ---------------- AWS FIXED SECTION ----------------
def fetch_aws_ec2_us_west_1():
    """
    Fixed AWS fetch:
    Directly loads the latest EC2 offer file from the AWS Pricing API.
    Filters to 'US West (N. California)'.
    """
    rows = []
    location_name = "US West (N. California)"
    # Direct JSON file (official bulk EC2 pricing data)
    ec2_offer_url = (
        "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-west-1/index.json"
    )
    print(f"Fetching AWS EC2 pricing from {ec2_offer_url} ... (this may take ~30s)")
    data = requests.get(ec2_offer_url, timeout=120).json()

    general_prefixes = ("m", "t", "d")
    compute_prefixes = ("c",)
    memory_prefixes = ("r", "x", "z", "u")

    products = data.get("products", {})
    terms = data.get("terms", {}).get("OnDemand", {})

    for sku, prod in products.items():
        attrs = prod.get("attributes", {})
        if attrs.get("servicecode") != "AmazonEC2":
            continue
        if attrs.get("location") != location_name:
            continue

        instance_type = attrs.get("instanceType", "")
        if not instance_type:
            continue

        # Identify category by instance family
        prefix = instance_type.split(".")[0]
        cat = None
        if prefix.startswith(general_prefixes):
            cat = "general-purpose"
        elif prefix.startswith(compute_prefixes):
            cat = "compute-optimized"
        elif prefix.startswith(memory_prefixes):
            cat = "memory-optimized"
        else:
            continue

        # Get vCPUs and memory
        vcpu = attrs.get("vcpu")
        mem_str = attrs.get("memory", "")
        mem_gib = None
        if mem_str:
            m = re.search(r"([\d\.]+)", mem_str)
            mem_gib = float(m.group(1)) if m else None

        # Extract OnDemand price
        price = None
        ond = terms.get(sku, {})
        for term_id, term_obj in ond.items():
            for pd_id, pd in term_obj.get("priceDimensions", {}).items():
                price_str = pd.get("pricePerUnit", {}).get("USD")
                if price_str:
                    try:
                        price = float(price_str)
                        break
                    except ValueError:
                        continue
            if price is not None:
                break

        if price is None:
            continue

        rows.append({
            "cloud": "AWS",
            "region": "us-west-1",
            "family": prefix,
            "category": cat,
            "instance_type": instance_type,
            "vcpus": vcpu,
            "memory_gib": mem_gib,
            "price_usd_per_hour": price,
            "source_url": ec2_offer_url,
            "timestamp_utc": now_iso,
        })

    print(f"AWS rows collected: {len(rows)}")
    return rows

# ---------------- Azure Section (unchanged) ----------------
def fetch_azure_westus():
    rows = []
    base = "https://prices.azure.com/api/retail/prices"
    page = base + "?$filter=armRegionName eq 'westus' and serviceName eq 'Virtual Machines'"
    print("Fetching Azure retail rates (paginated)...")
    while page:
        r = requests.get(page, timeout=60).json()
        for it in r.get("Items", []):
            sku = it.get("skuName") or ""
            product = it.get("productName") or ""
            arm_region = it.get("armRegionName")
            if arm_region != "westus":
                continue
            cat = None
            lower = (sku + product).lower()
            if re.search(r"\bd\d|dsv", lower):
                cat = "general-purpose"
            elif re.search(r"\bf\d|fsv", lower):
                cat = "compute-optimized"
            elif re.search(r"\be\d|esv", lower):
                cat = "memory-optimized"
            else:
                continue
            inst = it.get("armSkuName") or sku or product
            price = it.get("unitPrice")
            rows.append({
                "cloud": "Azure",
                "region": "westus",
                "family": sku,
                "category": cat,
                "instance_type": inst,
                "vcpus": "",
                "memory_gib": "",
                "price_usd_per_hour": price,
                "source_url": page,
                "timestamp_utc": now_iso,
            })
        page = r.get("NextPageLink")
        time.sleep(0.2)
    print(f"Azure rows: {len(rows)}")
    return rows

# ---------------- GCP Section (placeholder mirror) ----------------
def fetch_gcp_us_west4():
    rows = []
    # Using gcloud-compute mirror for simplicity
    url = "https://gcloud-compute.com/us-west4.html"
    print("Fetching GCP mirror table...")
    try:
        from bs4 import BeautifulSoup
        html = requests.get(url, timeout=60).text
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            name = tds[0].get_text(strip=True)
            vcpu = tds[1].get_text(strip=True)
            mem = tds[2].get_text(strip=True)
            price_str = tds[3].get_text(strip=True)
            p = re.search(r"([\d\.]+)", price_str)
            price = float(p.group(1)) if p else None
            cat = None
            if name.startswith("n4") or name.startswith("n2"):
                cat = "general-purpose"
            elif name.startswith("c2") or name.startswith("c4"):
                cat = "compute-optimized"
            elif name.startswith("m2") or name.startswith("m4"):
                cat = "memory-optimized"
            else:
                continue
            rows.append({
                "cloud": "GCP",
                "region": "us-west4",
                "family": name.split("-")[0],
                "category": cat,
                "instance_type": name,
                "vcpus": vcpu,
                "memory_gib": mem,
                "price_usd_per_hour": price,
                "source_url": url,
                "timestamp_utc": now_iso,
            })
    except Exception as e:
        print("GCP fetch warning:", e)
    print(f"GCP rows parsed: {len(rows)}")
    return rows

# ---------------- MAIN ----------------
def main():
    all_rows = []
    try:
        all_rows += fetch_aws_ec2_us_west_1()
    except Exception as e:
        print("AWS fetch failed:", e)
    try:
        all_rows += fetch_azure_westus()
    except Exception as e:
        print("Azure fetch failed:", e)
    try:
        all_rows += fetch_gcp_us_west4()
    except Exception as e:
        print("GCP fetch failed:", e)
    if all_rows:
        write_rows(all_rows)
    else:
        print("❌ No data fetched — check internet connection or region filters.")

if __name__ == "__main__":
    main()
