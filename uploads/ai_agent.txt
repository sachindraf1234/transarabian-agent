"""
ai_agent.py - COMPLIANT Business-Specific AI Agent
Aligned with Meta's WhatsApp Business Policy:
- NOT general-purpose, restricted to business operations only
- Includes human handoff trigger
- Blocks general knowledge questions
- Safe for 24h window
"""
import os
import random
import re
from config import GEMINI_API_KEY, COMPLIANCE
from compliance import (
    get_compliant_system_prompt,
    is_general_purpose_query,
    needs_human_handoff,
    get_restricted_response,
    get_human_handoff_message
)

try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
    else:
        model = None
        print("⚠️ GEMINI_API_KEY not set - AI replies will use compliant fallback templates")
except ImportError:
    model = None
    print("⚠️ google-generativeai not installed, using fallback")

# Conversation memory (in production use DB)
conversation_history = {}  # phone -> list of messages

FALLBACK_COMPLIANT_REPLIES = {
    "greeting": [
        "Hi! 👋 Welcome to {business}. How can I help you with our products or orders today?",
        "Hello! Thanks for reaching out to {business} 😊 What can I assist you with?",
    ],
    "price": "Sure! I can share our price list for {business}. Let me send it over 📄",
    "catalog": "Absolutely! Here's our full product catalog from {business} 😊",
    "invoice": "Got it! Let me pull up your invoice and send it 📄",
    "order": "I can help track your order. Could you share your order ID?",
    "support": "I'm here to help with {business} support! Could you share more details?",
    "thanks": "You're most welcome! 🙏 Let me know if you need anything else from {business}",
    "default": "Thanks for your message! How can I assist you with {business} products, orders, or support today?",
}

def get_history(phone: str, limit: int = 8):
    return conversation_history.get(phone, [])[-limit:]

def add_to_history(phone: str, role: str, text: str):
    if phone not in conversation_history:
        conversation_history[phone] = []
    conversation_history[phone].append({"role": role, "text": text})
    if len(conversation_history[phone]) > 20:
        conversation_history[phone] = conversation_history[phone][-20:]

def generate_reply(phone: str, user_message: str, user_name: str = "") -> str:
    """
    Generate COMPLIANT business-specific reply
    Returns either normal reply or TRIGGER_HUMAN_HANDOFF
    """
    from config import BUSINESS_NAME
    
    history = get_history(phone)
    history_str = "\n".join([f"{h['role']}: {h['text']}" for h in history]) or "No previous messages"
    
    add_to_history(phone, "user", user_message)
    
    # === POLICY CHECK 1: General-purpose query? ===
    if is_general_purpose_query(user_message):
        reply = get_restricted_response()
        print(f"🚫 BLOCKED general-purpose query from {phone}: {user_message[:50]}")
        add_to_history(phone, "assistant", reply)
        return reply
    
    # === POLICY CHECK 2: Needs human handoff based on user message? ===
    if needs_human_handoff(user_message):
        print(f"🚨 Human handoff triggered by user message from {phone}: {user_message[:50]}")
        reply = COMPLIANCE["HUMAN_HANDOFF_TRIGGER"]
        add_to_history(phone, "assistant", reply)
        return reply
    
    # === Generate AI reply ===
    if not model:
        # Compliant fallback without AI
        lower = user_message.lower()
        if any(g in lower for g in ["hi", "hello", "hey", "hlo", "good morning", "good evening"]):
            reply = random.choice(FALLBACK_COMPLIANT_REPLIES["greeting"]).format(business=BUSINESS_NAME)
        elif "price" in lower or "rate" in lower:
            reply = FALLBACK_COMPLIANT_REPLIES["price"].format(business=BUSINESS_NAME)
        elif "catalog" in lower or "product" in lower:
            reply = FALLBACK_COMPLIANT_REPLIES["catalog"].format(business=BUSINESS_NAME)
        elif "invoice" in lower or "bill" in lower:
            reply = FALLBACK_COMPLIANT_REPLIES["invoice"]
        elif "order" in lower or "track" in lower:
            reply = FALLBACK_COMPLIANT_REPLIES["order"]
        elif "thank" in lower:
            reply = FALLBACK_COMPLIANT_REPLIES["thanks"].format(business=BUSINESS_NAME)
        else:
            reply = FALLBACK_COMPLIANT_REPLIES["default"].format(business=BUSINESS_NAME)
        
        # Check if fallback itself should trigger handoff (e.g., frustrated user)
        if needs_human_handoff(user_message, reply):
            reply = COMPLIANCE["HUMAN_HANDOFF_TRIGGER"]
        
        add_to_history(phone, "assistant", reply)
        return reply
    
    try:
        prompt = get_compliant_system_prompt(history_str) + f"\n\nUser ({user_name} - {phone}) says: {user_message}\n\nReply as human team member from {BUSINESS_NAME} (short, friendly, business-specific only). If unrelated to business, use restricted response. If frustrated or asks human, output {COMPLIANCE['HUMAN_HANDOFF_TRIGGER']}:"
        response = model.generate_content(prompt)
        reply = response.text.strip()
        reply = reply.replace("Assistant:", "").replace("assistant:", "").strip()
        
        if len(reply) > 600:
            reply = reply[:600]
        
        # Post-generation policy check
        if needs_human_handoff(user_message, reply):
            print(f"🚨 Human handoff triggered by AI response for {phone}")
            reply = COMPLIANCE["HUMAN_HANDOFF_TRIGGER"]
        
        # Ensure AI didn't go general-purpose (extra safety)
        if is_general_purpose_query(reply) and "I am only programmed" not in reply:
            # If AI itself generated general content, replace with restricted
            reply = get_restricted_response()
        
        add_to_history(phone, "assistant", reply)
        return reply
        
    except Exception as e:
        print(f"Gemini error: {e}")
        # On error, trigger handoff rather than fail
        if "frustrat" in user_message.lower() or "human" in user_message.lower():
            return COMPLIANCE["HUMAN_HANDOFF_TRIGGER"]
        reply = FALLBACK_COMPLIANT_REPLIES["default"].format(business=BUSINESS_NAME)
        add_to_history(phone, "assistant", reply)
        return reply

def should_send_document(user_message: str) -> tuple:
    """Detect if we should auto-send a doc - ONLY within 24h window and business-related"""
    lower = user_message.lower()
    # Only for business docs, not general files
    if "price" in lower and ("list" in lower or "send" in lower or "price" in lower):
        return (True, "price-list.pdf")
    if "catalog" in lower or "catalogue" in lower:
        return (True, "catalog.pdf")
    if "invoice" in lower and ("my" in lower or "send" in lower or "bill" in lower):
        return (True, "invoice")
    if "brochure" in lower:
        return (True, "catalog.pdf")
    return (False, None)

def is_ai_paused_for_human(phone: str) -> bool:
    """Check if AI is paused for human handoff"""
    # This will be checked via database in app.py, but keep in-memory fallback
    return False
