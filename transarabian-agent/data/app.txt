"""
app.py - COMPLIANT FastAPI Webhook Server
Implements Meta's policies:
- Business-specific AI only
- 24h window enforcement
- Human handoff routing loop
- Template-only for bulk/outside window
- Opt-in tracking
"""
from fastapi import FastAPI, Request, BackgroundTasks, Query
from fastapi.responses import PlainTextResponse, JSONResponse
import time
import random
import os
from datetime import datetime

from config import VERIFY_TOKEN, ADMIN_NOTIFY_NUMBER, API_VERSION, TEMPLATES, COMPLIANCE, BUSINESS_NAME
from whatsapp_client import client
from human_behavior import human
from ai_agent import generate_reply, should_send_document
from database import (
    init_db, log_message, get_recent_messages, is_opted_out, set_opted_out,
    is_in_24h_window, is_opted_in, set_opted_in,
    trigger_human_handoff, is_ai_paused, get_handoff_queue, resolve_handoff,
    log_compliance
)
from compliance import needs_human_handoff, get_human_handoff_message

app = FastAPI(title="WhatsApp Human Agent - COMPLIANT", version="3.0")

@app.on_event("startup")
def startup():
    init_db()
    print("🚀 WhatsApp Human Agent COMPLIANT started")
    print(f"📱 Phone ID: {os.getenv('PHONE_NUMBER_ID')}")
    print(f"🏢 Business: {BUSINESS_NAME}")
    print("✅ Compliance: Business-specific AI, 24h window, Human handoff, Template-only bulk")
    print("✅ Ready to receive messages")

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print("✅ Webhook verified!")
        return PlainTextResponse(content=hub_challenge, status_code=200)
    else:
        return PlainTextResponse(content="Verification failed", status_code=403)

@app.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        print(f"\n📥 Incoming webhook: {data}\n")
        
        if data.get("object") != "whatsapp_business_account":
            return JSONResponse({"status": "not whatsapp"}, status_code=200)
        
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if "messages" not in value:
                    continue
                
                for message in value.get("messages", []):
                    from_number = message.get("from")
                    msg_id = message.get("id")
                    msg_type = message.get("type")
                    contact_name = ""
                    if value.get("contacts"):
                        contact_name = value["contacts"][0].get("profile", {}).get("name", "")
                    
                    print(f"👤 From {from_number} ({contact_name}) Type: {msg_type} | 24h window: {is_in_24h_window(from_number)} | Opt-in: {is_opted_in(from_number)}")
                    
                    if is_opted_out(from_number):
                        print(f"🚫 {from_number} opted out, ignoring")
                        continue
                    
                    # Check if AI paused for human handoff
                    if is_ai_paused(from_number):
                        print(f"⏸️ AI paused for {from_number} - human handoff active, routing to dashboard")
                        # Log but don't auto-reply, notify admin
                        if msg_type == "text":
                            text_body = message.get("text", {}).get("body", "")
                            log_message(from_number, "inbound", "text", text_body, wa_id=msg_id)
                            background_tasks.add_task(notify_human_dashboard, from_number, text_body, contact_name, "AI paused - human handling")
                        continue
                    
                    if msg_type == "text":
                        text_body = message.get("text", {}).get("body", "")
                        print(f"💬 Text: {text_body}")
                        log_message(from_number, "inbound", "text", text_body, wa_id=msg_id)
                        
                        # Auto opt-in on inbound (user reached out)
                        if not is_opted_in(from_number):
                            set_opted_in(from_number, source="inbound_message")
                        
                        # Handle opt-out keywords
                        lower = text_body.lower()
                        if any(kw in lower for kw in ["stop", "unsubscribe", "opt out", "opt-out"]):
                            set_opted_out(from_number)
                            background_tasks.add_task(
                                client.send_text,
                                from_number,
                                "You've been unsubscribed. You won't receive further broadcasts. Reply START to resubscribe. You can still message us for support.",
                                False
                            )
                            continue
                        
                        if "start" in lower and is_opted_out(from_number):
                            set_opted_in(from_number, source="user_resubscribe")
                            background_tasks.add_task(
                                client.send_text,
                                from_number,
                                "You're resubscribed! Thanks for staying with us 🙏",
                                False
                            )
                            continue
                        
                        background_tasks.add_task(
                            handle_text_message,
                            from_number,
                            text_body,
                            contact_name,
                            msg_id
                        )
                    
                    elif msg_type in ["document", "image", "audio", "video"]:
                        media_info = message.get(msg_type, {})
                        filename = media_info.get("filename", f"{msg_type}_{msg_id}")
                        print(f"📎 {msg_type}: {filename}")
                        log_message(from_number, "inbound", msg_type, media_info.get("id", ""), filename=filename, wa_id=msg_id)
                        background_tasks.add_task(
                            handle_media_message,
                            from_number,
                            msg_type,
                            filename,
                            contact_name,
                            msg_id
                        )
                    
                    elif msg_type == "button":
                        btn_text = message.get("button", {}).get("text", "")
                        print(f"🔘 Button: {btn_text}")
                        # Handle STOP button from template
                        if btn_text.lower() in ["stop", "unsubscribe", "opt out"]:
                            set_opted_out(from_number)
                            background_tasks.add_task(
                                client.send_text,
                                from_number,
                                "You've been unsubscribed from broadcasts.",
                                False
                            )
                        else:
                            background_tasks.add_task(handle_text_message, from_number, btn_text, contact_name, msg_id)
                    
                    elif msg_type == "interactive":
                        # Quick reply buttons (STOP etc)
                        interactive = message.get("interactive", {})
                        if interactive.get("type") == "button_reply":
                            btn_id = interactive.get("button_reply", {}).get("id", "")
                            btn_title = interactive.get("button_reply", {}).get("title", "")
                            print(f"🔘 Interactive button: {btn_id} - {btn_title}")
                            if "stop" in btn_id.lower() or "stop" in btn_title.lower():
                                set_opted_out(from_number)
                            else:
                                background_tasks.add_task(handle_text_message, from_number, btn_title, contact_name, msg_id)
        
        return JSONResponse({"status": "ok"}, status_code=200)
    
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"status": "error", "error": str(e)}, status_code=200)

