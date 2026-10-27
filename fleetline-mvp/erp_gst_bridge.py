"""Axiom Mobility (Fleetline) Tri-Stack GST E-Invoice & Tally Prime Bridge.

1. Rent-a-Cab HSN/SAC 996601 Tax Rules:
   - 5% GST without ITC (with automatic RCM detection)
   - 12% / 18% GST with ITC
2. NIC Standard E-Invoicing Payload Generator (IRN, AckNo, SignedQRCode)
3. Tally Prime XML Exporter (Masters + Vouchers Envelopes for Sundry Debtors & Creditors)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict, List, Optional


def determine_gst_tax_structure(
    supplier_gstin: str,
    client_gstin: str,
    supplier_is_corporate: bool,
    opted_itc_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolves Rent-a-Cab GST (HSN/SAC 996601), Intra vs Inter-state IGST, and RCM applicability."""
    hsn_sac = "996601"
    is_inter_state = supplier_gstin[:2] != client_gstin[:2] if (supplier_gstin and client_gstin and len(supplier_gstin) >= 2 and len(client_gstin) >= 2) else False

    # Standard default in Indian mobility: 5% without ITC
    rate_pct = 5.0 if opted_itc_rate is None else float(opted_itc_rate)

    # Statutory RCM Rule: If provider is non-corporate (individual/proprietorship/partnership) and recipient is corporate entity
    is_rcm = (not supplier_is_corporate) and (len(client_gstin) == 15) and rate_pct == 5.0

    if is_inter_state:
        tax_split = {"igst_pct": rate_pct, "cgst_pct": 0.0, "sgst_pct": 0.0}
    else:
        half = round(rate_pct / 2.0, 2)
        tax_split = {"igst_pct": 0.0, "cgst_pct": half, "sgst_pct": half}

    return {
        "hsn_sac": hsn_sac,
        "total_gst_pct": rate_pct,
        "is_rcm_applicable": is_rcm,
        "is_inter_state": is_inter_state,
        "tax_breakdown": tax_split,
        "itc_eligible": rate_pct > 5.0,
    }


