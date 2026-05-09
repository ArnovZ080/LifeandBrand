"""
Notification adapters for expiry alerts.

Three channels:
  email     — SMTP, compatible with Office 365 / Gmail / any SMTP relay
  teams     — Microsoft Teams Incoming Webhook (per-contact URL)
  whatsapp  — Twilio WhatsApp API (requires Business account)

Each adapter returns True on success, False on failure.
Failures are logged but never raise — the alert engine continues to
other contacts/channels even if one send fails.
"""

import json
import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AlertMessage:
    subject: str          # used by email and Teams card title
    body_text: str        # plain text (WhatsApp, SMS fallback)
    body_html: str        # rich HTML for email
    urgency: str          # "warning" | "action" | "urgent"
    item_name: str
    batch_reference: str
    quantity_remaining: float
    unit: str
    best_before_date: str
    days_until_expiry: int


# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(to_address: str, msg: AlertMessage) -> bool:
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password]):
        logger.warning("Email not configured — skipping")
        return False

    urgency_color = {"warning": "#f59e0b", "action": "#ef4444", "urgent": "#991b1b"}[msg.urgency]
    urgency_label = {"warning": "Freshness Warning", "action": "Action Required", "urgent": "URGENT — Expires Today"}[msg.urgency]

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
      <div style="background:{urgency_color};padding:16px 20px;border-radius:8px 8px 0 0">
        <h2 style="color:#fff;margin:0;font-size:18px">{urgency_label}</h2>
      </div>
      <div style="border:1px solid #e5e7eb;border-top:none;padding:20px;border-radius:0 0 8px 8px">
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:6px 0;color:#6b7280;font-size:13px">Item</td>
              <td style="padding:6px 0;font-weight:600">{msg.item_name}</td></tr>
          <tr><td style="padding:6px 0;color:#6b7280;font-size:13px">Batch</td>
              <td style="padding:6px 0">{msg.batch_reference}</td></tr>
          <tr><td style="padding:6px 0;color:#6b7280;font-size:13px">Remaining</td>
              <td style="padding:6px 0;font-weight:600">{msg.quantity_remaining:.2f} {msg.unit}</td></tr>
          <tr><td style="padding:6px 0;color:#6b7280;font-size:13px">Best Before</td>
              <td style="padding:6px 0;color:{urgency_color};font-weight:700">{msg.best_before_date}
                {"— TODAY" if msg.days_until_expiry == 0 else f"— {msg.days_until_expiry}h remaining" if msg.days_until_expiry <= 24 else f"— {msg.days_until_expiry // 24}d {msg.days_until_expiry % 24}h remaining"}
              </td></tr>
        </table>
        <p style="margin:16px 0 0;font-size:13px;color:#374151">
          Please coordinate with the floor team to push this item as a daily special or staff meal.
        </p>
        <p style="margin:8px 0 0;font-size:11px;color:#9ca3af">Life &amp; Brand Stock Control</p>
      </div>
    </div>
    """

    mime = MIMEMultipart("alternative")
    mime["Subject"] = msg.subject
    mime["From"] = settings.smtp_from_address or settings.smtp_user
    mime["To"] = to_address
    mime.attach(MIMEText(msg.body_text, "plain"))
    mime.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(mime["From"], to_address, mime.as_string())
        logger.info("Email sent to %s for batch %s", to_address, msg.batch_reference)
        return True
    except Exception as e:
        logger.error("Email failed to %s: %s", to_address, e)
        return False


# ── Microsoft Teams ────────────────────────────────────────────────────────────

def send_teams(webhook_url: str, msg: AlertMessage) -> bool:
    urgency_color = {"warning": "warning", "action": "attention", "urgent": "attention"}[msg.urgency]
    urgency_label = {"warning": "Freshness Warning ⚠️", "action": "Action Required 🔴", "urgent": "URGENT — Expires Today 🚨"}[msg.urgency]

    # Adaptive Card payload
    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": urgency_label,
                        "weight": "Bolder",
                        "size": "Medium",
                        "color": urgency_color,
                    },
                    {
                        "type": "FactSet",
                        "facts": [
                            {"title": "Item", "value": msg.item_name},
                            {"title": "Batch", "value": msg.batch_reference},
                            {"title": "Remaining", "value": f"{msg.quantity_remaining:.2f} {msg.unit}"},
                            {"title": "Best Before", "value": msg.best_before_date},
                            {"title": "Time Left", "value": (
                                "Expires TODAY" if msg.days_until_expiry == 0
                                else f"{msg.days_until_expiry}h" if msg.days_until_expiry <= 24
                                else f"{msg.days_until_expiry // 24}d {msg.days_until_expiry % 24}h"
                            )},
                        ],
                    },
                    {
                        "type": "TextBlock",
                        "text": "Coordinate with floor to push as daily special or staff meal.",
                        "wrap": True,
                        "color": "Default",
                        "size": "Small",
                    },
                ],
            },
        }],
    }

    try:
        r = httpx.post(webhook_url, json=card, timeout=10)
        r.raise_for_status()
        logger.info("Teams alert sent for batch %s", msg.batch_reference)
        return True
    except Exception as e:
        logger.error("Teams alert failed: %s", e)
        return False


# ── WhatsApp (Twilio) ──────────────────────────────────────────────────────────

def send_whatsapp(to_number: str, msg: AlertMessage) -> bool:
    """
    Sends via Twilio WhatsApp API.
    to_number must be in E.164 format: +27821234567
    Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM in .env
    """
    if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_whatsapp_from]):
        logger.warning("WhatsApp (Twilio) not configured — skipping")
        return False

    from_number = f"whatsapp:{settings.twilio_whatsapp_from}"
    to_wa = f"whatsapp:{to_number}"

    try:
        r = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            data={"From": from_number, "To": to_wa, "Body": msg.body_text},
            timeout=10,
        )
        r.raise_for_status()
        logger.info("WhatsApp sent to %s for batch %s", to_number, msg.batch_reference)
        return True
    except Exception as e:
        logger.error("WhatsApp failed to %s: %s", to_number, e)
        return False


# ── Message builder ────────────────────────────────────────────────────────────

def build_message(
    item_name: str,
    batch_reference: str,
    quantity_remaining: float,
    unit: str,
    best_before_date: str,
    days_until_expiry: int,
) -> AlertMessage:
    if days_until_expiry <= 0:
        urgency = "urgent"
        time_str = "expires TODAY"
        emoji = "🚨"
    elif days_until_expiry <= 24:
        urgency = "action"
        time_str = f"expires in {days_until_expiry}h"
        emoji = "🔴"
    else:
        urgency = "warning"
        time_str = f"expires in {days_until_expiry // 24}d {days_until_expiry % 24}h"
        emoji = "⚠️"

    subject = f"{emoji} {item_name} — {time_str} ({quantity_remaining:.1f} {unit} remaining)"

    body_text = (
        f"{emoji} *Freshness Alert*\n"
        f"*{item_name}* — {quantity_remaining:.1f} {unit} remaining\n"
        f"Batch: {batch_reference}\n"
        f"Best before: *{best_before_date}* ({time_str})\n"
        f"Please push at floor level 🍽️\n"
        f"— Life & Brand Stock System"
    )

    return AlertMessage(
        subject=subject,
        body_text=body_text,
        body_html="",  # built per-channel
        urgency=urgency,
        item_name=item_name,
        batch_reference=batch_reference,
        quantity_remaining=quantity_remaining,
        unit=unit,
        best_before_date=best_before_date,
        days_until_expiry=days_until_expiry,
    )