def notify_human_dashboard(phone, message, contact_name, reason):
    """Route to live dashboard (Slack/CRM) when human handoff triggered"""
    print(f"📋 HUMAN DASHBOARD NOTIFICATION: {phone} ({contact_name}) - {reason}: {message}")
    if ADMIN_NOTIFY_NUMBER:
        client.send_notification(
            ADMIN_NOTIFY_NUMBER,
            f"Human Handoff Needed - {contact_name or phone}",
            f"Phone: {phone}\nName: {contact_name}\nReason: {reason}\nMessage: {message}\n\nAI paused for {COMPLIANCE['PAUSE_AI_AFTER_HANDOFF_MINUTES']} min. Reply manually or resolve in /handoff-queue"
        )

def handle_text_message(from_number: str, text: str, contact_name: str, msg_id: str):
    """
    COMPLIANT human reply logic:
    1. Check human handoff
    2. Generate business-specific AI reply
    3. If TRIGGER_HUMAN_HANDOFF, route to dashboard and pause AI
    4. Else send reply (free text allowed because within 24h - user just messaged)
    5. If doc intent, send doc via tool (public HTTPS) within 24h window
    """
    try:
        # 1. Read delay + mark read
        read_delay = human.read_delay()
        print(f"👀 Human reading {from_number}: {read_delay}s | 24h window: {is_in_24h_window(from_number)}")
        time.sleep(read_delay)
        
        try:
            client.mark_as_read(msg_id)
        except:
            pass
        
        # 2. Check if AI paused (double check)
        if is_ai_paused(from_number):
            print(f"⏸️ AI still paused for {from_number}, skipping auto-reply")
            notify_human_dashboard(from_number, text, contact_name, "Message while AI paused")
            return
        
        # 3. Generate compliant AI reply
        reply_text = generate_reply(from_number, text, contact_name)
        print(f"🤖 AI reply to {from_number}: {reply_text}")
        
        # 4. HUMAN HANDOFF ROUTING LOOP (Meta requirement)
        if COMPLIANCE["HUMAN_HANDOFF_TRIGGER"] in reply_text:
            print(f"🚨 HUMAN HANDOFF TRIGGER detected for {from_number}")
            # Trigger handoff
            trigger_human_handoff(from_number, reason=f"AI triggered handoff: user said '{text[:100]}'")
            log_compliance(from_number, "human_handoff", True, f"Triggered by: {text[:100]}")
            
            # Send handoff message to user (free text allowed within 24h)
            handoff_msg = get_human_handoff_message()
            results = client.send_text(from_number, handoff_msg, human_like=True)
            for r in results:
                if r["status"] == "sent":
                    wa_id = r.get("response", {}).get("messages", [{}])[0].get("id", "")
                    log_message(from_number, "outbound", "text", handoff_msg, status="sent", wa_id=wa_id)
            
            # Notify admin / dashboard
            notify_human_dashboard(from_number, text, contact_name, "AI triggered human handoff")
            return
        
        # 5. Normal flow - send reply (compliant because user just messaged, within 24h)
        think = random.uniform(0.8, 2.5)
        time.sleep(think)
        
        # Compliance check: we're within 24h because user just messaged, so free text allowed
        results = client.send_text(from_number, reply_text, human_like=True)
        for r in results:
            if r["status"] == "sent":
                wa_id = r.get("response", {}).get("messages", [{}])[0].get("id", "")
                log_message(from_number, "outbound", "text", reply_text, status="sent", wa_id=wa_id)
            elif r["status"] == "blocked_compliance":
                # Should not happen within 24h, but fallback to template
                print(f"⚠️ Free text blocked, falling back to template for {from_number}")
                fallback_vars = [contact_name or "there", reply_text[:150]]
                client.send_template_text(from_number, TEMPLATES["customer_service_followup"]["name"], "en_US", fallback_vars)
        
        # 6. Document intent - tool/function call within 24h window (compliant)
        should_send, doc_type = should_send_document(text)
        if should_send:
            time.sleep(random.uniform(2.5, 5.0))
            doc_map = {
                "price-list.pdf": {
                    "link": os.getenv("PRICE_LIST_LINK", "https://yoursite.com/files/price-list.pdf"),
                    "filename": "price-list.pdf",
                    "caption": "Here's our price list 📄"
                },
                "catalog.pdf": {
                    "link": os.getenv("CATALOG_LINK", "https://yoursite.com/files/catalog.pdf"),
                    "filename": "catalog.pdf",
                    "caption": "Full catalog with all products 😊"
                },
                "invoice": {
                    "link": os.getenv("SAMPLE_INVOICE_LINK", "https://yoursite.com/files/invoice-sample.pdf"),
                    "filename": "invoice.pdf",
                    "caption": "Here's your invoice"
                }
            }
            if doc_type in doc_map:
                d = doc_map[doc_type]
                # Validate public HTTPS (Meta policy)
                if not d["link"].startswith("https://"):
                    print(f"❌ Doc link not HTTPS, skipping per policy: {d['link']}")
                else:
                    print(f"📄 Auto-sending {d['filename']} to {from_number} via document payload (within 24h window)")
                    res = client.send_document(from_number, d["link"], d["filename"], d["caption"], human_like=True)
                    log_message(from_number, "outbound", "document", d["caption"], filename=d["filename"], status=res["status"], wa_id=res.get("response", {}).get("messages", [{}])[0].get("id", "") if res["status"]=="sent" else "")
        
        # 7. Notify admin for important keywords
        if ADMIN_NOTIFY_NUMBER and any(kw in text.lower() for kw in ["urgent", "complaint", "payment", "order"]):
            # Admin notification - use template if outside window
            if is_in_24h_window(ADMIN_NOTIFY_NUMBER):
                client.send_text(ADMIN_NOTIFY_NUMBER, f"🔔 Important from {contact_name or from_number}: {text[:200]}\nReplied: {reply_text[:200]}", human_like=False)
            else:
                client.send_template_text(ADMIN_NOTIFY_NUMBER, TEMPLATES["customer_service_followup"]["name"], "en_US", [f"Important from {from_number}", text[:100]])
    
    except Exception as e:
        print(f"❌ handle_text_message error: {e}")
        import traceback
        traceback.print_exc()
        # On error, trigger human handoff rather than fail silently
        trigger_human_handoff(from_number, reason=f"AI error: {str(e)}")

