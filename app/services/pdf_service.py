import io
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether
)

COMPANY_NAME = "SevenUnique Tech Solutions Pvt. Ltd."
BRAND_NAME = "DhandaGrow"
COMPANY_ADDRESS = "Jaipur, Rajasthan 302017, India"
COMPANY_EMAIL = "support@dhandagrow.com"
COMPANY_PHONE = "+91-8741886688"
COMPANY_WEBSITE = "https://dhandagrow.com"


class PDFService:
    @staticmethod
    def _format_dt(dt_val: Any) -> str:
        if not dt_val:
            return "N/A"
        if isinstance(dt_val, datetime):
            return dt_val.strftime("%d %b %Y, %I:%M %p")
        if isinstance(dt_val, str):
            try:
                # Handle ISO strings
                dt = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
                return dt.strftime("%d %b %Y, %I:%M %p")
            except Exception:
                return dt_val[:19]
        return str(dt_val)

    @classmethod
    def generate_receipt_pdf(cls, transaction: Dict[str, Any]) -> bytes:
        """
        Generates a formal branded PDF receipt / tax invoice for a transaction.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()

        # Custom typography styles
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#1A202C"),
            fontName="Helvetica-Bold",
        )
        subtitle_style = ParagraphStyle(
            "SubTitle",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#4A5568"),
        )
        header_meta_style = ParagraphStyle(
            "HeaderMeta",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#2D3748"),
            alignment=2,  # Right aligned
        )
        section_heading = ParagraphStyle(
            "SectionHead",
            parent=styles["Heading2"],
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#2B6CB0"),
            fontName="Helvetica-Bold",
        )
        cell_bold = ParagraphStyle(
            "CellBold",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1A202C"),
        )
        cell_normal = ParagraphStyle(
            "CellNormal",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#2D3748"),
        )
        cell_right = ParagraphStyle(
            "CellRight",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            alignment=2,
            textColor=colors.HexColor("#2D3748"),
        )
        cell_right_bold = ParagraphStyle(
            "CellRightBold",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            alignment=2,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1A202C"),
        )

        elements = []

        # Header: Branding on Left, Invoice Details on Right
        txn_id = transaction.get("transaction_id") or "GROWG---"
        order_id = transaction.get("order_id") or "N/A"
        date_str = cls._format_dt(
            transaction.get("completed_at") or transaction.get("created_at")
        )
        status = str(transaction.get("status", "PENDING")).upper()

        brand_cell = [
            Paragraph(f"<b>{BRAND_NAME}</b>", title_style),
            Paragraph(f"{COMPANY_NAME}", subtitle_style),
            Paragraph(f"{COMPANY_ADDRESS}", subtitle_style),
            Paragraph(f"Email: {COMPANY_EMAIL} | Phone: {COMPANY_PHONE}", subtitle_style),
            Paragraph(f"Web: {COMPANY_WEBSITE}", subtitle_style),
        ]

        # Status badge color
        status_color = "#38A169" if status == "SUCCESS" else ("#E53E3E" if status in ["FAILED", "CANCELLED"] else "#DD6B20")

        meta_cell = [
            Paragraph(f"<b>PAYMENT RECEIPT</b>", ParagraphStyle("BigRec", parent=title_style, alignment=2, fontSize=16, textColor=colors.HexColor("#2B6CB0"))),
            Spacer(1, 4),
            Paragraph(f"<b>Receipt No:</b> {txn_id}", header_meta_style),
            Paragraph(f"<b>Order ID:</b> {order_id}", header_meta_style),
            Paragraph(f"<b>Date:</b> {date_str}", header_meta_style),
            Paragraph(f"<b>Status:</b> <font color='{status_color}'><b>{status}</b></font>", header_meta_style),
        ]

        top_table = Table(
            [[brand_cell, meta_cell]],
            colWidths=[310, 210]
        )
        top_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(top_table)
        elements.append(Spacer(1, 10))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2B6CB0"), spaceAfter=14))

        # Bill To & Payment Info (2 Column Table)
        user_name = transaction.get("user_name") or "Valued Customer"
        user_email = transaction.get("user_email") or "N/A"
        user_phone = transaction.get("user_phone") or "N/A"
        payment_mode = transaction.get("payment_mode") or "Unknown"
        gateway_tx = transaction.get("gateway_transaction_id") or transaction.get("external_transaction_id") or "N/A"
        provider_name = transaction.get("payment_provider") or transaction.get("payment_gateway") or "Payment Gateway"

        bill_to_cell = [
            Paragraph("<b>BILLED TO:</b>", section_heading),
            Spacer(1, 4),
            Paragraph(f"<b>Name:</b> {user_name}", cell_normal),
            Paragraph(f"<b>Email:</b> {user_email}", cell_normal),
            Paragraph(f"<b>Phone:</b> {user_phone}", cell_normal),
        ]

        pay_info_cell = [
            Paragraph("<b>PAYMENT INFORMATION:</b>", section_heading),
            Spacer(1, 4),
            Paragraph(f"<b>Payment Mode:</b> {payment_mode}", cell_normal),
            Paragraph(f"<b>Gateway / Provider:</b> {provider_name}", cell_normal),
            Paragraph(f"<b>Gateway Ref No:</b> {gateway_tx}", cell_normal),
        ]

        cust_table = Table([[bill_to_cell, pay_info_cell]], colWidths=[260, 260])
        cust_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        elements.append(cust_table)
        elements.append(Spacer(1, 15))

        # Itemized Plan Table
        plan_name = transaction.get("plan_name") or transaction.get("plan_id") or "Subscription Plan"
        billing_cycle = (transaction.get("billing_cycle") or transaction.get("plan_duration") or "Monthly").title()
        credits_count = transaction.get("credits_included") or transaction.get("purchased_credits") or 0
        currency = transaction.get("currency", "INR")
        total_amount = float(transaction.get("amount", 0.0))
        base_amount = float(transaction.get("base_amount", total_amount))
        gst_amount = float(transaction.get("gst_amount", 0.0))
        gst_rate = float(transaction.get("gst_rate", 0.18)) if gst_amount > 0 else 0.0

        item_desc = f"<b>{plan_name}</b> ({billing_cycle})<br/><font color='#718096' size='8'>Includes {credits_count} AI Credits • Full Feature Access</font>"

        headers = [
            Paragraph("<b>Item & Description</b>", cell_bold),
            Paragraph("<b>Cycle</b>", cell_bold),
            Paragraph("<b>AI Credits</b>", cell_bold),
            Paragraph(f"<b>Net Amount ({currency})</b>", cell_right_bold),
        ]

        row_item = [
            Paragraph(item_desc, cell_normal),
            Paragraph(billing_cycle, cell_normal),
            Paragraph(f"{credits_count:,}", cell_normal),
            Paragraph(f"{base_amount:,.2f}", cell_right),
        ]

        items_data = [headers, row_item]
        items_table = Table(items_data, colWidths=[240, 90, 80, 110])
        items_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 10))

        # Totals Summary Box
        totals_rows = [
            [Paragraph("Subtotal (Base Price):", cell_normal), Paragraph(f"₹ {base_amount:,.2f}", cell_right)],
        ]
        if gst_amount > 0:
            totals_rows.append([
                Paragraph(f"GST ({int(gst_rate * 100)}%):", cell_normal),
                Paragraph(f"₹ {gst_amount:,.2f}", cell_right)
            ])
        totals_rows.append([
            Paragraph("<b>Total Paid:</b>", cell_bold),
            Paragraph(f"<b>₹ {total_amount:,.2f} {currency}</b>", cell_right_bold)
        ])

        totals_table = Table(totals_rows, colWidths=[150, 100], hAlign="RIGHT")
        totals_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EDF2F7")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(totals_table)
        elements.append(Spacer(1, 25))

        # Footer Acknowledgement Box
        footer_text = (
            "<b>Payment Acknowledgment:</b><br/>"
            "This document is an electronically generated official receipt confirming your subscription payment "
            "to <b>SevenUnique Tech Solutions Pvt. Ltd.</b> through our secure payment gateway. "
            "No signature is required. For inquiries, contact support@dhandagrow.com."
        )
        footer_p = Paragraph(footer_text, ParagraphStyle("FooterP", parent=styles["Normal"], fontSize=8, leading=12, textColor=colors.HexColor("#718096")))
        footer_table = Table([[footer_p]], colWidths=[520])
        footer_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EDF2F7")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        elements.append(footer_table)

        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()

    @classmethod
    def generate_transaction_list_pdf(
        cls,
        transactions: List[Dict[str, Any]],
        user_info: Dict[str, Any],
        filters: Dict[str, Any]
    ) -> bytes:
        """
        Generates a user-scoped statement / list PDF of transaction history.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=28,
            leftMargin=28,
            topMargin=28,
            bottomMargin=28
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "ListTitle",
            parent=styles["Heading1"],
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1A202C"),
            fontName="Helvetica-Bold",
        )
        subtitle_style = ParagraphStyle(
            "ListSub",
            parent=styles["Normal"],
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#4A5568"),
        )
        meta_label = ParagraphStyle(
            "MetaLabel",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#2D3748"),
        )
        meta_val = ParagraphStyle(
            "MetaVal",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#4A5568"),
        )
        th_style = ParagraphStyle(
            "TH",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1A202C"),
        )
        td_style = ParagraphStyle(
            "TD",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#2D3748"),
        )
        td_right = ParagraphStyle(
            "TDRight",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=10,
            alignment=2,
            textColor=colors.HexColor("#2D3748"),
        )

        elements = []

        # Title & Branding
        now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")
        header_table = Table([
            [
                Paragraph(f"<b>{BRAND_NAME}</b> • Transaction History Report", title_style),
                Paragraph(f"Generated: {now_str}", ParagraphStyle("GenDate", parent=subtitle_style, alignment=2))
            ]
        ], colWidths=[380, 158])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2B6CB0"), spaceAfter=10))

        # User and Filters Panel
        user_name = user_info.get("name") or "User"
        user_email = user_info.get("email") or "N/A"
        user_phone = user_info.get("phone") or "N/A"

        f_status = filters.get("status") or "All"
        f_mode = filters.get("payment_mode") or "All"
        f_search = filters.get("search") or "None"
        date_range = f"{filters.get('date_from', 'Start')} to {filters.get('date_to', 'End')}"

        info_data = [
            [
                Paragraph("<b>Account Name:</b>", meta_label), Paragraph(str(user_name), meta_val),
                Paragraph("<b>Status Filter:</b>", meta_label), Paragraph(str(f_status), meta_val),
            ],
            [
                Paragraph("<b>Email:</b>", meta_label), Paragraph(str(user_email), meta_val),
                Paragraph("<b>Payment Mode:</b>", meta_label), Paragraph(str(f_mode), meta_val),
            ],
            [
                Paragraph("<b>Phone:</b>", meta_label), Paragraph(str(user_phone), meta_val),
                Paragraph("<b>Search / Date:</b>", meta_label), Paragraph(f"{f_search} | {date_range}", meta_val),
            ]
        ]
        info_table = Table(info_data, colWidths=[80, 180, 90, 188])
        info_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EDF2F7")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 10))

        # Transactions Table
        headers = [
            Paragraph("<b>Txn ID</b>", th_style),
            Paragraph("<b>Date & Time</b>", th_style),
            Paragraph("<b>Plan Name</b>", th_style),
            Paragraph("<b>Mode</b>", th_style),
            Paragraph("<b>Amount (INR)</b>", ParagraphStyle("THRight", parent=th_style, alignment=2)),
            Paragraph("<b>Status</b>", th_style),
            Paragraph("<b>Gateway Ref</b>", th_style),
        ]
        rows = [headers]

        total_spent = 0.0
        success_count = 0

        for tx in transactions:
            txn_id = tx.get("transaction_id") or tx.get("order_id") or "N/A"
            dt_str = cls._format_dt(tx.get("created_at"))
            p_name = tx.get("plan_name") or tx.get("plan_id") or "N/A"
            cycle = (tx.get("billing_cycle") or tx.get("plan_duration") or "Monthly").title()
            p_display = f"{p_name} ({cycle[:3]})"
            mode = tx.get("payment_mode") or "Unknown"
            amt = float(tx.get("amount", 0.0))
            st = str(tx.get("status", "pending")).upper()
            gw_ref = tx.get("gateway_transaction_id") or tx.get("external_transaction_id") or tx.get("order_id") or "-"

            if st == "SUCCESS":
                st_color = "#38A169"
                total_spent += amt
                success_count += 1
            elif st in ["FAILED", "CANCELLED", "EXPIRED"]:
                st_color = "#E53E3E"
            else:
                st_color = "#DD6B20"

            st_html = f"<font color='{st_color}'><b>{st}</b></font>"

            rows.append([
                Paragraph(f"<b>{txn_id}</b>", td_style),
                Paragraph(dt_str, td_style),
                Paragraph(p_display, td_style),
                Paragraph(mode, td_style),
                Paragraph(f"₹ {amt:,.2f}", td_right),
                Paragraph(st_html, td_style),
                Paragraph(str(gw_ref)[:16], td_style),
            ])

        # Widths total: 538 (A4 width 595 - 2*28 = 539)
        col_widths = [65, 85, 105, 65, 75, 60, 83]
        tx_table = Table(rows, colWidths=col_widths, repeatRows=1)
        tx_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(tx_table)
        elements.append(Spacer(1, 10))

        # Summary box
        summary_p = Paragraph(
            f"<b>Total Records:</b> {len(transactions)} | "
            f"<b>Successful Payments:</b> {success_count} | "
            f"<b>Total Successful Paid:</b> ₹ {total_spent:,.2f} INR",
            ParagraphStyle("SummP", parent=styles["Normal"], fontSize=8.5, leading=12, textColor=colors.HexColor("#2B6CB0"))
        )
        summ_table = Table([[summary_p]], colWidths=[538])
        summ_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EBF8FF")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BEE3F8")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(summ_table)

        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()

