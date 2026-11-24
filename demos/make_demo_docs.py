"""Builds the two demo corpora. The documents are synthetic (fictional company "Meridian Shipping").

Written by hand/script rather than by an LLM, so no generation prompt is needed; the exact text
is in this file and reproducible with:  python demos/make_demo_docs.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).parent


def pdf(path: Path, title: str, sections: list[tuple[str, list[str]]]) -> None:
    html = f"<h1>{title}</h1><p>Meridian Shipping Pvt Ltd. Internal document.</p>"
    for head, paras in sections:
        html += f"<h2>{head}</h2>" + "".join(f"<p>{p}</p>" for p in paras)
    story = fitz.Story(html)
    writer = fitz.DocumentWriter(str(path))
    media = fitz.paper_rect("a4")
    where = media + (54, 54, -54, -54)
    more = 1
    while more:
        dev = writer.begin_page(media)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()


# ----------------------------------------------------------------- demo 1: HR
def hr() -> None:
    d = ROOT / "hr_docs"
    d.mkdir(exist_ok=True, parents=True)
    pdf(d / "leave_policy.pdf", "Leave Policy (Shore Staff) v4.2", [
        ("1. Annual Leave", [
            "Shore staff accrue 24 days of paid annual leave per calendar year. Leave accrues monthly at 2 days per month of service.",
            "Up to 10 unused days may be carried forward to the next year. Carried-forward days expire on 31 March of the following year.",
            "Annual leave of more than 5 consecutive working days must be requested at least 14 days in advance through the HR portal.",
        ]),
        ("2. Sick Leave", [
            "Employees receive 12 days of paid sick leave per year. A medical certificate is required for any sick leave of 3 or more consecutive days.",
            "Sick leave cannot be carried forward. Sick leave taken immediately before or after a public holiday requires a medical certificate regardless of duration.",
        ]),
        ("3. Parental Leave", [
            "Mothers are entitled to 26 weeks of paid maternity leave. Fathers and non-birthing partners are entitled to 10 working days of paid paternity leave, to be taken within 6 months of the birth or adoption.",
            "Employees must notify HR of the expected date at least 8 weeks before the leave begins.",
        ]),
        ("4. Bereavement and Emergency Leave", [
            "Up to 5 days of paid bereavement leave are granted on the death of a spouse, child, parent or sibling. For other relatives, 2 days are granted.",
            "Emergency leave of up to 3 days per year may be approved by a line manager for urgent personal matters such as a house fire or hospitalisation of a family member.",
        ]),
        ("5. Approval", [
            "Leave requests are approved by the line manager within 3 working days. If a request is not answered within 3 working days it escalates automatically to the Head of Department.",
            "Leave during the quarter-end closing week (the last 5 working days of March, June, September and December) is granted only with Head of Department approval.",
        ]),
    ])
    pdf(d / "code_of_conduct.pdf", "Code of Conduct and Workplace Behaviour v3.0", [
        ("1. Working Hours and Attendance", [
            "Core working hours are 09:30 to 17:30, Monday to Friday, with a one hour lunch break. Staff must be reachable during core hours.",
            "Hybrid working is allowed for up to 2 days per week with line manager approval. Working from another country requires written approval from HR and is limited to 20 days per year.",
        ]),
        ("2. Gifts and Hospitality", [
            "Employees must not accept gifts worth more than USD 50 from suppliers, customers or agents. Any gift above this value must be declined or reported to Compliance within 5 working days.",
            "Cash or cash equivalents, such as gift cards, may never be accepted regardless of value.",
        ]),
        ("3. Harassment and Reporting Concerns", [
            "Meridian has zero tolerance for harassment or discrimination. Concerns can be raised with a line manager, with HR, or anonymously through the Ethics Hotline at ethics@meridian.example.",
            "Reports are acknowledged within 2 working days and investigations are normally completed within 30 calendar days. Retaliation against anyone who reports in good faith is a disciplinary offence.",
        ]),
        ("4. Use of Company Equipment and Data", [
            "Company laptops are for business use. Confidential data must not be copied to personal cloud storage or personal email.",
            "Lost or stolen devices must be reported to IT Security within 24 hours.",
        ]),
        ("5. Disciplinary Process", [
            "Minor breaches lead to a documented verbal warning, then a written warning. Serious misconduct may lead to suspension on full pay pending investigation, for up to 10 working days.",
        ]),
    ])
    pdf(d / "travel_expense_policy.pdf", "Travel and Expense Policy v2.5", [
        ("1. Booking Business Travel", [
            "All flights and hotels must be booked through the corporate travel desk at least 7 days before departure. Economy class is mandatory for flights under 6 hours. Business class may be approved for flights of 6 hours or longer by the Head of Department.",
            "Hotel stays are capped at USD 180 per night in tier-1 cities (London, Singapore, New York, Dubai) and USD 110 per night elsewhere.",
        ]),
        ("2. Daily Allowance (Per Diem)", [
            "The per diem for meals and incidentals is USD 60 per day in tier-1 cities and USD 40 per day elsewhere. If a meal is provided by the host, the per diem is reduced by USD 15 per meal.",
        ]),
        ("3. Claiming Expenses", [
            "Expense claims must be submitted within 30 days of returning from the trip, with original receipts for any item above USD 25. Claims submitted after 30 days require approval from the Finance Controller.",
            "Reimbursement is made within 10 working days of approval. Alcohol is never reimbursable.",
        ]),
        ("4. Leave During Travel", [
            "Travel time on weekends is not credited as leave or time off in lieu, unless the line manager approves compensatory time in writing. Personal days added to a business trip are treated as annual leave under the Leave Policy.",
        ]),
    ])


# ----------------------------------------------------------- demo 2: spares
def spares() -> None:
    d = ROOT / "spares_docs"
    d.mkdir(exist_ok=True, parents=True)
    rng = random.Random(11)
    parts = [
        ("Fuel injector nozzle", "Main engine", "MAN B&W 6S50MC", 412.50, "OP"),
        ("Piston ring set", "Main engine", "MAN B&W 6S50MC", 1890.00, "OP"),
        ("Cylinder liner", "Main engine", "MAN B&W 6S50MC", 7450.00, "NM"),
        ("Exhaust valve spindle", "Main engine", "MAN B&W 6S50MC", 3220.00, "NM"),
        ("Turbocharger bearing kit", "Main engine", "ABB TPL77", 2675.00, "OP"),
        ("Fuel pump plunger", "Main engine", "MAN B&W 6S50MC", 980.00, "NM"),
        ("Lube oil filter element", "Auxiliary engine", "Wartsila 6L20", 64.90, "OP"),
        ("Fuel oil filter element", "Auxiliary engine", "Wartsila 6L20", 58.40, "OP"),
        ("Cylinder head gasket", "Auxiliary engine", "Wartsila 6L20", 134.00, "OP"),
        ("Connecting rod bearing shell", "Auxiliary engine", "Wartsila 6L20", 289.00, "NM"),
        ("Starting air valve", "Auxiliary engine", "Wartsila 6L20", 520.00, "NM"),
        ("Seawater pump impeller", "Pumps", "Alfa Laval SW-150", 346.00, "OP"),
        ("Mechanical seal", "Pumps", "Alfa Laval SW-150", 218.00, "OP"),
        ("Pump shaft sleeve", "Pumps", "Alfa Laval SW-150", 172.00, "OP"),
        ("Bilge pump diaphragm", "Pumps", "Wilden P4", 96.50, "OP"),
        ("Purifier disc stack", "Purifier", "Alfa Laval S-946", 1560.00, "NM"),
        ("Purifier O-ring kit", "Purifier", "Alfa Laval S-946", 41.30, "OP"),
        ("Boiler burner nozzle", "Boiler", "Aalborg OL", 205.00, "OP"),
        ("Boiler gauge glass set", "Boiler", "Aalborg OL", 77.80, "OP"),
        ("Flame sensor", "Boiler", "Aalborg OL", 163.00, "NM"),
        ("Steering gear hydraulic seal kit", "Deck machinery", "Rolls-Royce SR-562", 640.00, "NM"),
        ("Windlass brake band", "Deck machinery", "Hatlapa W-30", 1125.00, "NM"),
        ("Mooring winch brake lining", "Deck machinery", "Hatlapa W-30", 388.00, "OP"),
        ("Hydraulic hose assembly 2m", "Deck machinery", "Generic", 52.00, "OP"),
        ("LED navigation light", "Navigation", "Aqua Signal 25", 118.00, "OP"),
        ("Radar magnetron", "Navigation", "Furuno FAR-2218", 2340.00, "NM"),
        ("GPS antenna", "Navigation", "Furuno GP-39", 295.00, "NM"),
        ("Lifeboat release hook pin", "Safety", "Schat-Davit", 76.00, "OP"),
        ("Fire extinguisher 9kg CO2", "Safety", "Generic", 189.00, "OP"),
        ("EPIRB battery", "Safety", "McMurdo E5", 410.00, "OP"),
        ("Immersion suit", "Safety", "Viking PS5005", 340.00, "OP"),
        ("Air compressor valve plate", "Air compressor", "Sperre HL2", 142.00, "OP"),
        ("Compressor piston ring set", "Air compressor", "Sperre HL2", 108.50, "OP"),
        ("Oily water separator filter", "Environmental", "RWO Skit", 232.00, "NM"),
        ("Sewage plant blower diaphragm", "Environmental", "Hamworthy ST", 87.00, "OP"),
        ("Alternator carbon brush set", "Electrical", "Stamford HCM", 64.00, "OP"),
        ("Circuit breaker 400A", "Electrical", "ABB Tmax", 780.00, "NM"),
        ("Cable gland M32", "Electrical", "Generic", 4.80, "OP"),
        ("Deck crane wire rope 20mm 100m", "Deck machinery", "Generic", 970.00, "NM"),
    ]
    rows = []
    for i, (desc, cat, equip, price, sup) in enumerate(parts, 1):
        stock = rng.choice([0, 0, 1, 2, 3, 4, 6, 8, 12, 20, 40])
        lead = rng.choice([5, 7, 10, 14, 21, 28, 35, 42]) if sup == "OP" else rng.choice([10, 14, 21, 28, 45])
        moq = 1 if price > 300 else rng.choice([1, 2, 5, 10])
        rows.append({"part_no": f"SP-{1000 + i * 7}", "description": desc, "category": cat, "equipment": equip,
                     "unit_price_usd": price, "stock_qty": stock, "lead_time_days": lead,
                     "min_order_qty": moq, "supplier_id": "OceanParts" if sup == "OP" else "NordMarine"})
    with open(d / "spares_catalogue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    pdf(d / "supplier_oceanparts_terms.pdf", "OceanParts Ltd - Supply Agreement Terms", [
        ("1. Pricing and Discounts", [
            "Catalogue prices are in USD and exclude freight and taxes. A volume discount of 5% applies to a single order with a value above USD 5,000, and 8% to a single order above USD 15,000.",
            "Prices are fixed for 90 days from the catalogue date.",
        ]),
        ("2. Delivery", [
            "Standard delivery is to the nominated port agent. Express air freight is available at a surcharge of 12% of the order value and shortens the lead time by 50%.",
            "Late delivery of more than 7 days beyond the quoted lead time entitles the buyer to a 2% credit per week of delay, capped at 10% of the order value.",
        ]),
        ("3. Payment", [
            "Payment terms are net 45 days from invoice date. A 1.5% early payment discount applies if paid within 10 days.",
        ]),
        ("4. Returns and Warranty", [
            "Unused parts in original packaging may be returned within 30 days for a refund less a 15% restocking fee. Warranty on all parts is 12 months from delivery against manufacturing defects.",
        ]),
    ])
    pdf(d / "supplier_nordmarine_terms.pdf", "NordMarine AS - Terms of Sale", [
        ("1. Pricing", [
            "Catalogue prices are in USD. A discount of 6% applies to a single order above USD 8,000. No discount applies below that value.",
            "OEM-certified parts carry a class-society certificate at no extra charge. Certificates for non-OEM parts cost USD 150 per order.",
        ]),
        ("2. Delivery", [
            "Delivery is DAP to the nominated port. Express delivery is available at a surcharge of 20% of the order value and halves the stated lead time. Orders placed after 14:00 CET are processed the next working day.",
        ]),
        ("3. Payment", [
            "Payment terms are net 30 days from invoice. No early-payment discount is offered.",
        ]),
        ("4. Returns and Warranty", [
            "Returns are accepted within 14 days only, with a 25% restocking fee. Warranty is 24 months from delivery for OEM parts and 6 months for non-OEM parts.",
        ]),
    ])
    pdf(d / "procurement_procedure.pdf", "Fleet Spares Procurement Procedure v1.8", [
        ("1. Approval Thresholds", [
            "Purchase orders up to USD 2,000 may be approved by the Chief Engineer. Orders from USD 2,001 to USD 10,000 require approval from the Superintendent. Orders above USD 10,000 require approval from the Technical Director.",
            "Splitting an order to stay under an approval threshold is prohibited.",
        ]),
        ("2. Quotes", [
            "For orders above USD 5,000, at least 2 quotes must be obtained unless the part is single-source. Single-source justification must be recorded in the purchase order.",
        ]),
        ("3. Critical Spares", [
            "Parts classed as critical must never be allowed to fall to zero stock. When a critical part has stock of 1 or below, a replenishment order must be raised within 2 working days.",
            "Critical categories are: Main engine, Steering gear and Safety.",
        ]),
        ("4. Urgent Orders", [
            "Urgent orders needed for a vessel arriving at port within 10 days may use express freight. The Superintendent must approve the express surcharge regardless of order value.",
        ]),
    ])


if __name__ == "__main__":
    hr()
    spares()
    print("demo documents written to", ROOT)
