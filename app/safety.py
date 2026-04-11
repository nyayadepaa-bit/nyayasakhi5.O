"""
app/safety.py
--------------
Safety, intent detection, domain classification, and risk assessment
for the Women Safety Legal Advisor.

Pipeline:
    1. Intent Detection:   greeting / legal_query / emergency / off_topic
    2. Domain Classification: criminal / workplace / domestic / cyber / procedure
    3. Risk Assessment:    detect urgent/dangerous situations
    4. Content Safety:     block harmful/manipulative queries
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Intent Detection ──────────────────────────────────────
GREETING_PATTERN = re.compile(
    r"^(hi+|hey+|hello+|good\s*(morning|evening|afternoon|night)"
    r"|namaste|namaskar|how\s*are\s*you|thank\s*you|thanks).*$",
    re.IGNORECASE,
)

CONVERSATIONAL_PATTERNS = [
    r"^my\s*name\s*(is|'s)",
    r"^i\s*am\s+[a-z]+$",
    r"^i'?m\s+[a-z]+$",
    r"^(who|what)\s+are\s+you",
    r"^(ok|okay|sure|alright|got\s*it|understood|fine)",
    r"^(yes|no|maybe|not\s*sure)",
    r"^(please|pls)\s+help",
    r"^tell\s*me\s*(about|more)",
    r"^what\s*can\s*you\s*do",
    r"^(can|could)\s*you\s*help",
]

OFF_TOPIC_INDICATORS = [
    r"recipe", r"weather", r"movie", r"cricket", r"song",
    r"joke", r"game", r"homework", r"essay\s*on",
    r"code\s*for", r"program\s*to", r"write\s*a\s*story",
]

LEGAL_INDICATORS = [
    r"law", r"legal", r"court", r"case", r"police", r"fir",
    r"complaint", r"judge", r"bail", r"arrest", r"crime",
    r"fraud", r"cheated", r"harassment", r"divorce", r"dowry",
    r"violence", r"abuse", r"ipc", r"crpc", r"bns", r"bnss",
    r"rights?", r"lawyer", r"advocate", r"section\s*\d+",
    r"property", r"contract", r"consumer", r"defamation",
    r"petition", r"appeal", r"custody", r"maintenance",
    r"alimony", r"cybercrime", r"stalking", r"molestation",
    r"rape", r"posh", r"vishakha", r"help\s*me", r"what\s*should\s*i\s*do",
    r"how\s*to\s*(file|report|complain)", r"POCSO", r"acid\s*attack",
    r"threat", r"blackmail", r"trafficking", r"forced",
    r"domestic", r"husband", r"wife", r"in-?laws?",
    r"protection\s*order", r"women.*commission", r"NCW",
    r"helpline", r"compensation", r"damages", r"penalty",
    # Situational problem indicators
    r"someone\s*(keeps?|is)", r"(he|she|they)\s*(keeps?|is|are)",
    r"messaging\s*me", r"calling\s*me", r"following\s*me",
    r"touching\s*me", r"hitting\s*me", r"beating\s*me",
    r"harassing", r"bothering\s*me", r"troubling\s*me",
    r"scared\s*of", r"afraid\s*of", r"threatened",
    r"i\s*(need|want)\s*help", r"please\s*help",
    r"what\s*(can|do)\s*i\s*do", r"is\s*this\s*(legal|illegal|wrong)",
    r"(my|the)\s*(boss|manager|colleague|neighbor)",
    r"uncomfortable", r"inappropriate", r"unwanted",
]


def detect_intent(text: str) -> str:
    """
    Classify user intent.

    Returns: 'greeting', 'conversational', 'legal_query', 'emergency', 'off_topic'
    """
    text_lower = text.lower().strip()

    # Check greeting
    if GREETING_PATTERN.fullmatch(text_lower):
        return "greeting"

    # Check emergency
    if is_emergency(text_lower):
        return "emergency"

    # Check conversational (name, intro, generic)
    for pattern in CONVERSATIONAL_PATTERNS:
        if re.search(pattern, text_lower):
            # But if it ALSO has legal keywords, treat as legal
            has_legal = any(re.search(p, text_lower) for p in LEGAL_INDICATORS)
            if not has_legal:
                return "conversational"

    # Check legal relevance
    for pattern in LEGAL_INDICATORS:
        if re.search(pattern, text_lower):
            return "legal_query"

    # Check off-topic
    for pattern in OFF_TOPIC_INDICATORS:
        if re.search(pattern, text_lower):
            return "off_topic"

    # Short queries with no legal keywords → conversational
    # Only if they don't describe a problem
    if len(text_lower.split()) <= 4:
        return "conversational"

    # Default: treat as legal query (benefit of doubt for longer text)
    return "legal_query"


# ── Domain Classification ─────────────────────────────────
DOMAIN_PATTERNS = {
    "domestic_violence": [
        r"domestic\s*violence", r"DV\s*Act", r"protection\s*of\s*women",
        r"husband.*beat", r"husband.*abuse", r"in-?laws?.*harass",
        r"dowry", r"498[\s-]?A", r"streedhan", r"cruelty.*husband",
        r"matrimonial", r"shared\s*household", r"protection\s*order",
        r"batter", r"thrown\s*out.*house",
    ],
    "workplace_harassment": [
        r"sexual\s*harassment.*work", r"POSH", r"vishakha",
        r"boss.*harass", r"colleague.*touch", r"office.*inapp",
        r"ICC", r"internal\s*complaints?\s*committee",
        r"workplace\s*safety", r"employer", r"coworker",
        r"promotion.*sex", r"quid\s*pro\s*quo",
    ],
    "cyber_crime": [
        r"cyber", r"online.*harass", r"online.*abuse",
        r"IT\s*Act", r"revenge\s*porn", r"morphing", r"deep\s*fake",
        r"social\s*media.*threat", r"whatsapp.*threat",
        r"fb.*harass", r"instagram.*stalk", r"trolling",
        r"obscene.*photo", r"blackmail.*photo", r"intimate.*video",
    ],
    "criminal_law": [
        r"rape", r"molestation", r"sexual\s*assault", r"eve\s*teasing",
        r"stalking", r"voyeurism", r"acid\s*attack",
        r"kidnap", r"abduction", r"trafficking", r"outrag.*modesty",
        r"ipc", r"bns", r"section\s*3[0-9]{2}", r"section\s*37[0-9]",
        r"murder", r"attempt.*murder", r"threat.*kill",
    ],
    "reporting_procedure": [
        r"how\s*to\s*(file|register|lodge)", r"FIR", r"first\s*information",
        r"police\s*complaint", r"zero\s*fir", r"e[\s-]?fir",
        r"where\s*to\s*report", r"women.*helpline", r"NCW",
        r"women.*commission", r"legal\s*aid", r"free\s*lawyer",
        r"magistrate.*complaint", r"PIL",
    ],
    "case_duration": [
        r"how\s*long.*case", r"time.*take.*court", r"duration",
        r"fast\s*track", r"pendency", r"disposed",
        r"when.*judgment", r"time\s*limit", r"limitation",
    ],
}


def classify_domain(text: str) -> list[str]:
    """
    Classify query into legal domain(s) for namespace routing.

    Returns: List of matching domains, most relevant first.
    """
    text_lower = text.lower()
    scores = {}

    for domain, patterns in DOMAIN_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, text_lower))
        if score > 0:
            scores[domain] = score

    if not scores:
        return ["general"]

    sorted_domains = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [d for d, _ in sorted_domains]


# ── Risk Assessment ───────────────────────────────────────
EMERGENCY_PATTERNS = [
    r"going\s*to\s*kill", r"threat.*life", r"life.*danger",
    r"being\s*beaten", r"beating\s*me", r"attacked",
    r"help\s*me\s*please", r"urgent.*help", r"emergency",
    r"suicid", r"want\s*to\s*die", r"end.*life",
    r"kidnapped", r"confined", r"locked\s*in",
    r"someone.*following", r"being\s*stalked.*now",
    r"acid.*throw", r"right\s*now", r"happening\s*now",
    r"husband.*knife", r"husband.*gun", r"hit.*head",
    r"bleeding", r"injured", r"unconscious",
]

def build_trust_block(name: str = "", situation: str = "") -> str:
    """
    Generate a warm, personalised trust-building acknowledgement.
    Uses the user's name and situation so every response feels like a direct,
    human conversation — not a generic template.
    """
    name_part  = f", {name.strip()}" if name and name.strip().lower() not in ("user", "friend", "") else ""
    sit_phrase = ""
    if situation:
        s = situation.lower()
        if "domestic" in s or "husband" in s or "abuse" in s:
            sit_phrase = "what you are going through at home"
        elif "workplace" in s or "boss" in s or "office" in s:
            sit_phrase = "the harassment you are facing at work"
        elif "cyber" in s or "online" in s:
            sit_phrase = "the online harassment you are dealing with"
        elif "dowry" in s:
            sit_phrase = "the dowry-related pressure you are under"
        elif "maintenance" in s or "alimony" in s:
            sit_phrase = "your maintenance rights situation"
        elif "stalking" in s:
            sit_phrase = "the stalking and threat you are experiencing"
        else:
            sit_phrase = "everything you have shared with me"

    return f"""