def handle_media_message(from_number: str, msg_type: str, filename: str, contact_name: str, msg_id: str):
    try:
        time.sleep(human.read_delay())
        try:
            client.mark_as_read(msg_id)
        except:
            pass
        
        if is_ai_paused(from_number):
            notify_human_dashboard(from_number, f"Sent {msg_type}: {filename}", contact_name, "Media while AI paused")
            return
        
        reply = f"Got your {msg_type}! 📎 Let me check it for {BUSINESS_NAME} support"
        time.sleep(random.uniform(1, 2.5))
        client.send_text(from_number, reply, human_like=True)
        log_message(from_number, "outbound", "text", reply, status="sent")
    
    except Exception as e:
        print(f"❌ handle_media_message error: {e}")

# === COMPLIANT MANUAL ENDPOINTS ===

@app.post("/send/text")
async def api_send_text(request: Request):
    """
    Single text - only allowed within 24h window per Meta policy
    For outside window, use /send/template/text
    """
    data = await request.json()
    to = data.get("to")
    message = data.get("message")
    if not to or not message:
        return JSONResponse({"error": "to and message required"}, status_code=400)
    
    # Compliance check
    if not is_in_24h_window(to):
        return JSONResponse({
            "error": "Outside 24h window - free text not allowed per Meta policy",
            "policy": "Must use pre-approved template for business-initiated outside 24h",
            "solution": "Use POST /send/template/text with template name",
            "24h_window": False
        }, status_code=400)
    
    if is_ai_paused(to):
        return JSONResponse({"error": "AI paused for this number - human handoff active", "paused": True}, status_code=400)
    
    results = client.send_text(to, message, human_like=data.get("human_like", True))
    return JSONResponse({"results": results, "compliant": True, "24h_window": True})

