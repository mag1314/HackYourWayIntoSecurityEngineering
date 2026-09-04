"""Notification of "this form needs your input".

Never raises: an email problem must not abort an application run. Every
notification is ALSO written to output/NEEDS_INPUT.md so you have a durable
list even with no SMTP configured at all.
"""
import os, smtplib, ssl
from datetime import datetime
from email.message import EmailMessage
from .config import OUTPUT_DIR

LOG = OUTPUT_DIR / "NEEDS_INPUT.md"


def _log(subject: str, body: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"\n\n---\n## {subject}\n_{datetime.now():%Y-%m-%d %H:%M}_\n\n{body}\n")


def send_email(subject: str, body: str) -> bool:
    """Returns True if emailed. Always logs to output/NEEDS_INPUT.md first."""
    _log(subject, body)

    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    pw = (os.getenv("SMTP_PASS") or "").replace(" ", "")  # Gmail shows app passwords in 4-char groups
    to = os.getenv("NOTIFY_TO") or user
    port = int(os.getenv("SMTP_PORT", "587"))

    if not all([host, user, pw, to]) or pw in ("your-app-password", ""):
        print(f"  [notify] SMTP not configured - logged to {LOG.name} instead.")
        return False

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
                s.login(user, pw); s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pw); s.send_message(msg)
        print(f"  [notify] emailed {to}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  [notify] SMTP login rejected (535). Gmail needs an APP PASSWORD, not your\n"
              "           normal password, and 2-Step Verification must be on:\n"
              "           https://myaccount.google.com/apppasswords\n"
              f"           Details still saved to {LOG.name}.")
    except Exception as e:
        print(f"  [notify] email failed ({type(e).__name__}: {e}); details saved to {LOG.name}.")
    return False
