"""
config.py - Compliant config for WhatsApp Business API
Aligned with Meta's Business Messaging Policy & AI Restrictions
"""
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secret_verify_token_123")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMIN_NOTIFY_NUMBER = os.getenv("ADMIN_NOTIFY_NUMBER", "")
API_VERSION = os.getenv("API_VERSION", "v21.0")
API_URL = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"
PORT = int(os.getenv("PORT", "8000"))

# === BUSINESS IDENTITY - REQUIRED FOR COMPLIANT AI ===
# CHANGE THESE TO YOUR ACTUAL BUSINESS
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Your Business Name")
BUSINESS_DESCRIPTION = os.getenv("BUSINESS_DESCRIPTION", 
    "We sell construction materials, provide price lists, catalogs, invoices, and order tracking support")
BUSINESS_GOALS = os.getenv("BUSINESS_GOALS",
    "answering product FAQs, sending price lists and catalogs, tracking orders, booking consultations, providing invoices")
BUSINESS_INFO = os.getenv("BUSINESS_INFO",
    "Products: cement, steel, tiles, sanitaryware. Location: Colombo, Sri Lanka. Hours: Mon-Sat 9am-6pm")

# === META APPROVED TEMPLATES - YOU MUST CREATE THESE IN META DASHBOARD ===
# Create at: https://business.facebook.com/wa/manage/message-templates/
TEMPLATES = {
    # For bulk text - must have STOP quick reply button
    "bulk_text_with_optout": {
        "name": os.getenv("TEMPLATE_BULK_TEXT", "bulk_update_with_optout"), # template name in Meta
        "language": "en_US",
        "description": "Bulk text update with opt-out button - for business-initiated outside 24h"
    },
    # For bulk document - header type DOCUMENT
    "bulk_document": {
        "name": os.getenv("TEMPLATE_BULK_DOC", "document_share_template"),
        "language": "en_US",
        "description": "Media template with document header - for bulk doc sending"
    },
    # For re-engaging outside 24h window
    "customer_service_followup": {
        "name": os.getenv("TEMPLATE_FOLLOWUP", "customer_followup"),
        "language": "en_US",
    },
    # Order update etc
    "order_update": {
        "name": os.getenv("TEMPLATE_ORDER", "order_update_template"),
        "language": "en_US",
    }
}

# === COMPLIANCE SETTINGS ===
COMPLIANCE = {
    "REQUIRE_OPT_IN_FOR_BULK": True,
    "HUMAN_HANDOFF_TRIGGER": "[TRIGGER_HUMAN_HANDOFF]",
    "PAUSE_AI_AFTER_HANDOFF_MINUTES": 60,  # Pause AI for 60 min after handoff
    "BLOCK_GENERAL_PURPOSE_QUERIES": True,
    "REQUIRE_24H_WINDOW_FOR_FREE_TEXT": True,
    "INCLUDE_STOP_BUTTON_IN_BULK": True,
}

# Anti-ban + human behavior (still needed for free text within 24h)
ANTI_BAN = {
    "MAX_PER_HOUR": 80,
    "MAX_PER_DAY": 600,
    "BATCH_SIZE": 25,
    "MIN_DELAY_BETWEEN_CONTACTS": 18,
    "MAX_DELAY_BETWEEN_CONTACTS": 45,
    "BATCH_BREAK_MIN": 180,
    "BATCH_BREAK_MAX": 480,
    "ENABLE_TYPING_INDICATOR": True,
    "ENABLE_READ_RECEIPT": True,
    "RANDOMIZE_ORDER": True,
    "RESPECT_ACTIVE_HOURS": True,
    # Meta compliant rate limiter - min 2-5 sec even for templates
    "MIN_TEMPLATE_DELAY": 3.0,  # seconds between template sends (Meta safe)
}

# WhatsApp shortcuts - only for human agents within 24h window, not for bulk templates
SHORTCUTS = {
    "/greet": "Hi there! 👋 How can I help you today?",
    "/price": "Sure! Here's our price list. Let me send it over 📄",
    "/thanks": "You're most welcome! 🙏 Let me know if you need anything else.",
    "/catalog": "Absolutely! Here's our full catalog with all products.",
    "/payment": "For payment, you can use bank transfer or COD. I'll send the details.",
    "/support": "I'm here to help! Could you please share more details about the issue?",
    "/bye": "Thanks for chatting! Have a great day 😊",
}

HUMAN_PREFIXES = ["", "", "", "Hey! ", "Hi, ", "Sure, ", "Okay so ",]

if not TOKEN or not PHONE_NUMBER_ID:
    print("⚠️ WARNING: WHATSAPP_TOKEN and PHONE_NUMBER_ID must be set in .env")
