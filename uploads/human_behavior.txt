"""
human_behavior.py - Makes the bot act 100% like a real human on WhatsApp
Anti-ban + Human timing engine
"""
import random
import time
import math
from datetime import datetime

class HumanBehavior:
    """
    Simulates REAL human WhatsApp usage patterns to avoid Meta bans.
    """
    # Typing speed: average human 40-70 WPM = 3.5-5.5 chars/sec
    CHARS_PER_SECOND_MIN = 3.0
    CHARS_PER_SECOND_MAX = 6.5
    
    # Human thinking / pausing
    THINK_PAUSE_MIN = 0.8
    THINK_PAUSE_MAX = 2.8

    def __init__(self):
        self.last_send_time = 0

    @staticmethod
    def typing_delay(text: str) -> float:
        """Calculate realistic typing time based on text length like a human"""
        if not text:
            return random.uniform(0.8, 1.5)
        
        char_count = len(text)
        # Base typing speed random per message (human speed varies)
        cps = random.uniform(HumanBehavior.CHARS_PER_SECOND_MIN, HumanBehavior.CHARS_PER_SECOND_MAX)
        base = char_count / cps
        
        # Longer messages -> human slows down, makes typos correction pause
        if char_count > 100:
            base *= random.uniform(1.1, 1.4)
        if char_count > 250:
            base *= random.uniform(1.15, 1.5)
        
        # Random micro pauses (thinking, checking phone)
        jitter = random.uniform(0.5, 2.2)
        delay = base + jitter
        
        # Clamp to human realistic: min 1.2s, max 14s per message bubble
        delay = max(1.2, min(delay, 14.0))
        return round(delay, 2)

    @staticmethod
    def read_delay() -> float:
        """Time human takes to read incoming message before replying"""
        return round(random.uniform(1.0, 3.5), 2)

    @staticmethod
    def between_messages_delay(is_same_person: bool = True) -> float:
        """Pause between consecutive message bubbles"""
        if is_same_person:
            # Human sends 2-3 messages in a row with short gaps
            return round(random.uniform(1.2, 3.8), 2)
        else:
            # Switching to different chat
            return round(random.uniform(4.5, 12.0), 2)

    @staticmethod
    def between_contacts_delay() -> float:
        """Pause between different people in bulk mode - CRITICAL anti-ban"""
        # Real human needs to search contact, open chat, etc
        return round(random.uniform(18.0, 45.0), 2)

    @staticmethod
    def between_batches_delay() -> float:
        """Long break after a batch (like human takes coffee break)"""
        return round(random.uniform(180.0, 480.0), 2)  # 3-8 minutes

    @staticmethod
    def document_upload_delay(file_size_mb: float = 1.0) -> float:
        """Simulate human selecting file, waiting for upload"""
        base = random.uniform(2.5, 5.5)
        size_factor = min(file_size_mb * 0.8, 6.0)
        return round(base + size_factor + random.uniform(0, 1.5), 2)

    @staticmethod
    def split_long_message(text: str, max_len: int = 320) -> list:
        """
        Real humans don't send 1000 char paragraph.
        They split into 2-4 bubbles naturally at sentences.
        """
        if len(text) <= max_len:
            return [text]
        
        # Split by sentences
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        bubbles = []
        current = ""
        
        for sent in sentences:
            if len(current) + len(sent) + 1 <= max_len:
                current = (current + " " + sent).strip() if current else sent
            else:
                if current:
                    bubbles.append(current)
                # If single sentence too long, hard split by words
                if len(sent) > max_len:
                    words = sent.split()
                    tmp = ""
                    for w in words:
                        if len(tmp) + len(w) + 1 <= max_len:
                            tmp = (tmp + " " + w).strip() if tmp else w
                        else:
                            bubbles.append(tmp)
                            tmp = w
                    if tmp:
                        current = tmp
                    else:
                        current = ""
                else:
                    current = sent
        
        if current:
            bubbles.append(current)
        
        # If still 1 bubble but very long, force split
        if len(bubbles) == 1 and len(bubbles[0]) > max_len * 1.5:
            text = bubbles[0]
            bubbles = [text[i:i+max_len] for i in range(0, len(text), max_len)]
        
        return bubbles

    @staticmethod
    def random_emoji_for_context() -> str:
        """Optional human touch - not every time"""
        if random.random() < 0.28:  # 28% chance
            return random.choice(["", "", "👍", "🙏", "😊", "📄", ""])
        return ""

    @staticmethod
    def should_take_long_break(messages_sent: int) -> bool:
        """Human gets tired"""
        # Every 22-30 messages, take a longer pause
        return messages_sent > 0 and messages_sent % random.randint(22, 30) == 0

    @staticmethod
    def get_active_hours_factor() -> float:
        """Humans don't send at 3am consistently - add jitter"""
        hour = datetime.now().hour
        # If it's night time (11pm-6am), add extra random delay to simulate less activity
        if 23 <= hour or hour <= 6:
            return random.uniform(1.5, 2.5)
        return 1.0

# Global instance
human = HumanBehavior()