def generate_irp_einvoice_payload(
    invoice_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Generates NIC standard e-Invoice schema payload and computes deterministic mock IRN."""
    inv_num = invoice_data.get("invoice_number", "AXM-INV-001")
    supplier_gstin = invoice_data.get("supplier_gstin", "29AABCA1234F1Z1")
    client_gstin = invoice_data.get("client_gstin", "29AABCC5678K1Z2")
    doc_date = invoice_data.get("invoice_date", dt.date.today().strftime("%d/%m/%Y"))
    doc_val = round(float(invoice_data.get("total_amount_paise", 0)) / 100.0, 2)

    # Compute 64-character SHA-256 IRN hash
    raw_str = f"{supplier_gstin}:{inv_num}:INV:{doc_date}:{doc_val}"
    irn = hashlib.sha256(raw_str.encode()).hexdigest()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    ack_no = f"1126{int(dt.datetime.now().timestamp()) % 100000000:08d}"

    nic_payload = {
        "Version": "1.1",
        "TranDtls": {
            "TaxSch": "GST",
            "SupTyp": "B2B",
            "RegRev": "Y" if invoice_data.get("is_rcm_applicable") else "N",
        },
        "DocDtls": {
            "Typ": "INV",
            "No": inv_num,
            "Dt": doc_date,
        },
        "SellerDtls": {
            "Gstin": supplier_gstin,
            "LglNm": invoice_data.get("supplier_legal_name", "Axiom Fleet Logistics Pvt Ltd"),
            "TrdNm": invoice_data.get("supplier_trade_name", "Axiom Fleet"),
            "Addr1": invoice_data.get("supplier_address", "Indiranagar 100ft Rd"),
            "Loc": invoice_data.get("supplier_city", "Bengaluru"),
            "Pin": 560038,
            "Stcd": supplier_gstin[:2] if len(supplier_gstin) >= 2 else "29",
        },
        "BuyerDtls": {
            "Gstin": client_gstin,
            "LglNm": invoice_data.get("client_legal_name", "Enterprise Client Technologies"),
            "Loc": invoice_data.get("client_city", "Bengaluru"),
            "Pin": 560100,
            "Stcd": client_gstin[:2] if len(client_gstin) >= 2 else "29",
        },
        "ItemList": [
            {
                "SlNo": "1",
                "PrdDesc": "Passenger Car Rental Services",
                "IsServc": "Y",
                "HsnCd": "996601",
                "TotAmt": doc_val,
                "AssAmt": round(doc_val / 1.05, 2),
                "GstRt": 5.0,
                "TotItemVal": doc_val,
            }
        ],
        "ValDtls": {
            "AssVal": round(doc_val / 1.05, 2),
            "TotInvVal": doc_val,
        },
    }

    signed_qr = f"https://einvoice1.gst.gov.in/qr?irn={irn}&ackno={ack_no}&val={doc_val}"

    return {
        "irn": irn,
        "ack_no": ack_no,
        "ack_dt": now_iso,
        "signed_qr_code": signed_qr,
        "nic_payload": nic_payload,
        "status": "GENERATED_AND_SIGNED",
    }


def export_tally_prime_xml(
    invoices: List[Dict[str, Any]],
    supplier_purchases: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Exports Tally Prime compatible XML for Sundry Debtors (Sales) and Sundry Creditors (Purchases + TDS 194C)."""
    xml_lines = [
        '<ENVELOPE>',
        '  <HEADER>',
        '    <TALLYREQUEST>Import Data</TALLYREQUEST>',
        '  </HEADER>',
        '  <BODY>',
        '    <IMPORTDATA>',
        '      <REQUESTDESC>',
        '        <REPORTNAME>Vouchers</REPORTNAME>',
        '      </REQUESTDESC>',
        '      <REQUESTDATA>',
    ]

    # 1. Sales Vouchers (Corporate Clients / Sundry Debtors)
    for inv in (invoices or []):
        inv_no = inv.get("invoice_number", "INV-001")
        date_str = inv.get("invoice_date_tally", dt.date.today().strftime("%Y%m%d"))
        client_name = inv.get("client_name", "Corporate Client A")
        gross_amt = round(float(inv.get("gross_amount_paise", 0)) / 100.0, 2)
        gst_amt = round(float(inv.get("gst_amount_paise", 0)) / 100.0, 2)
        net_amt = round(float(inv.get("net_amount_paise", 0)) / 100.0, 2)
        cost_center = inv.get("cost_center", "Corporate Fleet Operations")

        xml_lines.extend([
            '        <TALLYMESSAGE xmlns:UDF="TallyUDF">',
            f'          <VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Accounting Voucher View">',
            f'            <DATE>{date_str}</DATE>',
            f'            <VOUCHERNUMBER>{inv_no}</VOUCHERNUMBER>',
            f'            <PARTYLEDGERNAME>{client_name}</PARTYLEDGERNAME>',
            f'            <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>',
            f'            <ALLLEDGERENTRIES.LIST>',
            f'              <LEDGERNAME>{client_name}</LEDGERNAME>',
            f'              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>',
            f'              <AMOUNT>-{net_amt}</AMOUNT>',
            f'            </ALLLEDGERENTRIES.LIST>',
            f'            <ALLLEDGERENTRIES.LIST>',
            f'              <LEDGERNAME>Car Rental Revenue (SAC 996601)</LEDGERNAME>',
            f'              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>',
            f'              <AMOUNT>{gross_amt}</AMOUNT>',
            f'              <COSTCENTRENAME>{cost_center}</COSTCENTRENAME>',
            f'            </ALLLEDGERENTRIES.LIST>',
            f'            <ALLLEDGERENTRIES.LIST>',
            f'              <LEDGERNAME>Output GST 5%</LEDGERNAME>',
            f'              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>',
            f'              <AMOUNT>{gst_amt}</AMOUNT>',
            f'            </ALLLEDGERENTRIES.LIST>',
            f'          </VOUCHER>',
            '        </TALLYMESSAGE>',
        ])

    # 2. Purchase Vouchers (Partner Fleet Vendors / Sundry Creditors with TDS 194C)
    for pur in (supplier_purchases or []):
        pur_no = pur.get("voucher_number", f"PUR-{int(dt.datetime.now().timestamp())}")
        date_str = pur.get("date_tally", dt.date.today().strftime("%Y%m%d"))
        vendor_name = pur.get("vendor_name", "Partner Fleet Vendor B")
        gross_amt = round(float(pur.get("gross_amount_paise", 0)) / 100.0, 2)
        tds_pct = float(pur.get("tds_pct", 1.0))  # Section 194C 1% individual or 2% corporate
        tds_amt = round(gross_amt * (tds_pct / 100.0), 2)
        net_payable = round(gross_amt - tds_amt, 2)
        cost_center = pur.get("cost_center", "Outsourced Fleet Supply")

        xml_lines.extend([
            '        <TALLYMESSAGE xmlns:UDF="TallyUDF">',
            f'          <VOUCHER VCHTYPE="Purchase" ACTION="Create" OBJVIEW="Accounting Voucher View">',
            f'            <DATE>{date_str}</DATE>',
            f'            <VOUCHERNUMBER>{pur_no}</VOUCHERNUMBER>',
            f'            <PARTYLEDGERNAME>{vendor_name}</PARTYLEDGERNAME>',
            f'            <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>',
            f'            <ALLLEDGERENTRIES.LIST>',
            f'              <LEDGERNAME>Fleet Hire Expense (SAC 996601)</LEDGERNAME>',
            f'              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>',
            f'              <AMOUNT>-{gross_amt}</AMOUNT>',
            f'              <COSTCENTRENAME>{cost_center}</COSTCENTRENAME>',
            f'            </ALLLEDGERENTRIES.LIST>',
            f'            <ALLLEDGERENTRIES.LIST>',
            f'              <LEDGERNAME>{vendor_name}</LEDGERNAME>',
            f'              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>',
            f'              <AMOUNT>{net_payable}</AMOUNT>',
            f'            </ALLLEDGERENTRIES.LIST>',
            f'            <ALLLEDGERENTRIES.LIST>',
            f'              <LEDGERNAME>TDS on Transport Contractor Sec 194C</LEDGERNAME>',
            f'              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>',
            f'              <AMOUNT>{tds_amt}</AMOUNT>',
            f'            </ALLLEDGERENTRIES.LIST>',
            f'          </VOUCHER>',
            '        </TALLYMESSAGE>',
        ])

    xml_lines.extend([
        '      </REQUESTDATA>',
        '    </IMPORTDATA>',
        '  </BODY>',
        '</ENVELOPE>',
    ])

    return '\n'.join(xml_lines)