@app.post("/send/template/text")
async def api_send_template_text(request: Request):
    """Compliant bulk/business-initiated text via template"""
    data = await request.json()
    to = data.get("to")
    template_name = data.get("template_name") or TEMPLATES["bulk_text_with_optout"]["name"]
    variables = data.get("variables", [])
    language = data.get("language", "en_US")
    
    if not to:
        return JSONResponse({"error": "to required"}, status_code=400)
    
    if COMPLIANCE["REQUIRE_OPT_IN_FOR_BULK"] and not is_opted_in(to):
        return JSONResponse({
            "error": "No opt-in - bulk requires explicit consent per Meta policy",
            "policy": "Customers must opt-in via web form, checkbox, or previous chat",
            "solution": "Get opt-in or use within 24h window after user messages"
        }, status_code=400)
    
    result = client.send_template_text(to, template_name, language, variables)
    log_message(to, "outbound", "text", f"Template {template_name} vars={variables}", status=result["status"], is_template=1, template_name=template_name)
    return JSONResponse(result)

@app.post("/send/document")
async def api_send_document(request: Request):
    """Single document - safe within 24h window"""
    data = await request.json()
    to = data.get("to")
    link = data.get("link")
    filename = data.get("filename")
    caption = data.get("caption", "")
    if not all([to, link, filename]):
        return JSONResponse({"error": "to, link, filename required"}, status_code=400)
    
    if not link.startswith("https://"):
        return JSONResponse({"error": "Document must be public HTTPS per Meta policy"}, status_code=400)
    
    if not is_in_24h_window(to):
        return JSONResponse({
            "error": "Outside 24h window - raw document not recommended",
            "policy": "For bulk docs outside 24h, must use Media Message Template with document header",
            "solution": "Use POST /send/template/document"
        }, status_code=400)
    
    result = client.send_document(to, link, filename, caption, human_like=data.get("human_like", True))
    return JSONResponse(result)

@app.post("/send/template/document")
async def api_send_template_document(request: Request):
    """Compliant bulk document via Media Template"""
    data = await request.json()
    to = data.get("to")
    link = data.get("link")
    filename = data.get("filename", "document.pdf")
    template_name = data.get("template_name") or TEMPLATES["bulk_document"]["name"]
    variables = data.get("variables", [])
    language = data.get("language", "en_US")
    
    if not all([to, link]):
        return JSONResponse({"error": "to and link required"}, status_code=400)
    
    if not link.startswith("https://"):
        return JSONResponse({"error": "Document must be public HTTPS"}, status_code=400)
    
    if COMPLIANCE["REQUIRE_OPT_IN_FOR_BULK"] and not is_opted_in(to):
        return JSONResponse({"error": "No opt-in for bulk docs - explicit consent required"}, status_code=400)
    
    result = client.send_template_document(to, template_name, link, filename, language, variables)
    log_message(to, "outbound", "document", f"Template {template_name} doc={filename}", filename=filename, status=result["status"], is_template=1, template_name=template_name)
    return JSONResponse(result)

