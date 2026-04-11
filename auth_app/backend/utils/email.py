"""Email sending utilities (SMTP).  Falls back to console-print when SMTP is not configured."""

import logging
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def send_verification_email(to_email: str, name: str, token: str) -> bool:
    """Send email-verification link. Returns True on success."""
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

    # If SMTP is not configured, log to console (dev mode)
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.info(
            f"[DEV EMAIL] Verification link for {to_email}:\n  {verify_url}"
        )
        print(f"\n{'='*60}")
        print(f"  EMAIL VERIFICATION (dev mode — SMTP not configured)")
        print(f"  To:   {to_email}")
        print(f"  Name: {name}")
        print(f"  Link: {verify_url}")
        print(f"{'='*60}\n")
        return True

    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: auto; padding: 30px; border: 1px solid #e5e7eb; border-radius: 12px;">
            <h2 style="color: #4f46e5;">Welcome to {settings.APP_NAME}, {name}!</h2>
            <p>Please verify your email address by clicking the button below:</p>
            <a href="{verify_url}"
               style="display:inline-block; padding:12px 28px; background:#4f46e5;
                      color:#fff; text-decoration:none; border-radius:8px; margin:16px 0;">
                Verify Email
            </a>
            <p style="color:#6b7280; font-size:13px;">
                Or copy this link: <br><code>{verify_url}</code>
            </p>
            <p style="color:#9ca3af; font-size:12px;">This link expires in 24 hours.</p>
        </div>
        """

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = to_email
        msg["Subject"] = f"Verify your email — {settings.APP_NAME}"
        msg.attach(MIMEText(f"Verify your email: {verify_url}", "plain"))
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info(f"Verification email sent to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False
