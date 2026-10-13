from fastapi import APIRouter, Depends, status, Request, Response, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from app.schemas.auth import (
    SignupRequest,
    SendOTPRequest,
    VerifyOTPRequest,
    LoginRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    FacebookAuthLoginRequest,
)
from app.services.facebook_service import FacebookService
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService
from app.core.config import settings
from app.core.database import get_database
from app.core.security import get_current_user, CurrentUser
from bson import ObjectId
from pydantic import EmailStr
import jwt

router = APIRouter()

def set_refresh_cookie(response: Response, refresh_token: str):
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax" if settings.ENVIRONMENT == "development" else "none",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )

@router.post("/send-otp")
@router.post("/resend-otp")
async def send_otp(req: SendOTPRequest):
    """Send 6-digit verification code to user's email via SMTP."""
    return await AuthService.send_otp(req.email, req.name)

@router.post("/verify-otp")
async def verify_otp(req: VerifyOTPRequest):
    """Verify 6-digit email OTP code."""
    return await AuthService.verify_otp(req.email, req.otp)

@router.post(
    "/signup",
    summary="Register New User Account",
    description="Registers a new user account with first name, last name, contact number, email, password, and optional email verification OTP."
)
async def signup(req: SignupRequest, response: Response):
    user, access_token, refresh_token = await AuthService.signup(req)
    set_refresh_cookie(response, refresh_token)
    msg = "User registered successfully." if user.emailVerified else "User registered successfully. A verification link has also been sent to your email inbox."
    user_dict = {
        "id": str(user.id),
        "fullName": user.fullName or getattr(user, "name", None) or "User",
        "name": user.fullName or getattr(user, "name", None) or "User",
        "firstName": user.firstName,
        "lastName": user.lastName,
        "email": user.email,
        "phone": user.phone or user.contactNumber,
        "contactNumber": user.contactNumber or user.phone,
        "accountType": user.accountType,
        "role": getattr(user, "role", "user") or "user",
        "emailVerified": bool(user.emailVerified),
        "email_verified": bool(user.emailVerified),
        "isVerified": bool(user.emailVerified)
    }
    return {
        "success": True,
        "message": msg,
        "access_token": access_token,
        "accessToken": access_token,
        "token": access_token,
        "user": user_dict,
        "data": {
            "access_token": access_token,
            "accessToken": access_token,
            "token": access_token,
            "user": user_dict
        }
    }


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    user, access_token, refresh_token = await AuthService.login(req)
    set_refresh_cookie(response, refresh_token)
    user_dict = {
        "id": str(user.id),
        "fullName": user.fullName or getattr(user, "name", None) or "User",
        "name": user.fullName or getattr(user, "name", None) or "User",
        "firstName": user.firstName,
        "lastName": user.lastName,
        "email": user.email,
        "phone": user.phone or user.contactNumber,
        "contactNumber": user.contactNumber or user.phone,
        "accountType": user.accountType,
        "role": getattr(user, "role", "user") or "user",
        "emailVerified": bool(user.emailVerified),
        "email_verified": bool(user.emailVerified),
        "isVerified": bool(user.emailVerified)
    }
    return {
        "success": True,
        "message": "Logged in successfully",
        "access_token": access_token,
        "accessToken": access_token,
        "token": access_token,
        "user": user_dict,
        "data": {
            "access_token": access_token,
            "accessToken": access_token,
            "token": access_token,
            "user": user_dict
        }
    }