---

> 🛡️ **I hear you{name_part}. I understand {sit_phrase or "your situation"}.**
>
> I have read every detail you shared carefully. Right now, I am cross-referencing your specific facts against documented court precedents, applicable Indian laws, and real judgment patterns — to give you an analysis that actually fits *your* case, not a copy-paste answer.
>
> **Here is exactly what I am working on for you:**
> - Understanding your legal position and which laws protect you
> - Predicting the most likely outcomes based on cases similar to yours
> - Identifying what documents and steps will strengthen your case
> - Explaining your options honestly — so you can decide what to do next
>
> This will take just a moment. Everything you tell me stays completely confidential.

---
"""


# Backward-compatible alias used in imports across the codebase
EMERGENCY_RESOURCES = build_trust_block()


def is_emergency(text: str) -> bool:
    """Detect if the query indicates an emergency/dangerous situation."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in EMERGENCY_PATTERNS)


def get_risk_assessment(text: str) -> dict:
    """
    Assess risk level of the query.

    Returns:
        dict with 'level' (low/medium/high/emergency),
        'emergency_resources' (str or None),
        'flags' (list of detected risk indicators)
    """
    text_lower = text.lower()

    flags = [p for p in EMERGENCY_PATTERNS if re.search(p, text_lower)]

    if len(flags) >= 2:
        return {
            "level": "emergency",
            "emergency_resources": EMERGENCY_RESOURCES,
            "flags": flags,
        }
    elif len(flags) == 1:
        return {
            "level": "high",
            "emergency_resources": EMERGENCY_RESOURCES,
            "flags": flags,
        }
    elif is_emergency(text_lower):
        return {
            "level": "high",
            "emergency_resources": EMERGENCY_RESOURCES,
            "flags": flags,
        }

    # Check for sensitive topics
    sensitive = [
        r"rape", r"molestation", r"sexual\s*assault",
        r"acid", r"trafficking", r"child\s*abuse",
    ]
    sensitive_flags = [p for p in sensitive if re.search(p, text_lower)]
    if sensitive_flags:
        return {
            "level": "medium",
            "emergency_resources": None,
            "flags": sensitive_flags,
        }

    return {"level": "low", "emergency_resources": None, "flags": []}


