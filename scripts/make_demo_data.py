"""
Generate price files for three FICTIONAL Massachusetts hospitals -- one in each
CMS layout (tall CSV, wide CSV, JSON) -- so the whole pipeline can be run and
the dashboard previewed before any real files are downloaded.

The payer names are deliberately messy in the way real files are
("BCBS MA", "Blue Cross Blue Shield of Massachusetts", "BLUE CROSS - HMO BLUE")
so the payer-normalization model has something real to do.

All hospitals, prices and NPIs here are made up.

Usage:  python scripts/make_demo_data.py   ->  data/demo/files/*.csv|json
"""
import csv
import json
import random
from pathlib import Path

random.seed(7)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "demo" / "files"
OUT.mkdir(parents=True, exist_ok=True)

SERVICES = list(csv.DictReader(open(ROOT / "transform" / "seeds" / "shoppable_services.csv")))
# rough price anchors (not real rates), used only to make the fake numbers plausible
ANCHOR = {"Imaging": 450, "Cardiology": 40, "GI procedures": 1400, "Surgery": 4500, "Lab": 25,
          "Office visits": 150, "Therapy": 60, "Inpatient": 22000}
ATTESTATION = ("To the best of its knowledge and belief, this hospital has included all applicable standard "
               "charge information in accordance with the requirements of 45 CFR 180.50, and the information "
               "encoded is true, accurate, and complete as of the date in the file.")

HOSPITALS = [
    {
        "id": "demo_harborview", "fmt": "tall",
        "name": "Harborview General Hospital (FICTIONAL DEMO)", "markup": 1.35,
        "payers": [("Blue Cross Blue Shield of Massachusetts", "PPO", 1.00), ("Blue Cross Blue Shield of Massachusetts", "HMO Blue", 0.93),
                   ("Harvard Pilgrim Health Care", "HMO", 0.97), ("Tufts Health Plan", "Commercial", 0.95),
                   ("Aetna", "Open Access", 1.08), ("UnitedHealthcare", "Choice Plus", 1.12),
                   ("MassHealth", "ACO", 0.55), ("BCBS Medicare Advantage", "Medicare HMO Blue", 0.62)],
    },
    {
        "id": "demo_backbay", "fmt": "wide",
        "name": "Back Bay Medical Center (FICTIONAL DEMO)", "markup": 1.10,
        "payers": [("BCBS MA", "PPO", 1.00), ("BCBS MA", "HMO", 0.90), ("HPHC", "All Plans", 0.99),
                   ("Point32Health - Tufts", "HMO", 0.94), ("Cigna", "Open Access Plus", 1.15),
                   ("UHC", "Commercial", 1.05), ("WellSense", "MassHealth ACO", 0.52)],
    },
    {
        "id": "demo_charlesriver", "fmt": "json",
        "name": "Charles River Community Hospital (FICTIONAL DEMO)", "markup": 0.85,
        "payers": [("BLUE CROSS - HMO BLUE", "HMO Blue", 1.00), ("Blue Cross Blue Shield", "PPO", 1.04),
                   ("Harvard Pilgrim", "Commercial", 0.96), ("Tufts Health Plan", "HMO", 0.92),
                   ("Aetna", "PPO", 1.02), ("Fallon Health", "Community Care", 0.88),
                   ("Mass General Brigham Health Plan", "Commercial", 0.98), ("Tufts Medicare Preferred", "HMO", 0.60)],
    },
]


def rows_for(h):
    """One dict per service x payer with gross, cash and negotiated values."""
    out = []
    for s in SERVICES:
        if random.random() < 0.1:  # every hospital is missing a few services
            continue
        base = ANCHOR[s["category"]] * random.uniform(0.6, 1.8) * h["markup"]
        gross = round(base * random.uniform(2.5, 4.0), 2)
        setting = "inpatient" if s["code_type"] == "MS-DRG" else random.choice(["outpatient", "outpatient", "both"])
        payers = []
        for payer, plan, mult in h["payers"]:
            if random.random() < 0.05:
                continue
            negotiated = round(base * mult * random.uniform(0.85, 1.15), 2)
            p = {"payer": payer, "plan": plan, "dollar": negotiated, "pct": None, "algo": None,
                 "method": "case rate" if setting == "inpatient" else "fee schedule"}
            if random.random() < 0.04:  # some rates are only a % of charges
                p.update(dollar=None, pct=round(random.uniform(40, 70), 1),
                         algo=None, method="percent of total billed charges")
            # 2026 fields: actual allowed amounts
            if p["dollar"] and random.random() < 0.7:
                p.update(median=round(p["dollar"] * random.uniform(0.9, 1.0), 2),
                         p10=round(p["dollar"] * random.uniform(0.6, 0.8), 2),
                         p90=round(p["dollar"] * random.uniform(1.0, 1.2), 2),
                         count=str(random.randint(11, 400)))
            payers.append(p)
        rev = "0610" if s["category"] == "Imaging" else "0360" if s["category"] == "Surgery" else ""
        out.append({"s": s, "gross": gross, "cash": round(gross * 0.6, 2), "setting": setting,
                    "rev": rev, "payers": payers})
    return out


def meta_rows(h):
    keys = ["hospital_name", "last_updated_on", "version", "location_name", "hospital_address",
            "license_number|MA", "type_2_npi", ATTESTATION, "attester_name"]
    vals = [h["name"], "2026-07-01", "3.0.0", h["name"], "1 Example Way, Boston, MA 02115",
            str(random.randint(1000, 9999)), str(random.randint(10**9, 2 * 10**9 - 1)), "TRUE", "Demo Attester"]
    return keys, vals


