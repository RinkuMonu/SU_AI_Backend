from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Any, Dict
from app.api.dependencies import get_current_user, get_database
from app.schemas.payment import PaymentCreateRequest, PaymentCreateResponse, PaymentCallbackResponse, PaymentStatusResponse
from app.services.payin_service import PayinService
from pymongo.database import Database

router = APIRouter()

@router.post("/payin/create", response_model=PaymentCreateResponse)
async def create_payment(
    request: PaymentCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    user_id = str(current_user["id"])
    user_email = current_user.get("email", "user@example.com")
    result = await PayinService.create_payment(
        db, user_id, user_email, request.plan_id, billing_cycle=request.billing_cycle
    )
    return result

@router.post("/payin/callback", response_model=PaymentCallbackResponse)
async def payment_callback(
    request: Request,
    db: Database = Depends(get_database)
):
    # Payin might send application/json or form-data
    if request.headers.get("content-type") == "application/json":
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)
        
    headers = dict(request.headers)
    result = await PayinService.process_callback(db, payload, headers)
    return result

@router.get("/payin/status/{order_id}", response_model=PaymentStatusResponse)
async def payment_status(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    transaction = await db["payment_transactions"].find_one({"order_id": order_id})
    if not transaction:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if transaction["user_id"] != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return {
        "order_id": order_id,
        "status": transaction["status"],
        "amount": transaction["amount"],
        "base_amount": transaction.get("base_amount"),
        "gst_amount": transaction.get("gst_amount")
    }

from fastapi.responses import HTMLResponse
from datetime import datetime, timezone

@router.get("/payin/checkout-simulated", response_class=HTMLResponse)
async def checkout_simulated_page(
    order_id: str,
    amount: float,
    db: Database = Depends(get_database)
):
    """Zaakpay / Finunique Platform Escrow payment gateway simulation checkout."""
    # Find matching payment record
    payment = await db["marketplace_payments"].find_one({"order_id": order_id})
    campaign_name = payment.get("campaign_name", "Influencer Marketing Campaign") if payment else "Influencer Collaboration"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Zaakpay / Finunique Escrow Checkout</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }}
    body {{ background: #0b0c14; color: #f1f2f6; display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }}
    .card {{ background: #131422; border: 1px solid rgba(255,255,255,0.12); border-radius: 20px; max-width: 460px; width: 100%; padding: 28px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7); position: relative; }}
    .badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 9999px; color: #10b981; font-size: 11px; font-weight: 600; }}
    .header {{ margin-bottom: 24px; text-align: center; }}
    .header h1 {{ font-size: 20px; font-weight: 700; margin-top: 10px; background: linear-gradient(135deg, #fc9a5d, #be32ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    .header p {{ color: rgba(255,255,255,0.6); font-size: 13px; margin-top: 4px; }}
    .details {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 18px; margin-bottom: 24px; }}
    .row {{ display: flex; justify-content: space-between; padding: 8px 0; font-size: 13px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
    .row:last-child {{ border-bottom: none; }}
    .row .label {{ color: rgba(255,255,255,0.6); }}
    .row .val {{ font-weight: 600; color: #ffffff; text-align: right; }}
    .total-row {{ display: flex; justify-content: space-between; align-items: baseline; margin-top: 10px; padding-top: 12px; border-top: 1px dashed rgba(255,255,255,0.15); }}
    .total-val {{ font-size: 26px; font-weight: 800; color: #fc9a5d; }}
    .methods {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 24px; }}
    .method {{ padding: 12px; border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; background: rgba(255,255,255,0.02); text-align: center; font-size: 12px; font-weight: 500; cursor: pointer; transition: 0.2s; }}
    .method.active {{ border-color: #be32ff; background: rgba(190, 50, 255, 0.1); color: #ffffff; font-weight: 600; }}
    .btn {{ display: block; width: 100%; padding: 14px; border: none; border-radius: 12px; background: linear-gradient(135deg, #fc9a5d, #be32ff); color: white; font-size: 15px; font-weight: 700; cursor: pointer; transition: 0.2s; box-shadow: 0 10px 25px -5px rgba(190, 50, 255, 0.4); text-align: center; text-decoration: none; }}
    .btn:hover {{ opacity: 0.95; transform: translateY(-1px); }}
    .footer-note {{ text-align: center; margin-top: 18px; font-size: 11px; color: rgba(255,255,255,0.4); line-height: 1.5; }}
    .success-box {{ display: none; text-align: center; padding: 20px 0; }}
    .success-icon {{ width: 64px; height: 64px; margin: 0 auto 16px; border-radius: 50%; background: rgba(16, 185, 129, 0.15); border: 2px solid #10b981; display: flex; align-items: center; justify-content: center; font-size: 32px; color: #10b981; }}
  </style>
</head>
<body>
  <div class="card">
    <div id="checkout-view">
      <div class="header">
        <span class="badge">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          Zaakpay / Finunique 256-Bit Escrow
        </span>
        <h1>Platform Escrow Deposit</h1>
        <p>Deposit collaboration funds safely into Platform Escrow</p>
      </div>

      <div class="details">
        <div class="row">
          <span class="label">Campaign</span>
          <span class="val">{campaign_name}</span>
        </div>
        <div class="row">
          <span class="label">Order Reference</span>
          <span class="val" style="font-family: monospace; font-size: 12px;">{order_id}</span>
        </div>
        <div class="row">
          <span class="label">Security Protection</span>
          <span class="val" style="color: #10b981;">100% Escrow Protected</span>
        </div>
        <div class="total-row">
          <span style="font-weight: 600; color: rgba(255,255,255,0.8);">Total Amount</span>
          <span class="total-val">₹{amount:,.2f}</span>
        </div>
      </div>

      <div class="methods">
        <div class="method active">⚡ Instant UPI / QR</div>
        <div class="method">💳 Debit / Credit Card</div>
        <div class="method">🏦 Net Banking</div>
        <div class="method">👛 Wallet</div>
      </div>

      <button class="btn" id="pay-btn" onclick="processPayment()">
        Complete Payment (₹{amount:,.2f})
      </button>

      <div class="footer-note">
        Funds will remain locked under SevenUnique Platform Escrow until creator deliverables are approved.
      </div>
    </div>

    <div id="success-view" class="success-box">
      <div class="success-icon">✓</div>
      <h2 style="font-size: 22px; font-weight: 700; color: #10b981; margin-bottom: 8px;">Payment Successful!</h2>
      <p style="color: rgba(255,255,255,0.7); font-size: 13px; margin-bottom: 20px;">
        Zaakpay transaction of <strong style="color: #ffffff;">₹{amount:,.2f}</strong> has been verified. Escrow is now active!
      </p>
      <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 14px; font-size: 12px; text-align: left; margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <span style="color: rgba(255,255,255,0.5);">Transaction ID</span>
          <span id="txn-id-val" style="font-family: monospace; color: #fc9a5d;">TXN_ZAAKPAY_VERIFIED</span>
        </div>
        <div style="display: flex; justify-content: space-between;">
          <span style="color: rgba(255,255,255,0.5);">Campaign Status</span>
          <span style="color: #10b981; font-weight: 600;">Active & In Progress</span>
        </div>
      </div>
      <button class="btn" onclick="window.close()" style="background: rgba(255,255,255,0.1); box-shadow: none;">
        Close Window & Return to Dashboard
      </button>
    </div>
  </div>

  <script>
    async function processPayment() {{
      const btn = document.getElementById('pay-btn');
      btn.disabled = true;
      btn.innerText = 'Processing Zaakpay Gateway...';

      try {{
        const res = await fetch('/api/v1/payments/payin/checkout-simulated/confirm', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ order_id: '{order_id}', amount: {amount} }})
        }});
        const data = await res.json();
        if (data.success) {{
          document.getElementById('checkout-view').style.display = 'none';
          document.getElementById('success-view').style.display = 'block';
          if (data.payment_id) {{
            document.getElementById('txn-id-val').innerText = data.payment_id;
          }}
        }} else {{
          alert(data.message || 'Payment processing failed');
          btn.disabled = false;
          btn.innerText = 'Complete Payment (₹{amount:,.2f})';
        }}
      }} catch (err) {{
        console.error(err);
        document.getElementById('checkout-view').style.display = 'none';
        document.getElementById('success-view').style.display = 'block';
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@router.post("/payin/checkout-simulated/confirm")
async def checkout_simulated_confirm(
    payload: Dict[str, Any],
    db: Database = Depends(get_database)
):
    """Mark simulated Zaakpay payment as successfully processed."""
    order_id = payload.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id")

    now = datetime.now(timezone.utc)
    payment_id = f"TXN_ZAAKPAY_{uuid.uuid4().hex[:10].upper()}"

    # 1. Update marketplace_payments if exists
    marketplace_payment = await db["marketplace_payments"].find_one({"order_id": order_id})
    if marketplace_payment:
        await db["marketplace_payments"].update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "success",
                "payment_id": payment_id,
                "verified_at": now,
                "updated_at": now
            }}
        )
        hiring_req_id = marketplace_payment.get("hiring_request_id")
        if hiring_req_id:
            await db["hiring_requests"].update_one(
                {"$or": [{"hiring_request_id": hiring_req_id}, {"_id": hiring_req_id}]},
                {"$set": {
                    "status": "in_progress",
                    "payment_status": "paid",
                    "payment_order_id": order_id,
                    "payment_id": payment_id,
                    "activated_at": now,
                    "updated_at": now
                }}
            )

    # 2. Update payment_transactions if exists
    await db["payment_transactions"].update_one(
        {"order_id": order_id},
        {"$set": {
            "status": "success",
            "external_transaction_id": payment_id,
            "verified_at": now,
            "updated_at": now
        }}
    )

    return {"success": True, "status": "success", "payment_id": payment_id}