# ── Content Safety ────────────────────────────────────────
HARMFUL_PATTERNS = [
    r"how\s*to\s*(commit|do).*crime",
    r"how\s*to\s*avoid.*punishment",
    r"how\s*to\s*(hide|destroy)\s*evidence",
    r"how\s*to\s*(harass|stalk|abuse)",
    r"how\s*to\s*file\s*false\s*(case|fir|complaint)",
    r"loophole.*exploit",
    r"how\s*to\s*escape\s*law",
]


def is_harmful_query(text: str) -> bool:
    """Check if the query attempts to misuse the legal system."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in HARMFUL_PATTERNS)


def get_safety_response(intent: str, risk: dict) -> Optional[str]:
    """
    Get a safety response if needed.

    Returns:
        Response string if safety intervention needed, None otherwise.
    """
    if intent == "greeting":
        return (
            "🙏 **Namaste!** I am **NyayaDepaaAI**, your Women Safety & Rights Legal Advisor.\n\n"
            "I can help you with:\n"
            "- 🏠 Domestic violence rights & protection orders\n"
            "- 💼 Workplace sexual harassment (POSH)\n"
            "- 🌐 Cyber harassment & online safety\n"
            "- 📋 Filing FIRs and police complaints\n"
            "- ⚖️ Understanding your legal rights under Indian law\n\n"
            "Please describe your situation and I will provide detailed legal guidance.\n\n"
            "⚖️ *This is informational guidance only, not a substitute for professional legal counsel.*"
        )

    if intent == "conversational":
        return (
            "🙏 Thank you for reaching out! I am **NyayaDepaaAI**, your AI companion for women's legal safety.\n\n"
            "I'm here to help you understand your legal rights and protections under Indian law. "
            "To provide the best guidance, could you please tell me —\n\n"
            "**What legal issue or situation do you need help with?**\n\n"
            "For example:\n"
            "- *\"I am facing harassment at my workplace\"*\n"
            "- *\"My husband is abusing me, what can I do?\"*\n"
            "- *\"How do I file a cybercrime complaint?\"*\n\n"
            "The more details you share, the better I can guide you. Your information is safe with me. 🛡️"
        )

    if intent == "off_topic":
        return (
            "⚖️ I am a **Women Safety Legal Advisor** specialized in Indian law. "
            "I can only help with legal matters related to women's safety and rights.\n\n"
            "Examples of what I can help with:\n"
            "- *\"My husband is threatening me, what are my legal options?\"*\n"
            "- *\"How to file a sexual harassment complaint at work?\"*\n"
            "- *\"Someone is sharing my photos online without consent\"*"
        )

    return None


# ── Emotional State Detection ─────────────────────────────
EMOTION_PATTERNS = {
    "fearful": [
        r"scared", r"afraid", r"fear", r"terrified", r"frightened",
        r"shaking", r"trembling", r"can't sleep", r"nightmares",
        r"i don'?t feel safe", r"not safe", r"unsafe",
    ],
    "distressed": [
        r"crying", r"can'?t stop cry", r"broken", r"shattered",
        r"devastated", r"helpless", r"hopeless", r"desperate",
        r"don'?t know what to do", r"lost", r"confused",
        r"overwhelmed", r"numb", r"shock",
    ],
    "angry": [
        r"angry", r"furious", r"disgusted", r"outraged",
        r"fed up", r"had enough", r"can'?t take", r"frustrated",
        r"want justice", r"punish",
    ],
    "urgent": [
        r"right now", r"immediately", r"asap", r"today",
        r"happening now", r"currently", r"just happened",
        r"need help fast", r"urgent", r"emergency", r"soon",
    ],
    "calm": [
        r"curious", r"wondering", r"want to know", r"interested",
        r"just asking", r"general question", r"information",
        r"can you tell me", r"what are",
    ],
}


def detect_emotional_state(text: str) -> str:
    """
    Detect the emotional state of the user for tone personalization.

    Returns: 'fearful', 'distressed', 'angry', 'urgent', 'calm', 'neutral'
    """
    text_lower = text.lower()
    scores = {}

    for emotion, patterns in EMOTION_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, text_lower))
        if score > 0:
            scores[emotion] = score

    if not scores:
        return "neutral"

    return max(scores, key=scores.get)