@router.post("/facebook/login")
async def facebook_login(req: FacebookAuthLoginRequest, response: Response):
    """
    Authenticate or sign up user using Facebook Login.
    Accepts either an access_token from the Facebook SDK / OAuth flow or an authorization code.
    Returns standard access token, refresh token cookie, and user profile data.
    """
    db = get_database()
    access_token = req.access_token

    if not access_token and req.code:
        token_data = await FacebookService.exchange_code_for_token(req.code)
        access_token = token_data.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide either 'access_token' or 'code'."
        )

    user, access_token_jwt, refresh_token_jwt = await FacebookService.authenticate_facebook_user(
        db=db,
        access_token=access_token,
        account_type=req.accountType or "business",
    )
    set_refresh_cookie(response, refresh_token_jwt)

    user_payload = {
        "id": str(user.id),
        "fullName": user.fullName,
        "firstName": user.firstName,
        "lastName": user.lastName,
        "email": user.email,
        "phone": user.phone,
        "contactNumber": user.contactNumber,
        "accountType": user.accountType,
        "role": getattr(user, "role", "user") or "user",
        "name": getattr(user, "name", user.fullName) or user.fullName,
        "emailVerified": bool(user.emailVerified),
        "email_verified": bool(user.emailVerified),
        "isVerified": bool(user.emailVerified),
        "profileImageUrl": user.profileImageUrl,
    }

    return {
        "success": True,
        "message": "Facebook login successful",
        "access_token": access_token_jwt,
        "accessToken": access_token_jwt,
        "token": access_token_jwt,
        "user": user_payload,
        "data": {
            "access_token": access_token_jwt,
            "accessToken": access_token_jwt,
            "token": access_token_jwt,
            "user": user_payload
        }
    }

@router.get("/me")
async def get_auth_me(current_user=Depends(get_current_user)):
    db = get_database()
    user_id = current_user.get("id") or current_user.get("_id")
    doc = None
    try:
        doc = await db["users"].find_one({"_id": ObjectId(str(user_id))})
    except Exception:
        pass
    if not doc and current_user.get("email"):
        doc = await db["users"].find_one({"email": current_user.get("email")})
        
    res = dict(doc or current_user)
    res["id"] = str(res.get("_id", user_id))
    if "_id" in res:
        del res["_id"]
    if "hashed_password" in res:
        del res["hashed_password"]
    if not res.get("role"):
        res["role"] = "user"
    if not res.get("fullName") and res.get("name"):
        res["fullName"] = res["name"]
    if not res.get("name") and res.get("fullName"):
        res["name"] = res["fullName"]
    res["email_verified"] = res.get("email_verified", res.get("emailVerified", True))
    return res

