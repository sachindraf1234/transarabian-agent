"""
compliance.py - Meta WhatsApp Business Policy Compliance Engine
Ensures AI agent follows:
- General-Purpose vs Business-Specific restriction
- 24h window rule
- Opt-in requirement
- Template-only for bulk
- Human handoff
"""
import re
import time
from datetime import datetime, timedelta
from typing import Tuple, Optional
from config import COMPLIANCE, BUSINESS_NAME, BUSINESS_GOALS, BUSINESS_INFO, BUSINESS_DESCRIPTION

# === GENERAL PURPOSE QUERY DETECTION ===
# Meta bans unrestricted LLM. Must block these.
GENERAL_PURPOSE_PATTERNS = [
    r"write me a poem", r"tell me a joke", r"help me code", r"write.*essay",
    r"who is the president", r"what is the meaning of life", r"explain quantum",
    r"politics", r"election", r"medical advice", r"diagnose", r"illegal",
    r"how to make.*drug", r"competitor.*better", r"stock price", r"crypto",
    r"general knowledge", r"trivia", r"recipe", r"movie recommendation",
    r"write a story", r"generate image", r"what's the weather"
]

PROFANITY_AND_FRUSTRATION = [
    r"\b(fuck|shit|asshole|bitch|bastard|idiot|stupid)\b",
    r"i want.*human", r"talk to.*human", r"real person", r"human agent",
    r"escalate", r"manager", r"supervisor", r"frustrated", r"angry", r"terrible service",
    r"useless", r"worst", r"complaint.*human"
]

def is_general_purpose_query(text: str) -> bool:
    """Detect if user asks general AI question (violates Meta policy)"""
    if not COMPLIANCE["BLOCK_GENERAL_PURPOSE_QUERIES"]:
        return False
    lower = text.lower()
    for pattern in GENERAL_PURPOSE_PATTERNS:
        if re.search(pattern, lower):
            return True
    # Heuristic: if asks question completely unrelated to business keywords
    business_keywords = ["price", "catalog", "product", "order", "invoice", "delivery", "payment", "stock", "cement", "tile", "steel", "material", "quote", "consultation", "booking", "support", "service"]
    # If message is question but contains none of business keywords and is > 10 chars, might be general
    if "?" in text and len(text) > 15:
        has_business_kw = any(kw in lower for kw in business_keywords)
        # If question about coding, poem, joke, etc already caught above, but also check for "what is", "who is", "how to" without business context
        general_starters = ["what is", "who is", "how to", "why is", "tell me about", "explain"]
        if any(lower.strip().startswith(s) for s in general_starters) and not has_business_kw:
            # Extra check: not asking about product
            if not any(kw in lower for kw in ["your", "you", "business", "product", "service"]):
                return True
    return False

def needs_human_handoff(text: str, ai_response: str = "") -> bool:
    """Check if user frustrated or asked for human, or AI triggered handoff"""
    lower = text.lower()
    # Check user message for handoff triggers
    for pattern in PROFANITY_AND_FRUSTRATION:
        if re.search(pattern, lower):
            return True
    
    # Check AI response for trigger phrase
    if COMPLIANCE["HUMAN_HANDOFF_TRIGGER"] in ai_response:
        return True
    
    # If user explicitly says STOP is handled elsewhere, but human request is handoff
    return False

def get_restricted_response() -> str:
    """Compliant response when user asks general purpose question"""
    return f"I am only programmed to assist with {BUSINESS_GOALS} for {BUSINESS_NAME}. How can I help you with our services today? You can ask about price lists, catalogs, orders, or support."

def get_human_handoff_message() -> str:
    """Message when routing to human"""
    return f"Got it - connecting you to a human team member from {BUSINESS_NAME} right away. A real person will reply shortly. Thank you for your patience 🙏"

def is_in_24h_window(last_inbound_timestamp: Optional[datetime]) -> bool:
    """Check if we're within 24h customer service window"""
    if not last_inbound_timestamp:
        return False
    return datetime.now() - last_inbound_timestamp <= timedelta(hours=24)