@app.post("/send/bulk/template/text")
async def api_bulk_template_text(request: Request, background_tasks: BackgroundTasks):
    """
    COMPLIANT BULK TEXT - Template only with opt-in
    Body: {"numbers": [...], "template_name": "...", "variable_sets": [["name","order123"], ...]}
    """
    data = await request.json()
    numbers = data.get("numbers", [])
    template_name = data.get("template_name") or TEMPLATES["bulk_text_with_optout"]["name"]
    variable_sets = data.get("variable_sets", [])
    language = data.get("language", "en_US")
    
    if not numbers:
        return JSONResponse({"error": "numbers array required"}, status_code=400)
    
    # Filter opt-in
    if COMPLIANCE["REQUIRE_OPT_IN_FOR_BULK"]:
        opted_in_numbers = [n for n in numbers if is_opted_in(n)]
        skipped = len(numbers) - len(opted_in_numbers)
        if skipped > 0:
            print(f"⚠️ {skipped} numbers skipped - no opt-in (Meta policy)")
    else:
        opted_in_numbers = numbers
    
    background_tasks.add_task(client.bulk_send_template, opted_in_numbers, template_name, language, variable_sets, False)
    return JSONResponse({
        "status": "started",
        "total_requested": len(numbers),
        "total_opted_in": len(opted_in_numbers),
        "skipped_no_optin": len(numbers) - len(opted_in_numbers),
        "template": template_name,
        "compliant": True,
        "policy": "Template-only with opt-in + STOP button"
    })

@app.post("/send/bulk/template/docs")
async def api_bulk_template_docs(request: Request, background_tasks: BackgroundTasks):
    """
    COMPLIANT BULK DOCS - Media Template with document header
    Body: {"rows": [{"phone":"...","doc_link":"https://...","filename":"...","variables":[...]}, ...], "template_name": "..."}
    """
    data = await request.json()
    rows = data.get("rows", [])
    template_name = data.get("template_name") or TEMPLATES["bulk_document"]["name"]
    language = data.get("language", "en_US")
    
    if not rows:
        return JSONResponse({"error": "rows required"}, status_code=400)
    
    # Validate all links HTTPS
    for r in rows:
        link = r.get("doc_link") or r.get("link", "")
        if not link.startswith("https://"):
            return JSONResponse({"error": f"All doc links must be public HTTPS. Invalid: {link}"}, status_code=400)
    
    background_tasks.add_task(client.bulk_send_template_documents, rows, template_name, language, False)
    return JSONResponse({
        "status": "started",
        "total": len(rows),
        "template": template_name,
        "compliant": True,
        "policy": "Media template with document header + dynamic URL mapping"
    })

# Legacy endpoints - now warn about compliance
@app.post("/send/bulk/text")
async def api_bulk_text_legacy(request: Request):
    return JSONResponse({
        "error": "NON-COMPLIANT endpoint - bulk free text blocked per Meta policy",
        "policy": "Bulk/business-initiated must use pre-approved template",
        "solution": "Use POST /send/bulk/template/text with template name and variables {{1}}, {{2}}",
        "example": {
            "numbers": ["9198..."],
            "template_name": TEMPLATES["bulk_text_with_optout"]["name"],
            "variable_sets": [["John", "Order123"]]
        }
    }, status_code=400)

@app.post("/send/bulk/docs")
async def api_bulk_docs_legacy(request: Request):
    return JSONResponse({
        "error": "NON-COMPLIANT endpoint - raw bulk doc blocked",
        "policy": "Cannot send raw standalone document in bulk. Must use Media Message Template with document header",
        "solution": "Use POST /send/bulk/template/docs with template that has document header",
        "example": {
            "rows": [{"phone": "9198...", "doc_link": "https://.../file.pdf", "filename": "price.pdf", "variables": ["John"]}],
            "template_name": TEMPLATES["bulk_document"]["name"]
        }
    }, status_code=400)

@app.get("/handoff-queue")
async def get_handoff():
    queue = get_handoff_queue()
    return {"handoff_queue": queue, "count": len(queue), "policy": "Human handoff required when AI fails or user asks human"}

@app.post("/handoff-queue/{phone}/resolve")
async def resolve_handoff_endpoint(phone: str):
    resolve_handoff(phone)
    return {"status": "resolved", "phone": phone, "ai_resumed": True}

