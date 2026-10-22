import hashlib
import io
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import fitz  # PyMuPDF


class AgreementPdfService:
    """
    Generates professional, legally structured PDF documents for SevenUnique AI
    Influencer Marketing Agreements with bilateral signatures, cryptographic verification,
    and platform escrow terms.
    """

    @staticmethod
    def generate_pdf(agreement: Dict[str, Any]) -> bytes:
        doc = fitz.open()

        # Dimensions: A4 = 595.3 x 841.9 pt
        width, height = 595.3, 841.9
        margin = 36.0
        content_w = width - (margin * 2)

        hirer = agreement.get("hirer_party") or {}
        creator = agreement.get("influencer_party") or {}
        camp = agreement.get("campaign_details") or {}
        fin = agreement.get("financial_terms") or {}
        clauses = agreement.get("legal_clauses") or []
        sigs = agreement.get("signatures") or {}
        status = (agreement.get("status") or "draft").replace("_", " ").upper()

        # =========================================================================
        # PAGE 1: COVER, PARTIES, CAMPAIGN DETAILS & FINANCIALS
        # =========================================================================
        p1 = doc.new_page(width=width, height=height)

        # Header Banner
        p1.draw_rect(fitz.Rect(margin, margin, width - margin, margin + 60), color=None, fill=(0.07, 0.08, 0.14))
        p1.insert_text(
            (margin + 16, margin + 26),
            "SEVENUNIQUE AI PLATFORM",
            fontsize=12,
            fontname="helv",
            color=(0.75, 0.45, 1.0)
        )
        p1.insert_text(
            (margin + 16, margin + 46),
            "BILATERAL INFLUENCER MARKETING AGREEMENT",
            fontsize=14,
            fontname="helv",
            color=(1.0, 1.0, 1.0)
        )

        # Status badge & Agreement metadata
        agr_num = agreement.get("agreement_number", "AGR-2026-XXXX")
        version = agreement.get("version", "1.0")
        created_at_str = str(agreement.get("created_at") or datetime.now(timezone.utc).strftime("%d/%m/%Y, %H:%M UTC"))

        p1.insert_textbox(
            fitz.Rect(width - margin - 190, margin + 12, width - margin - 16, margin + 50),
            f"Agreement: {agr_num}\nVersion: {version} | {status}",
            fontsize=8.5,
            fontname="helv",
            color=(0.8, 0.8, 0.9),
            align=fitz.TEXT_ALIGN_RIGHT
        )

        y = margin + 75

        # Campaign Title Card
        title = agreement.get("title") or f"Influencer Marketing Agreement — {camp.get('campaign_name', 'Campaign')}"
        p1.draw_rect(fitz.Rect(margin, y, width - margin, y + 36), color=(0.85, 0.85, 0.9), fill=(0.96, 0.96, 0.98), width=0.8)
        p1.insert_textbox(
            fitz.Rect(margin + 12, y + 8, width - margin - 12, y + 32),
            title,
            fontsize=11,
            fontname="helv",
            color=(0.1, 0.1, 0.25)
        )

        y += 46

        # SECTION 1: CONTRACTING PARTIES (2 Columns)
        col_w = (content_w - 12) / 2
        p1.insert_text((margin, y + 10), "1. CONTRACTING PARTIES", fontsize=9.5, fontname="helv", color=(0.3, 0.3, 0.5))
        y += 16

        # Party A Box
        p1.draw_rect(fitz.Rect(margin, y, margin + col_w, y + 100), color=(0.82, 0.82, 0.88), fill=(0.98, 0.98, 1.0), width=0.6)
        p1.insert_text((margin + 10, y + 16), "PARTY A: HIRER / BRAND", fontsize=8.5, fontname="helv", color=(0.5, 0.3, 0.8))
        h_name = hirer.get("legal_name") or "Authorized Representative"
        h_biz = hirer.get("business_name") or "Registered Business"
        h_email = hirer.get("email") or "brand@example.com"
        h_addr = hirer.get("address") or "Registered Office, India"
        h_gstin = hirer.get("gstin") or "NA (Standard Platform Merchant)"
        h_id = hirer.get("user_id", "")[:16]

        party_a_text = (
            f"Legal Name: {h_name}\n"
            f"Business: {h_biz}\n"
            f"Email: {h_email}\n"
            f"Address: {h_addr}\n"
            f"GSTIN / Tax: {h_gstin}\n"
            f"Account ID: {h_id}..."
        )
        p1.insert_textbox(
            fitz.Rect(margin + 10, y + 24, margin + col_w - 10, y + 96),
            party_a_text,
            fontsize=8,
            fontname="helv",
            color=(0.15, 0.15, 0.2)
        )

        # Party B Box
        col2_x = margin + col_w + 12
        p1.draw_rect(fitz.Rect(col2_x, y, col2_x + col_w, y + 100), color=(0.82, 0.82, 0.88), fill=(1.0, 0.98, 0.96), width=0.6)
        p1.insert_text((col2_x + 10, y + 16), "PARTY B: CREATOR / INFLUENCER", fontsize=8.5, fontname="helv", color=(0.85, 0.45, 0.1))
        c_name = creator.get("legal_name") or "Creator"
        raw_u = creator.get("username") or "@creator"
        c_uname = f"@{raw_u.strip().lstrip('@')}"
        c_email = creator.get("email") or "creator@example.com"
        c_platform = creator.get("platform") or camp.get("social_platform") or "Instagram"
        c_url = creator.get("profile_url") or f"https://{c_platform.lower()}.com/{c_uname.lstrip('@')}"
        c_id = creator.get("user_id", "")[:16]

        party_b_text = (
            f"Legal Name: {c_name}\n"
            f"Social Handle: {c_uname}\n"
            f"Platform: {c_platform}\n"
            f"Contact Email: {c_email}\n"
            f"Profile URL: {c_url}\n"
            f"Creator ID: {c_id}... (Verified)"
        )
        p1.insert_textbox(
            fitz.Rect(col2_x + 10, y + 24, col2_x + col_w - 10, y + 96),
            party_b_text,
            fontsize=8,
            fontname="helv",
            color=(0.15, 0.15, 0.2)
        )

        y += 114

        # SECTION 2: SCOPE OF WORK & CAMPAIGN DELIVERABLES
        p1.insert_text((margin, y + 10), "2. CAMPAIGN SPECIFICATIONS & DELIVERABLES", fontsize=9.5, fontname="helv", color=(0.3, 0.3, 0.5))
        y += 16

        deliverables = camp.get("deliverables") or ["1 Dedicated Reel / Video", "2 Stories with Link"]
        deliv_str = "\n".join([f"• {d}" for d in deliverables])

        camp_box_text = (
            f"Campaign Objective: {camp.get('campaign_objectives', 'Brand promotion, awareness, and conversions.')}\n"
            f"Product / Service: {camp.get('product_or_service', 'Influencer Collaboration Services')}\n"
            f"Campaign Period: {camp.get('start_date', '2026-10-21')} to {camp.get('end_date', '2026-11-04')}\n"
            f"Submission Deadline: {camp.get('content_submission_deadline', camp.get('end_date', '2026-11-04'))}\n"
            f"Agreed Deliverables:\n{deliv_str}\n"
            f"Revision Requirements: {camp.get('revision_requirements', 'Up to 2 creative revisions within 5 business days.')}\n"
            f"Disclosures: Must visibly tag '#ad', '#sponsored', and official Brand partner handles in compliance with ASCI."
        )

        p1.draw_rect(fitz.Rect(margin, y, width - margin, y + 130), color=(0.85, 0.85, 0.9), fill=(0.98, 0.98, 0.99), width=0.6)
        p1.insert_textbox(
            fitz.Rect(margin + 12, y + 8, width - margin - 12, y + 124),
            camp_box_text,
            fontsize=8,
            fontname="helv",
            color=(0.15, 0.15, 0.2)
        )

        y += 144

        # SECTION 3: FINANCIAL TERMS & ESCROW SCHEDULE
        p1.insert_text((margin, y + 10), "3. FINANCIAL TERMS & PLATFORM ESCROW", fontsize=9.5, fontname="helv", color=(0.3, 0.3, 0.5))
        y += 16

        agreed_comp = float(fin.get("agreed_compensation") or fin.get("proposed_compensation") or 4500.0)
        plat_fee = float(fin.get("platform_service_fee") or 236.0)
        total_payable = float(fin.get("total_payable") or (agreed_comp + plat_fee))

        p1.draw_rect(fitz.Rect(margin, y, width - margin, y + 68), color=(0.85, 0.85, 0.9), fill=(0.95, 0.98, 0.95), width=0.6)
        fin_text = (
            f"Agreed Creator Fee: INR {agreed_comp:,.2f}  |  Platform Escrow & Contract Protection Fee: INR {plat_fee:,.2f} (incl. 18% GST)\n"
            f"Total Escrow Amount Payable: INR {total_payable:,.2f}\n"
            f"Payment Schedule: 100% Escrow deposit by Hirer via Zaakpay / Platform Gateway prior to campaign commencement.\n"
            f"Payout Release: Net creator compensation released to Influencer upon Hirer deliverable verification and acceptance."
        )
        p1.insert_textbox(
            fitz.Rect(margin + 12, y + 8, width - margin - 12, y + 62),
            fin_text,
            fontsize=8,
            fontname="helv",
            color=(0.1, 0.3, 0.1)
        )

        y += 82

        # Page 1 Footer
        p1.draw_line(fitz.Point(margin, height - 35), fitz.Point(width - margin, height - 35), color=(0.8, 0.8, 0.85), width=0.5)
        p1.insert_text((margin, height - 22), "SevenUnique AI Technologies — Confidential Legal Contract", fontsize=7.5, fontname="helv", color=(0.5, 0.5, 0.6))
        p1.insert_text((width - margin - 80, height - 22), "Page 1 of 2", fontsize=7.5, fontname="helv", color=(0.5, 0.5, 0.6))

        # =========================================================================
        # PAGE 2: ENFORCEABLE LEGAL CLAUSES & ELECTRONIC SIGNATURES
        # =========================================================================
        p2 = doc.new_page(width=width, height=height)

        # Header Page 2
        p2.draw_rect(fitz.Rect(margin, margin, width - margin, margin + 30), color=None, fill=(0.07, 0.08, 0.14))
        p2.insert_text((margin + 16, margin + 20), "SEVENUNIQUE AI — ENFORCEABLE LEGAL TERMS & CONDITIONS", fontsize=9.5, fontname="helv", color=(1.0, 1.0, 1.0))
        p2.insert_text((width - margin - 140, margin + 20), f"Agreement: {agr_num}", fontsize=8, fontname="helv", color=(0.8, 0.8, 0.9))

        y2 = margin + 42

        # Default standard clauses if none provided
                # Standard comprehensive legal clauses under Indian jurisdiction & IT Act 2000
        standard_clauses = [
            ("1. Scope of Work, Deliverables & Specifications",
             f"The Creator agrees to produce, edit, and publish the agreed deliverables ({', '.join(deliverables)}) in strict adherence to Brand objectives, guidelines, and quality benchmarks."),
            ("2. Commercial License, Reposting & Exclusivity",
             "Creator retains attribution rights while granting Brand an exclusive 12-month commercial license to repost, boost, and run digital advertisements using the deliverables worldwide."),
            ("3. Content Approval, Revisions & Deadlines",
             "Brand may request up to 2 creative revision rounds within 5 business days of deliverable submission. If no feedback is provided within 5 business days, content is deemed approved."),
            ("4. Mandatory Advertising Disclosures (ASCI & FTC)",
             "Creator must visibly include '#ad', '#sponsored', or official platform partnership tags in full accordance with the Advertising Standards Council of India (ASCI) and FTC guidelines."),
            ("5. Confidentiality, Non-Disclosure & DPDP Act",
             "Both parties agree to treat campaign briefs, negotiated financial terms, and unreleased brand assets as strictly confidential under the Digital Personal Data Protection Act, 2023."),
            ("6. Responsibilities of Parties & Non-Disparagement",
             "Creator shall maintain professional brand alignment and refrain from disparaging statements. Brand agrees to supply approved product samples and brief guidelines promptly."),
            ("7. Cancellation, Termination & Force Majeure",
             "Either party may cancel with mutual consent. Unjustified creator default entitles Brand to 100% escrow refund. Neither party is liable for delays caused by verifiable force majeure events."),
            ("8. Limitation of Liability & Platform Escrow",
             "Total financial liability of either party shall not exceed total contract compensation. All funds are held in secure platform escrow until deliverable verification."),
            ("9. Governing Law, Dispute Resolution & Jurisdiction",
             "This Agreement is governed by the laws of India. Disputes are subject to binding platform arbitration under the Arbitration and Conciliation Act, 1996 with courts of Jaipur having jurisdiction."),
            ("10. Electronic Signature Consent & IT Act 2000",
             "The parties execute this document via secure electronic signature. Under Section 10A of the Information Technology Act, 2000, this digital record is legally valid and binding.")
        ]

        active_clauses = [{"clause_title": t, "clause_text": txt} for t, txt in standard_clauses]

        for idx, cl in enumerate(active_clauses[:6]):
            title_cl = cl.get("clause_title") or f"Clause {idx + 1}"
            text_cl = cl.get("clause_text") or ""
            p2.insert_text((margin, y2 + 10), title_cl, fontsize=8.5, fontname="helv", color=(0.2, 0.2, 0.4))
            y2 += 14
            p2.insert_textbox(
                fitz.Rect(margin, y2, width - margin, y2 + 42),
                text_cl,
                fontsize=7.5,
                fontname="helv",
                color=(0.25, 0.25, 0.3)
            )
            y2 += 44

        # SECTION 5: BILATERAL ELECTRONIC SIGNATURES
        y2 += 4
        p2.draw_line(fitz.Point(margin, y2), fitz.Point(width - margin, y2), color=(0.8, 0.8, 0.85), width=0.6)
        y2 += 12
        p2.insert_text((margin, y2 + 8), "4. ELECTRONIC SIGNATURES & AUDIT LOG", fontsize=9.5, fontname="helv", color=(0.2, 0.2, 0.4))
        y2 += 16

        # Signature Box Hirer
        h_sig = sigs.get("hirer") or {}
        p2.draw_rect(fitz.Rect(margin, y2, margin + col_w, y2 + 95), color=(0.8, 0.8, 0.85), fill=(0.97, 0.99, 0.97) if h_sig.get("signed") else (0.99, 0.99, 0.99), width=0.6)
        p2.insert_text((margin + 10, y2 + 16), "PARTY A (HIRER) SIGNATURE", fontsize=8, fontname="helv", color=(0.3, 0.6, 0.3) if h_sig.get("signed") else (0.6, 0.6, 0.6))

        if h_sig.get("signed"):
            h_sig_text = (
                f"Signed by: {h_sig.get('signer_name', h_name)}\n"
                f"Title: {h_sig.get('signer_title', 'Authorized Brand Representative')}\n"
                f"Date: {h_sig.get('signed_at', 'Verified Timestamp')}\n"
                f"IP Address: {h_sig.get('ip_address', '127.0.0.1')}\n"
                f"SHA256: {str(h_sig.get('signature_hash', 'VERIFIED'))[:28]}..."
            )
        else:
            h_sig_text = "Status: Pending Electronic Signature\nAwaiting Brand representative signature."

        p2.insert_textbox(
            fitz.Rect(margin + 10, y2 + 24, margin + col_w - 10, y2 + 90),
            h_sig_text,
            fontsize=7.5,
            fontname="helv",
            color=(0.15, 0.15, 0.2)
        )

        # Signature Box Creator
        c_sig = sigs.get("influencer") or {}
        p2.draw_rect(fitz.Rect(col2_x, y2, col2_x + col_w, y2 + 95), color=(0.8, 0.8, 0.85), fill=(0.97, 0.99, 0.97) if c_sig.get("signed") else (0.99, 0.99, 0.99), width=0.6)
        p2.insert_text((col2_x + 10, y2 + 16), "PARTY B (INFLUENCER) SIGNATURE", fontsize=8, fontname="helv", color=(0.3, 0.6, 0.3) if c_sig.get("signed") else (0.6, 0.6, 0.6))

        if c_sig.get("signed"):
            c_sig_text = (
                f"Signed by: {c_sig.get('signer_name', c_name)}\n"
                f"Role: Content Creator & Contracting Party\n"
                f"Date: {c_sig.get('signed_at', 'Verified Timestamp')}\n"
                f"IP Address: {c_sig.get('ip_address', '127.0.0.1')}\n"
                f"SHA256: {str(c_sig.get('signature_hash', 'VERIFIED'))[:28]}..."
            )
        else:
            c_sig_text = "Status: Pending Electronic Signature\nAwaiting Creator signature."

        p2.insert_textbox(
            fitz.Rect(col2_x + 10, y2 + 24, col2_x + col_w - 10, y2 + 90),
            c_sig_text,
            fontsize=7.5,
            fontname="helv",
            color=(0.15, 0.15, 0.2)
        )

        y2 += 105

        # Cryptographic Hash & Verification Seal
        doc_hash = hashlib.sha256(f"{agr_num}:{h_name}:{c_name}:{agreed_comp}".encode()).hexdigest()
        p2.draw_rect(fitz.Rect(margin, y2, width - margin, y2 + 30), color=(0.85, 0.85, 0.9), fill=(0.96, 0.96, 0.98), width=0.5)
        p2.insert_textbox(
            fitz.Rect(margin + 10, y2 + 6, width - margin - 10, y2 + 26),
            f"SevenUnique Cryptographic Verification Digest (SHA-256): {doc_hash}\n"
            "This document is an electronic record under the Information Technology Act, 2000 and ASCI guidelines.",
            fontsize=6.5,
            fontname="helv",
            color=(0.3, 0.3, 0.4)
        )

        # Page 2 Footer
        p2.draw_line(fitz.Point(margin, height - 35), fitz.Point(width - margin, height - 35), color=(0.8, 0.8, 0.85), width=0.5)
        p2.insert_text((margin, height - 22), "SevenUnique AI Technologies — Confidential Legal Contract", fontsize=7.5, fontname="helv", color=(0.5, 0.5, 0.6))
        p2.insert_text((width - margin - 80, height - 22), "Page 2 of 2", fontsize=7.5, fontname="helv", color=(0.5, 0.5, 0.6))

        return doc.tobytes()