def validate_bulk_opt_in(phone: str, db_check_func) -> bool:
    """Validate explicit opt-in for bulk (Meta requirement)"""
    if not COMPLIANCE["REQUIRE_OPT_IN_FOR_BULK"]:
        return True
    # db_check_func should check contacts table for opted_in flag
    try:
        contact = db_check_func(phone)
        if not contact:
            return False
        return contact.get("opted_in", 0) == 1 and contact.get("blocked", 0) == 0
    except:
        return False

def audit_message_compliance(phone: str, message_type: str, is_bulk: bool, is_template: bool, in_24h_window: bool) -> Tuple[bool, str]:
    """
    Audit if a message is compliant before sending
    Returns (is_compliant, reason)
    """
    if is_bulk:
        # Bulk must be template
        if not is_template:
            return False, "BULK VIOLATION: Business-initiated bulk must use pre-approved template, not free text. Create template in Meta dashboard."
        # Bulk must have opt-in (checked separately)
    else:
        # Single message
        if not in_24h_window and not is_template:
            if COMPLIANCE["REQUIRE_24H_WINDOW_FOR_FREE_TEXT"]:
                return False, "24H WINDOW VIOLATION: Outside 24h window, must use template, not free custom text. User must message first or use approved template."
    
    # Document checks
    if message_type == "document" and is_bulk and not is_template:
        return False, "BULK DOC VIOLATION: Cannot send raw document in bulk. Must use Media Message Template with document header."
    
    return True, "Compliant"

# === SYSTEM PROMPT FOR COMPLIANT AI ===
def get_compliant_system_prompt(history: str = "") -> str:
    return f"""
You are a task-oriented AI assistant for {BUSINESS_NAME}.

Business Description: {BUSINESS_DESCRIPTION}
Business Info: {BUSINESS_INFO}
Your sole objective is to assist users with {BUSINESS_GOALS}.

CRITICAL SAFETY POLICIES (Meta Compliance - MUST FOLLOW):

1. SCOPE RESTRICTION - You are NOT a general-purpose chatbot:
   - ONLY answer questions about {BUSINESS_NAME} products, orders, price lists, catalogs, invoices, delivery, payment, bookings, support
   - If user asks general knowledge, personal advice, poems, jokes, coding, politics, medical, illegal, competitor brands, or anything unrelated to {BUSINESS_NAME}:
     -> Politely reply: "I am only programmed to assist with {BUSINESS_GOALS} for {BUSINESS_NAME}. How can I help you with our services today?"
   - NEVER discuss politics, medical advice, illegal substances, competitor brands.

2. HUMAN HANDOFF - Mandatory:
   - If user expresses frustration, uses profanity, says "talk to human", "real person", "manager", "escalate", or explicitly asks for human agent:
     -> Output EXACT phrase: {COMPLIANCE['HUMAN_HANDOFF_TRIGGER']}
     -> Do not attempt to resolve further. Human team will take over.
   - If you cannot answer or are unsure, also output {COMPLIANCE['HUMAN_HANDOFF_TRIGGER']} instead of hallucinating.

3. DOCUMENT HANDLING:
   - If user asks for price list, catalog, invoice: Acknowledge and say you will send it. System will handle actual file sending via tool.
   - Do NOT provide local file paths. Documents are sent via public HTTPS URLs.

4. STYLE:
   - Reply like a real human from {BUSINESS_NAME}: short (under 250 chars), friendly, casual
   - Use occasional emojis but not excessive
   - Never say you are AI or bot. You are a human team member from {BUSINESS_NAME}
   - If greeting, greet back warmly and ask how you can help with business services
   - Keep context but stay within business scope

5. COMPLIANCE:
   - Never mention you are Meta AI or general assistant
   - Always stay within {BUSINESS_GOALS}

Current conversation history:
{history}
"""

# For logging compliance audits
def log_compliance_check(phone, check_result, message_type, is_bulk):
    timestamp = datetime.now().isoformat()
    print(f"[COMPLIANCE AUDIT {timestamp}] Phone:{phone} Type:{message_type} Bulk:{is_bulk} -> {check_result}")