@app.get("/")
async def root():
    return {
        "status": f"WhatsApp Human Agent COMPLIANT Running 🤖 for {BUSINESS_NAME}",
        "compliance": {
            "business_specific_ai": "✅ Restricted to business operations only, not general-purpose",
            "24h_window": "✅ Free text only within 24h of user message",
            "bulk_policy": "✅ Template-only for bulk/business-initiated with opt-in + STOP button",
            "doc_policy": "✅ Single doc via HTTPS within 24h, bulk doc via Media Template with document header",
            "human_handoff": "✅ TRIGGER_HUMAN_HANDOFF routing loop + pause AI",
            "rate_limiter": "✅ 2-5s min delay + human gaps 18-45s + batch breaks"
        },
        "phone_id": os.getenv("PHONE_NUMBER_ID"),
        "templates_required": TEMPLATES,
        "endpoints": {
            "webhook": "/webhook",
            "single_text_24h": "POST /send/text (only within 24h)",
            "single_doc_24h": "POST /send/document (only within 24h, HTTPS)",
            "compliant_bulk_text": "POST /send/bulk/template/text (template + opt-in)",
            "compliant_bulk_doc": "POST /send/bulk/template/docs (media template + dynamic URL)",
            "template_text": "POST /send/template/text",
            "template_doc": "POST /send/template/document",
            "handoff_queue": "GET /handoff-queue"
        }
    }

@app.get("/stats")
async def stats():
    from database import get_conn
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM messages")
    total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as today FROM messages WHERE date(timestamp) = date('now')")
    today = cur.fetchone()["today"]
    cur.execute("SELECT COUNT(*) as contacts FROM contacts")
    contacts = cur.fetchone()["contacts"]
    cur.execute("SELECT COUNT(*) as opted_in FROM contacts WHERE opted_in=1 AND blocked=0")
    opted_in = cur.fetchone()["opted_in"]
    cur.execute("SELECT COUNT(*) as handoff FROM handoff_queue WHERE resolved=0")
    handoff = cur.fetchone()["handoff"]
    conn.close()
    return {
        "total_messages": total,
        "today": today,
        "contacts": contacts,
        "opted_in": opted_in,
        "handoff_active": handoff,
        "sent_this_hour": client.sent_this_hour,
        "sent_this_day": client.sent_this_day,
        "total_sent_session": client.total_sent,
        "compliance": "All bulk via templates, opt-in enforced, 24h window enforced"
    }

@app.get("/compliance-audit")
async def compliance_audit():
    """Show compliance status"""
    return {
        "policy_checks": {
            "1_general_vs_business": {
                "status": "COMPLIANT",
                "implementation": "AI system prompt restricts to business goals only, blocks general queries with 'I am only programmed to assist with...'",
                "code": "compliance.py:is_general_purpose_query + ai_agent.py:get_compliant_system_prompt"
            },
            "2_single_vs_bulk_text": {
                "single": "COMPLIANT - Free custom text allowed within 24h window, webhook -> AI -> answer",
                "bulk": "COMPLIANT - Pre-approved template only, AI populates {{1}}, {{2}}, opt-in mandatory, STOP button included",
                "code": "whatsapp_client.py:send_template_text + bulk_send_template"
            },
            "3_single_vs_bulk_doc": {
                "single": "COMPLIANT - Within 24h, public HTTPS link, tool/function call",
                "bulk": "COMPLIANT - Media Message Template with document header, dynamic URL mapping per user",
                "code": "whatsapp_client.py:send_template_document + bulk_send_template_documents"
            },
            "4_prompt_guardrails": {
                "status": "COMPLIANT",
                "system_prompt": f"You are task-oriented for {BUSINESS_NAME}, sole objective {TEMPLATES}",
                "safety": "Blocks politics, medical, illegal, competitors. Triggers [TRIGGER_HUMAN_HANDOFF] on frustration/human request",
                "code": "compliance.py:get_compliant_system_prompt + ai_agent.py"
            },
            "5_human_handoff": {
                "status": "COMPLIANT",
                "routing": "If AI contains [TRIGGER_HUMAN_HANDOFF], route to Slack/CRM dashboard, pause AI for phone",
                "code": "app.py:handle_text_message + database.py:handoff_queue"
            },
            "6_rate_limiter": {
                "status": "COMPLIANT",
                "delay": "2-5s min between bulk (Meta) + 18-45s human gaps + 3-8min batch breaks",
                "code": "whatsapp_client.py:bulk_send_template + human_behavior.py"
            }
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
