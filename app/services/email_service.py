import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import asyncio
from typing import Optional
from app.core.config import settings
import logging
import os
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    async def send_verification_email(to_email: str, verification_link: str, full_name: Optional[str] = None):
        """Send verification email with Dhanda Grow branding and clickable link via SMTP."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            EmailService._send_verification_email_sync,
            to_email,
            verification_link,
            full_name
        )

    @staticmethod
    def _send_verification_email_sync(to_email: str, verification_link: str, full_name: Optional[str] = None):
        recipient_name = full_name or to_email.split('@')[0]
        subject = "Verify your email - Dhanda Grow"

        text_body = f"""Namaste {recipient_name},

Welcome to Dhanda Grow!
Please verify your email address to activate your account and start growing your business with AI:

{verification_link}

This link is valid for 24 hours.

If you did not sign up for Dhanda Grow, please ignore this email.

Best regards,
The Dhanda Grow Team
"""

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verify Your Email - Dhanda Grow</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f4f6fb; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f4f6fb; padding: 40px 15px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 18px; box-shadow: 0 12px 36px rgba(32, 22, 124, 0.08); overflow: hidden; border: 1px solid #e5e9f2;" cellspacing="0" cellpadding="0">
          
          <!-- Top Gradient Accent Bar -->
          <tr>
            <td style="background: linear-gradient(90deg, #20167c 0%, #4338ca 45%, #f97316 100%); height: 6px; font-size: 0; line-height: 0;">&nbsp;</td>
          </tr>

          <!-- Header with Logo -->
          <tr>
            <td style="background-color: #ffffff; padding: 36px 32px 20px 32px; text-align: center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <img src="cid:dhandagrow_logo" alt="Dhanda Grow AI" width="250" style="width: 250px; max-width: 100%; height: auto; display: block; margin: 0 auto; border: 0;" />
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top: 10px;">
                    <p style="margin: 0; color: #64748b; font-size: 13px; font-weight: 500; letter-spacing: 0.3px;">Apne Business Ko Banao Smart &amp; Digital</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Content Section -->
          <tr>
            <td style="padding: 10px 38px 32px 38px;">
              <div style="background-color: #f8fafc; border: 1px solid #edf2f7; border-radius: 14px; padding: 28px 24px;">
                <h2 style="margin: 0 0 14px 0; color: #1e1b4b; font-size: 21px; font-weight: 700; text-align: center;">Confirm Your Email Address</h2>
                <p style="margin: 0 0 16px 0; color: #475569; font-size: 15px; line-height: 1.6;">Hello <strong>{recipient_name}</strong>,</p>
                <p style="margin: 0 0 24px 0; color: #475569; font-size: 15px; line-height: 1.6;">
                  Welcome to <strong>Dhanda Grow</strong>! Thank you for joining our platform. Tap the button below to verify your email address and start growing your business with our AI-powered marketing and management tools:
                </p>

                <!-- CTA Button -->
                <table role="presentation" cellspacing="0" cellpadding="0" style="margin: 28px auto; width: 100%;">
                  <tr>
                    <td align="center">
                      <a href="{verification_link}" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #20167c 0%, #3730a3 50%, #f97316 100%); color: #ffffff; font-size: 16px; font-weight: 700; text-decoration: none; padding: 15px 40px; border-radius: 10px; box-shadow: 0 6px 18px rgba(32, 22, 124, 0.28); letter-spacing: 0.3px;">Verify Email Address</a>
                    </td>
                  </tr>
                </table>

                <p style="margin: 24px 0 6px 0; color: #64748b; font-size: 13px; text-align: center;">Or copy and paste this link in your browser:</p>
                <p style="margin: 0 0 20px 0; word-break: break-all; font-size: 12px; color: #4338ca; text-align: center; background: #ffffff; padding: 10px 14px; border-radius: 8px; border: 1px dashed #cbd5e1;">
                  <a href="{verification_link}" style="color: #4338ca; text-decoration: underline;">{verification_link}</a>
                </p>

                <p style="margin: 16px 0 0 0; color: #94a3b8; font-size: 12px; line-height: 1.5; text-align: center;">
                  ⏱️ This verification link will expire in 24 hours.
                </p>
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8fafc; padding: 24px 32px; text-align: center; border-top: 1px solid #edf2f7;">
              <p style="margin: 0 0 6px 0; color: #1e1b4b; font-size: 13px; font-weight: 600;">Dhanda Grow AI</p>
              <p style="margin: 0 0 10px 0; color: #94a3b8; font-size: 12px;">Automated Marketing • Brand Kit • AI Catalog • Smart Growth</p>
              <p style="margin: 0; color: #cbd5e1; font-size: 11px;">© Dhanda Grow. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

        EmailService._send_email_sync(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            logo_cid="dhandagrow_logo"
        )

    @staticmethod
    async def send_password_reset_email(to_email: str, reset_link: str, full_name: Optional[str] = None):
        """Send password reset email with Dhanda Grow branding and clickable link via SMTP."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            EmailService._send_password_reset_email_sync,
            to_email,
            reset_link,
            full_name
        )

    @staticmethod
    def _send_password_reset_email_sync(to_email: str, reset_link: str, full_name: Optional[str] = None):
        recipient_name = full_name or to_email.split('@')[0]
        subject = "Reset your password - Dhanda Grow"

        text_body = f"""Hello {recipient_name},

We received a request to reset your Dhanda Grow account password.
Please visit the following link to choose a new password:

{reset_link}

This link is valid for 1 hour.

If you did not request a password reset, you can safely ignore this email. Your password will remain unchanged.

Best regards,
The Dhanda Grow Team
"""

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Your Password - Dhanda Grow</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f4f6fb; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f4f6fb; padding: 40px 15px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 18px; box-shadow: 0 12px 36px rgba(32, 22, 124, 0.08); overflow: hidden; border: 1px solid #e5e9f2;" cellspacing="0" cellpadding="0">
          
          <!-- Top Accent Bar -->
          <tr>
            <td style="background: linear-gradient(90deg, #20167c 0%, #4338ca 45%, #f97316 100%); height: 6px; font-size: 0; line-height: 0;">&nbsp;</td>
          </tr>

          <!-- Header with Logo -->
          <tr>
            <td style="background-color: #ffffff; padding: 36px 32px 20px 32px; text-align: center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <img src="cid:dhandagrow_logo" alt="Dhanda Grow AI" width="250" style="width: 250px; max-width: 100%; height: auto; display: block; margin: 0 auto; border: 0;" />
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top: 10px;">
                    <p style="margin: 0; color: #64748b; font-size: 13px; font-weight: 500; letter-spacing: 0.3px;">Apne Business Ko Banao Smart &amp; Digital</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Content Section -->
          <tr>
            <td style="padding: 10px 38px 32px 38px;">
              <div style="background-color: #f8fafc; border: 1px solid #edf2f7; border-radius: 14px; padding: 28px 24px;">
                <h2 style="margin: 0 0 14px 0; color: #1e1b4b; font-size: 21px; font-weight: 700; text-align: center;">Reset Your Password</h2>
                <p style="margin: 0 0 16px 0; color: #475569; font-size: 15px; line-height: 1.6;">Hello <strong>{recipient_name}</strong>,</p>
                <p style="margin: 0 0 24px 0; color: #475569; font-size: 15px; line-height: 1.6;">
                  We received a request to reset the password for your <strong>Dhanda Grow</strong> account. Click the button below to choose your new password:
                </p>

                <!-- CTA Button -->
                <table role="presentation" cellspacing="0" cellpadding="0" style="margin: 28px auto; width: 100%;">
                  <tr>
                    <td align="center">
                      <a href="{reset_link}" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #20167c 0%, #3730a3 50%, #f97316 100%); color: #ffffff; font-size: 16px; font-weight: 700; text-decoration: none; padding: 15px 40px; border-radius: 10px; box-shadow: 0 6px 18px rgba(32, 22, 124, 0.28); letter-spacing: 0.3px;">Reset Password</a>
                    </td>
                  </tr>
                </table>

                <p style="margin: 24px 0 6px 0; color: #64748b; font-size: 13px; text-align: center;">Or copy and paste this link in your browser:</p>
                <p style="margin: 0 0 20px 0; word-break: break-all; font-size: 12px; color: #4338ca; text-align: center; background: #ffffff; padding: 10px 14px; border-radius: 8px; border: 1px dashed #cbd5e1;">
                  <a href="{reset_link}" style="color: #4338ca; text-decoration: underline;">{reset_link}</a>
                </p>

                <p style="margin: 16px 0 0 0; color: #94a3b8; font-size: 12px; line-height: 1.5; text-align: center;">
                  ⏱️ This reset link is valid for 1 hour. If you didn't request a password reset, you can safely ignore this message.
                </p>
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8fafc; padding: 24px 32px; text-align: center; border-top: 1px solid #edf2f7;">
              <p style="margin: 0 0 6px 0; color: #1e1b4b; font-size: 13px; font-weight: 600;">Dhanda Grow AI</p>
              <p style="margin: 0 0 10px 0; color: #94a3b8; font-size: 12px;">Automated Marketing • Brand Kit • AI Catalog • Smart Growth</p>
              <p style="margin: 0; color: #cbd5e1; font-size: 11px;">© Dhanda Grow. All rights reserved.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

        EmailService._send_email_sync(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            logo_cid="dhandagrow_logo"
        )

    @staticmethod
    async def send_otp_email(to_email: str, otp: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, EmailService._send_otp_email_sync, to_email, otp)

    @staticmethod
    def _send_otp_email_sync(to_email: str, otp: str):
        subject = "Your Dhanda Grow Verification Code"
        text_body = f"Your verification code is: {otp}\n\nThis code will expire in 10 minutes."
        html_body = f"""
        <div style="font-family: Arial, sans-serif; padding: 25px; color: #1e1b4b; background-color: #f4f6fb;">
            <div style="max-width: 480px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 14px; border: 1px solid #e2e8f0; text-align: center;">
                <img src="cid:dhandagrow_logo" alt="Dhanda Grow" width="200" style="margin-bottom: 20px;" />
                <h2 style="color: #20167c; margin-bottom: 8px;">Verification Code</h2>
                <p style="color: #64748b; font-size: 14px;">Enter the following OTP code to proceed:</p>
                <div style="font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #f97316; margin: 24px 0; padding: 12px; background: #f8fafc; border-radius: 8px;">{otp}</div>
                <p style="color: #94a3b8; font-size: 12px;">This code will expire in 10 minutes.</p>
            </div>
        </div>
        """
        EmailService._send_email_sync(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            logo_cid="dhandagrow_logo"
        )

    @staticmethod
    def _send_email_sync(to_email: str, subject: str, text_body: str, html_body: str, logo_cid: Optional[str] = None):
        host = settings.SMTP_HOST
        port = settings.SMTP_PORT
        username = settings.SMTP_USERNAME
        password = settings.SMTP_PASSWORD
        from_email = settings.SMTP_FROM_EMAIL or username

        if not host or not username or not password:
            logger.error("SMTP is not configured in settings.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Email service is unavailable. SMTP is not configured."
            )

        clean_password = password.replace(" ", "")

        try:
            # Related multipart container for HTML + inline CID images
            msg = MIMEMultipart("related")
            msg['From'] = f"Dhanda Grow <{from_email}>"
            msg['To'] = to_email
            msg['Subject'] = subject

            # Alternative part for plain text and HTML
            msg_alt = MIMEMultipart("alternative")
            msg.attach(msg_alt)

            msg_alt.attach(MIMEText(text_body, 'plain'))
            msg_alt.attach(MIMEText(html_body, 'html'))

            # Attach inline dhandagrow logo if requested
            if logo_cid:
                logo_path = os.path.join("assets", "images", "dhandagrow.png")
                if os.path.exists(logo_path):
                    with open(logo_path, "rb") as img_file:
                        img = MIMEImage(img_file.read(), _subtype="png")
                        img.add_header("Content-ID", f"<{logo_cid}>")
                        img.add_header("Content-Disposition", "inline", filename="dhandagrow.png")
                        msg.attach(img)

            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=20)
            else:
                server = smtplib.SMTP(host, port, timeout=20)
                server.starttls()

            server.login(username, clean_password)
            server.send_message(msg)
            server.quit()
            logger.info(f"Successfully sent Dhanda Grow email to {to_email} with subject '{subject}'")
        except Exception as e:
            logger.error(f"Failed to send email to {to_email} via SMTP: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send email: {str(e)}"
            )