def codes(r):
    c = [(r["s"]["billing_code"], r["s"]["code_type"])]
    if r["rev"]:
        c.append((r["rev"], "RC"))
    return c


def write_tall(h, rows):
    cols = ["description", "code|1", "code|1|type", "code|2", "code|2|type", "setting",
            "drug_unit_of_measurement", "drug_type_of_measurement", "standard_charge|gross",
            "standard_charge|discounted_cash", "payer_name", "plan_name", "modifiers",
            "standard_charge|negotiated_dollar", "standard_charge|negotiated_percentage",
            "standard_charge|negotiated_algorithm", "median_amount", "10th_percentile", "90th_percentile",
            "count", "standard_charge|min", "standard_charge|max", "standard_charge|methodology",
            "additional_generic_notes"]
    with open(OUT / f"{h['id']}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerows(meta_rows(h))
        w.writerow(cols)
        for r in rows:
            c = codes(r) + [("", "")]
            dollars = [p["dollar"] for p in r["payers"] if p["dollar"]]
            for p in r["payers"]:
                w.writerow([r["s"]["service_name"], c[0][0], c[0][1], c[1][0], c[1][1], r["setting"], "", "",
                            r["gross"], r["cash"], p["payer"], p["plan"], "", p["dollar"] or "", p["pct"] or "",
                            p["algo"] or "", p.get("median", ""), p.get("p10", ""), p.get("p90", ""),
                            p.get("count", ""), min(dollars, default=""), max(dollars, default=""), p["method"], ""])


def write_wide(h, rows):
    base_cols = ["description", "code|1", "code|1|type", "code|2", "code|2|type", "modifiers", "setting",
                 "drug_unit_of_measurement", "drug_type_of_measurement", "standard_charge|gross",
                 "standard_charge|discounted_cash"]
    payer_cols = []
    for payer, plan, _ in h["payers"]:
        payer_cols += [f"standard_charge|{payer}|{plan}|negotiated_dollar",
                       f"standard_charge|{payer}|{plan}|negotiated_percentage",
                       f"standard_charge|{payer}|{plan}|negotiated_algorithm",
                       f"median_amount|{payer}|{plan}", f"10th_percentile|{payer}|{plan}",
                       f"90th_percentile|{payer}|{plan}", f"count|{payer}|{plan}",
                       f"standard_charge|{payer}|{plan}|methodology", f"additional_payer_notes|{payer}|{plan}"]
    cols = base_cols + payer_cols + ["standard_charge|min", "standard_charge|max", "additional_generic_notes"]
    # wide files from Excel are often Windows-1252 -- write it that way to exercise the transcoder
    with open(OUT / f"{h['id']}.csv", "w", newline="", encoding="cp1252") as f:
        w = csv.writer(f)
        w.writerows(meta_rows(h))
        w.writerow(cols)
        for r in rows:
            c = codes(r) + [("", "")]
            by = {(p["payer"], p["plan"]): p for p in r["payers"]}
            vals = [r["s"]["service_name"].replace(" - ", " – "), c[0][0], c[0][1], c[1][0], c[1][1], "",
                    r["setting"], "", "", r["gross"], r["cash"]]
            for payer, plan, _ in h["payers"]:
                p = by.get((payer, plan))
                vals += ([p["dollar"] or "", p["pct"] or "", p["algo"] or "", p.get("median", ""), p.get("p10", ""),
                          p.get("p90", ""), p.get("count", ""), p["method"], ""] if p else [""] * 9)
            dollars = [p["dollar"] for p in r["payers"] if p["dollar"]]
            w.writerow(vals + [min(dollars, default=""), max(dollars, default=""), ""])


def write_json(h, rows):
    keys, vals = meta_rows(h)
    doc = {
        "hospital_name": h["name"], "last_updated_on": vals[1], "version": "3.0.0",
        "location_name": [h["name"]], "hospital_address": [vals[4]],
        "license_information": {"license_number": vals[5], "state": "MA"},
        "type_2_npi": [vals[6]],
        "attestation": {"attestation": ATTESTATION, "confirm_attestation": True, "attester_name": "Demo Attester"},
        "standard_charge_information": [],
    }
    for r in rows:
        payers = []
        for p in r["payers"]:
            d = {"payer_name": p["payer"], "plan_name": p["plan"], "methodology": p["method"]}
            if p["dollar"]:
                d["standard_charge_dollar"] = p["dollar"]
            if p["pct"]:
                d["standard_charge_percentage"] = p["pct"]
            for k_out, k_in in [("median_amount", "median"), ("10th_percentile", "p10"),
                                ("90th_percentile", "p90"), ("count", "count")]:
                if k_in in p:
                    d[k_out] = p[k_in]
            payers.append(d)
        doc["standard_charge_information"].append({
            "description": r["s"]["service_name"],
            "code_information": [{"code": c, "type": t} for c, t in codes(r)],
            "standard_charges": [{"setting": r["setting"], "gross_charge": r["gross"],
                                  "discounted_cash": r["cash"], "payers_information": payers}],
        })
    (OUT / f"{h['id']}.json").write_text(json.dumps(doc, indent=1))


for h in HOSPITALS:
    rows = rows_for(h)
    {"tall": write_tall, "wide": write_wide, "json": write_json}[h["fmt"]](h, rows)
    print(f"{h['id']}: {len(rows)} services, {h['fmt']}")