@router.post("/logout")
async def logout(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await AuthService.logout(refresh_token)
    response.delete_cookie("refresh_token")
    return {"success": True, "message": "Logged out successfully"}

@router.post("/refresh")
async def refresh(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return {"success": False, "message": "No refresh token"}
    
    access_token, new_refresh_token = await AuthService.refresh(refresh_token)
    set_refresh_cookie(response, new_refresh_token)
    return {
        "success": True,
        "message": "Token refreshed",
        "data": {"accessToken": access_token}
    }

@router.get("/me")
async def get_current_user_profile(current_user: CurrentUser = Depends(get_current_user)):
    """
    Fetch current authenticated user profile.
    Compatible with both User direct format and standard APIResponse envelope.
    """
    db = get_database()
    doc = await db["users"].find_one({"_id": ObjectId(current_user["id"])})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = str(doc["_id"])
    full_name = doc.get("fullName") or doc.get("name") or "User"
    email_ver = bool(doc.get("emailVerified", doc.get("email_verified", True)))

    user_dict = {
        "id": user_id,
        "_id": user_id,
        "fullName": full_name,
        "name": full_name,
        "firstName": doc.get("firstName") or full_name.split()[0],
        "lastName": doc.get("lastName") or (" ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else None),
        "email": doc.get("email"),
        "phone": doc.get("phone") or doc.get("contactNumber"),
        "contactNumber": doc.get("contactNumber") or doc.get("phone"),
        "accountType": doc.get("accountType", "business"),
        "role": doc.get("role", "user") or "user",
        "emailVerified": email_ver,
        "email_verified": email_ver,
        "isVerified": email_ver,
        "profileImageUrl": doc.get("profileImageUrl"),
        "preferredLanguage": doc.get("preferredLanguage"),
        "onboardingCompleted": doc.get("onboardingCompleted", False),
        "onboarding_step": doc.get("onboarding_step", 1),
    }

    # Return top-level fields AND data envelope for dual compatibility
    response_payload = {
        **user_dict,
        "success": True,
        "data": user_dict,
    }
    return response_payload

@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email_get(request: Request, token: str = Query(None), link: str = Query(None)):
    """Handle direct clicks from verification email link in browser. Accepts either ?token=... or ?link=..."""
    accept_header = request.headers.get("accept", "")
    format_param = request.query_params.get("format", "")
    is_json = "application/json" in accept_header or format_param == "json"

    token_or_link = link or token or request.query_params.get("token") or request.query_params.get("link")
    if not token_or_link:
        if is_json:
            return JSONResponse(status_code=400, content={"success": False, "detail": "Missing verification link or token."})
        return HTMLResponse(status_code=400, content="""<!DOCTYPE html><html><body style="font-family: sans-serif; text-align: center; padding: 40px; background: #0f172a; color: white;"><h2>Verification Link Required</h2><p>Please click the full verification link sent to your email.</p></body></html>""")

    try:
        res = await AuthService.verify_email(token_or_link)
        if is_json:
            return JSONResponse({
                "success": True,
                "message": "Email verified successfully" if not res.get("alreadyVerified") else "Email is already verified",
                "data": res
            })

        email = res.get("email", "")
        already = res.get("alreadyVerified", False)
        status_text = "Already Verified" if already else "Email Successfully Verified!"
        msg_text = (
            f"Your email address <strong>{email}</strong> is already verified with your Dhanda Grow account."
            if already else
            f"Your email address <strong>{email}</strong> has been successfully verified. Welcome to <strong>Dhanda Grow</strong>!"
        )

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Email Verification - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f172a;
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      padding: 44px 36px 36px 36px;
      border-radius: 22px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
      overflow: hidden;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 5px;
      background: linear-gradient(90deg, #20167c 0%, #4338ca 50%, #f97316 100%);
    }}
    .logo {{
      max-width: 230px;
      width: 100%;
      height: auto;
      margin: 0 auto 28px auto;
      display: block;
      filter: drop-shadow(0 4px 10px rgba(0,0,0,0.3));
    }}
    .badge {{
      width: 68px;
      height: 68px;
      background: rgba(34, 197, 94, 0.15);
      border: 2px solid #22c55e;
      color: #22c55e;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 34px;
      margin: 0 auto 20px auto;
    }}
    h1 {{
      font-size: 23px;
      font-weight: 700;
      margin-bottom: 12px;
      color: #ffffff;
      letter-spacing: -0.3px;
    }}
    p {{
      color: #94a3b8;
      font-size: 15px;
      line-height: 1.6;
      margin-bottom: 30px;
    }}
    p strong {{
      color: #f1f5f9;
    }}
    .btn {{
      display: inline-block;
      background: linear-gradient(135deg, #20167c 0%, #4338ca 50%, #f97316 100%);
      color: #ffffff;
      text-decoration: none;
      padding: 14px 34px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 15px;
      transition: transform 0.2s, box-shadow 0.2s;
      box-shadow: 0 6px 20px rgba(249, 115, 22, 0.3);
      letter-spacing: 0.3px;
    }}
    .btn:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(249, 115, 22, 0.4);
    }}
    .footer {{
      margin-top: 28px;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #334155;
      padding-top: 18px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    <div class="badge">✓</div>
    <h1>{status_text}</h1>
    <p>{msg_text}</p>
    <a href="{settings.FRONTEND_URL}/login" class="btn">Proceed to Login</a>
    <div class="footer">Dhanda Grow AI • Apne Business Ko Banao Smart &amp; Digital</div>
  </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)

    except HTTPException as e:
        if is_json:
            return JSONResponse(status_code=e.status_code, content={"success": False, "detail": e.detail})

        error_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verification Error - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f172a;
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #ef4444;
      padding: 44px 36px 36px 36px;
      border-radius: 22px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
      overflow: hidden;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 5px;
      background: #ef4444;
    }}
    .logo {{
      max-width: 230px;
      width: 100%;
      height: auto;
      margin: 0 auto 28px auto;
      display: block;
    }}
    .badge {{
      width: 68px;
      height: 68px;
      background: rgba(239, 68, 68, 0.15);
      border: 2px solid #ef4444;
      color: #ef4444;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 34px;
      margin: 0 auto 20px auto;
    }}
    h1 {{
      font-size: 23px;
      font-weight: 700;
      margin-bottom: 12px;
      color: #ffffff;
    }}
    p {{
      color: #94a3b8;
      font-size: 15px;
      line-height: 1.6;
      margin-bottom: 30px;
    }}
    .btn {{
      display: inline-block;
      background: #334155;
      color: #ffffff;
      text-decoration: none;
      padding: 14px 32px;
      border-radius: 12px;
      font-weight: 600;
      font-size: 15px;
      transition: background 0.2s;
    }}
    .btn:hover {{
      background: #475569;
    }}
    .footer {{
      margin-top: 28px;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #334155;
      padding-top: 18px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    <div class="badge">✕</div>
    <h1>Verification Failed</h1>
    <p>{e.detail}</p>
    <a href="{settings.FRONTEND_URL}/login" class="btn">Return to Dhanda Grow</a>
    <div class="footer">Dhanda Grow AI • Apne Business Ko Banao Smart &amp; Digital</div>
  </div>
</body>
</html>"""
        return HTMLResponse(status_code=e.status_code, content=error_html)

@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest):
    """API endpoint to verify email. Accepts either 'link' (full link from email) or 'token'."""
    token_or_link = req.link or req.token
    if not token_or_link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide either 'link' (full verification link from email) or 'token'."
        )
    res = await AuthService.verify_email(token_or_link)
    return {
        "success": True,
        "message": "Email verified successfully" if not res.get("alreadyVerified") else "Email is already verified",
        "data": {
            "email": res["email"],
            "emailVerified": True,
            "isVerified": True
        }
    }

@router.post("/resend-verification")
@router.post("/send-verification")
async def resend_verification(req: ResendVerificationRequest):
    """Send/Resend verification link directly to user's Gmail inbox via SMTP."""
    res = await AuthService.resend_verification(req.email, force=bool(req.force))
    is_already = res.get("alreadyVerified", False)
    return {
        "success": True,
        "message": "Email is already verified." if is_already else "Verification link has been sent to your Gmail inbox. Please check your email and tap the link to verify.",
        "data": {
            "email": req.email,
            "emailSent": not is_already,
            "emailVerified": is_already,
            "isVerified": is_already
        }
    }

@router.get("/verification-status")
async def get_verification_status(email: EmailStr = Query(...)):
    """Check if an email is verified or not (returns boolean true/false)."""
    db = get_database()
    clean_email = email.lower().strip()
    user = await db["users"].find_one({"email": clean_email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    is_verified = bool(user.get("emailVerified", False))
    return {
        "success": True,
        "email": clean_email,
        "emailVerified": is_verified,
        "isVerified": is_verified
    }

@router.post("/verification-status")
async def post_verification_status(req: ResendVerificationRequest):
    """Check if an email is verified or not via JSON body (returns boolean true/false)."""
    db = get_database()
    clean_email = req.email.lower().strip()
    user = await db["users"].find_one({"email": clean_email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    is_verified = bool(user.get("emailVerified", False))
    return {
        "success": True,
        "email": clean_email,
        "emailVerified": is_verified,
        "isVerified": is_verified
    }


@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """Send real password reset email via SMTP with Dhanda Grow branding."""
    res = await AuthService.forgot_password(req.email)
    return res

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(request: Request, token: str = Query(None), link: str = Query(None)):
    """Handle direct clicks on reset password link in browser. Accepts either ?token=... or ?link=..."""
    raw_val = link or token or request.query_params.get("token") or request.query_params.get("link")
    clean_token = AuthService.extract_token(raw_val)


    # Pre-validate token
    token_valid = True
    user_email = ""
    error_detail = ""

    try:
        payload = jwt.decode(clean_token, settings.JWT_ACCESS_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_email = payload.get("email", "")
    except jwt.ExpiredSignatureError:
        token_valid = False
        error_detail = "This password reset link has expired. Please request a new one."
    except jwt.InvalidTokenError:
        token_valid = False
        error_detail = "This password reset link is invalid or corrupted."

    if not token_valid:
        error_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Password Expired - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #ef4444;
      padding: 44px 36px;
      border-radius: 22px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0; height: 5px;
      background: #ef4444;
    }}
    .logo {{ max-width: 230px; width: 100%; margin: 0 auto 26px auto; display: block; }}
    .badge {{
      width: 68px; height: 68px;
      background: rgba(239, 68, 68, 0.15);
      border: 2px solid #ef4444;
      color: #ef4444;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 34px; margin: 0 auto 20px auto;
    }}
    h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 12px; color: #ffffff; }}
    p {{ color: #94a3b8; font-size: 15px; line-height: 1.6; margin-bottom: 28px; }}
    .btn {{
      display: inline-block;
      background: #334155; color: #ffffff;
      text-decoration: none; padding: 13px 30px;
      border-radius: 12px; font-weight: 600; font-size: 14px;
    }}
    .footer {{ margin-top: 26px; font-size: 12px; color: #64748b; border-top: 1px solid #334155; padding-top: 18px; }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    <div class="badge">✕</div>
    <h1>Link Expired or Invalid</h1>
    <p>{error_detail}</p>
    <a href="{settings.FRONTEND_URL}/login" class="btn">Return to Dhanda Grow</a>
    <div class="footer">Dhanda Grow AI • Apne Business Ko Banao Smart &amp; Digital</div>
  </div>
</body>
</html>"""
        return HTMLResponse(status_code=400, content=error_html)

    form_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Password - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      padding: 40px 36px;
      border-radius: 22px;
      max-width: 460px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
      overflow: hidden;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0; height: 5px;
      background: linear-gradient(90deg, #20167c 0%, #4338ca 50%, #f97316 100%);
    }}
    .logo {{
      max-width: 220px;
      width: 100%;
      height: auto;
      margin: 0 auto 22px auto;
      display: block;
      filter: drop-shadow(0 4px 10px rgba(0,0,0,0.3));
    }}
    h1 {{
      font-size: 22px;
      font-weight: 700;
      margin-bottom: 8px;
      color: #ffffff;
      letter-spacing: -0.3px;
    }}
    .subtitle {{
      color: #94a3b8;
      font-size: 14px;
      line-height: 1.5;
      margin-bottom: 26px;
    }}
    .form-group {{
      text-align: left;
      margin-bottom: 18px;
    }}
    label {{
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
    }}
    input {{
      width: 100%;
      padding: 13px 16px;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 10px;
      color: #f8fafc;
      font-size: 15px;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    input:focus {{
      border-color: #6366f1;
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
    }}
    .error-msg {{
      color: #f87171;
      font-size: 13px;
      margin-bottom: 16px;
      display: none;
      text-align: center;
      background: rgba(239, 68, 68, 0.12);
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid rgba(239, 68, 68, 0.3);
    }}
    .btn {{
      width: 100%;
      margin-top: 8px;
      padding: 14px;
      background: linear-gradient(135deg, #20167c 0%, #4338ca 50%, #f97316 100%);
      color: #ffffff;
      border: none;
      border-radius: 12px;
      font-weight: 700;
      font-size: 15px;
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s;
      box-shadow: 0 6px 20px rgba(249, 115, 22, 0.3);
    }}
    .btn:hover {{
      transform: translateY(-1px);
      box-shadow: 0 8px 24px rgba(249, 115, 22, 0.4);
    }}
    .btn:disabled {{
      opacity: 0.6;
      cursor: not-allowed;
      transform: none;
    }}
    .success-container {{
      display: none;
    }}
    .badge {{
      width: 68px; height: 68px;
      background: rgba(34, 197, 94, 0.15);
      border: 2px solid #22c55e;
      color: #22c55e;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 34px; margin: 0 auto 20px auto;
    }}
    .login-btn {{
      display: inline-block;
      margin-top: 20px;
      background: linear-gradient(135deg, #20167c 0%, #4338ca 50%, #f97316 100%);
      color: #ffffff;
      text-decoration: none;
      padding: 13px 34px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 15px;
    }}
    .footer {{
      margin-top: 26px;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #334155;
      padding-top: 16px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    
    <div id="formSection">
      <h1>Set New Password</h1>
      <p class="subtitle">Enter your new password and confirm it below</p>
      
      <div id="errorBox" class="error-msg"></div>

      <form id="resetForm" onsubmit="handleSubmit(event)">
        <div class="form-group">
          <label for="newPassword">New Password</label>
          <input type="password" id="newPassword" placeholder="Minimum 6 characters" required autocomplete="new-password" />
        </div>
        <div class="form-group">
          <label for="confirmPassword">Confirm Password</label>
          <input type="password" id="confirmPassword" placeholder="Re-enter new password" required autocomplete="new-password" />
        </div>
        <button type="submit" id="submitBtn" class="btn">Update Password</button>
      </form>
    </div>

    <div id="successSection" class="success-container">
      <div class="badge">✓</div>
      <h1>Password Reset Successful!</h1>
      <p style="color: #94a3b8; font-size: 15px; line-height: 1.6; margin-top: 10px;">
        Your password has been updated successfully. You can now log in to Dhanda Grow using your new credentials.
      </p>
      <a href="{settings.FRONTEND_URL}/login" class="login-btn">Proceed to Login</a>
    </div>

    <div class="footer">Dhanda Grow AI • Apne Business Ko Banao Smart &amp; Digital</div>
  </div>

  <script>
    async function handleSubmit(e) {{
      e.preventDefault();
      const newPassword = document.getElementById('newPassword').value;
      const confirmPassword = document.getElementById('confirmPassword').value;
      const errorBox = document.getElementById('errorBox');
      const submitBtn = document.getElementById('submitBtn');

      errorBox.style.display = 'none';

      if (newPassword.length < 6) {{
        errorBox.textContent = 'Password must be at least 6 characters long.';
        errorBox.style.display = 'block';
        return;
      }}

      if (newPassword !== confirmPassword) {{
        errorBox.textContent = 'Passwords do not match.';
        errorBox.style.display = 'block';
        return;
      }}

      submitBtn.disabled = true;
      submitBtn.textContent = 'Updating password...';

      try {{
        const response = await fetch('/api/v1/auth/reset-password', {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          }},
          body: JSON.stringify({{
            token: '{clean_token}',
            newPassword: newPassword,
            confirmPassword: confirmPassword
          }})
        }});

        const result = await response.json();

        if (response.ok) {{
          document.getElementById('formSection').style.display = 'none';
          document.getElementById('successSection').style.display = 'block';
        }} else {{
          errorBox.textContent = result.detail || result.message || 'Failed to reset password.';
          errorBox.style.display = 'block';
          submitBtn.disabled = false;
          submitBtn.textContent = 'Update Password';
        }}
      }} catch (err) {{
        errorBox.textContent = 'Connection error. Please try again.';
        errorBox.style.display = 'block';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Update Password';
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=form_html)

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    """API endpoint to reset password. Accepts either 'link' (full reset link from email) or 'token'."""
    token_or_link = req.link or req.token
    if not token_or_link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide either 'link' (full reset link from email) or 'token'."
        )
    res = await AuthService.reset_password(token_or_link, req.newPassword, req.confirmPassword)
    return res


