"""
app/clarifier.py
-----------------
Clarification Intelligence Layer.

Detects when a query lacks critical legal context and generates
personalized clarification suggestions instead of producing an
incomplete answer.

Returns structured output:
    {
        "needs_clarification": True/False,
        "message": "Personalized question text",
        "suggestions": [
            {"label": "Display text", "intent": "intent_code", "expansion": "..."}
        ],
        "missing_factors": ["relationship", "location", ...]
    }
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Critical Legal Context Factors ────────────────────────
# Each factor has: detection patterns (if present, factor is satisfied)
# and suggestion generators (if absent, these suggestions are offered)

LEGAL_FACTORS = {
    "relationship": {
        "description": "Relationship with the offender",
        "indicators": [
            r"husband", r"wife", r"partner", r"boyfriend", r"ex[\s-]",
            r"colleague", r"boss", r"manager", r"supervisor", r"coworker",
            r"stranger", r"neighbour", r"neighbor", r"relative",
            r"father[\s-]?in[\s-]?law", r"mother[\s-]?in[\s-]?law",
            r"in[\s-]?laws?", r"brother", r"uncle", r"landlord",
            r"friend", r"classmate", r"teacher", r"professor",
            r"known\s*person", r"unknown\s*person", r"family",
        ],
        "suggestions": [
            {"label": "It's my husband / partner", "intent": "rel_spouse", "expansion": "by my husband/partner"},
            {"label": "It's a colleague / boss at work", "intent": "rel_workplace", "expansion": "by a colleague or superior at my workplace"},
            {"label": "It's a family member / in-laws", "intent": "rel_family", "expansion": "by a family member or in-laws"},
            {"label": "It's a stranger / unknown person", "intent": "rel_stranger", "expansion": "by an unknown person/stranger"},
            {"label": "It's someone I know (friend/neighbor)", "intent": "rel_acquaintance", "expansion": "by someone I know personally"},
        ],
    },
    "location": {
        "description": "Where the incident occurred",
        "indicators": [
            r"home", r"house", r"workplace", r"office", r"online",
            r"public\s*place", r"street", r"transport", r"bus", r"metro",
            r"school", r"college", r"university", r"market",
            r"cyber", r"social\s*media", r"whatsapp", r"instagram",
            r"facebook", r"internet", r"phone",
        ],
        "suggestions": [
            {"label": "At home / in my house", "intent": "loc_home", "expansion": "at my home/residence"},
            {"label": "At my workplace / office", "intent": "loc_work", "expansion": "at my workplace"},
            {"label": "Online / on social media", "intent": "loc_online", "expansion": "online/on social media"},
            {"label": "In a public place", "intent": "loc_public", "expansion": "in a public place"},
        ],
    },
    "incident_type": {
        "description": "Type of incident",
        "indicators": [
            r"beat", r"hit", r"slap", r"kick", r"punch", r"push",
            r"threat", r"threaten", r"blackmail",
            r"touch", r"grope", r"molest", r"rape", r"assault",
            r"stalk", r"follow", r"spy",
            r"abuse", r"harass", r"bully",
            r"message", r"call", r"photo", r"video", r"morphing",
            r"dowry", r"demand", r"money",
            r"verbal\s*abuse", r"mental\s*torture",
            r"thrown\s*out", r"locked", r"confined",
        ],
        "suggestions": [
            {"label": "Physical violence (hitting, pushing)", "intent": "type_physical", "expansion": "involving physical violence"},
            {"label": "Verbal abuse or threats", "intent": "type_verbal", "expansion": "involving verbal abuse and threats"},
            {"label": "Sexual harassment / assault", "intent": "type_sexual", "expansion": "involving sexual harassment"},
            {"label": "Stalking or being followed", "intent": "type_stalking", "expansion": "involving stalking"},
            {"label": "Online threats / morphing / blackmail", "intent": "type_cyber", "expansion": "involving online harassment/blackmail"},
            {"label": "Financial abuse / dowry demands", "intent": "type_financial", "expansion": "involving financial abuse or dowry demands"},
        ],
    },
    "evidence": {
        "description": "Evidence availability",
        "indicators": [
            r"evidence", r"proof", r"screenshot", r"recording",
            r"witness", r"photo", r"video", r"chat", r"message",
            r"medical\s*report", r"doctor", r"hospital",
            r"cctv", r"camera", r"document", r"paper",
        ],
        "suggestions": [
            {"label": "Yes, I have screenshots / messages", "intent": "evi_digital", "expansion": ". I have digital evidence like screenshots and messages"},
            {"label": "Yes, I have witnesses", "intent": "evi_witness", "expansion": ". There are witnesses to the incident"},
            {"label": "Yes, I have medical records", "intent": "evi_medical", "expansion": ". I have medical records documenting injuries"},
            {"label": "No, I don't have direct evidence", "intent": "evi_none", "expansion": ". I currently don't have direct evidence"},
        ],
    },
    "prior_action": {
        "description": "Prior reporting or actions taken",
        "indicators": [
            r"already\s*(filed|reported|complained|told)",
            r"fir", r"police\s*(station|complaint)",
            r"complained\s*to", r"reported\s*to",
            r"lawyer", r"advocate", r"legal\s*notice",
            r"protection\s*order", r"ngo",
            r"nothing\s*(yet|done)", r"haven'?t\s*(reported|filed)",
            r"first\s*time", r"never\s*reported",
        ],
        "suggestions": [
            {"label": "I've already filed a police complaint / FIR", "intent": "prior_fir", "expansion": ". I have already filed a police complaint"},
            {"label": "I've told family / friends but nothing formal", "intent": "prior_informal", "expansion": ". I have only told family/friends so far"},
            {"label": "I haven't taken any action yet", "intent": "prior_none", "expansion": ". I have not taken any formal action yet"},
        ],
    },
    "urgency": {
        "description": "Urgency / immediate safety",
        "indicators": [
            r"right\s*now", r"immediately", r"urgent", r"emergency",
            r"happening\s*now", r"today", r"tonight", r"just\s*happened",
            r"in\s*danger", r"not\s*safe", r"afraid", r"scared",
            r"need\s*help\s*(fast|now|urgently)",
            r"long\s*(time|ago|back)", r"months?\s*ago", r"years?\s*ago",
            r"ongoing", r"keeps\s*happening", r"for\s*a\s*while",
        ],
        "suggestions": [
            {"label": "🔴 It's happening right now / I'm in danger", "intent": "urg_now", "expansion": " and I am in immediate danger right now"},
            {"label": "🟡 It happened recently (past few days)", "intent": "urg_recent", "expansion": ". This happened recently within the past few days"},
            {"label": "🟢 It's been going on for a while", "intent": "urg_ongoing", "expansion": ". This has been ongoing for some time"},
            {"label": "🔵 I want to understand my rights (general)", "intent": "urg_general", "expansion": ". I want to understand my legal rights and options"},
        ],
    },
}

# ── Minimum factors needed to skip clarification ─────────
# If a query has at least this many factors resolved, proceed directly
MIN_FACTORS_FOR_ANSWER = 3

# Queries asking about specific legal topics (acts, sections) should
# skip clarification — they already know what they want
SPECIFIC_QUERY_PATTERNS = [
    r"section\s*\d+", r"what\s*is\s*(the\s*)?law",
    r"explain\s*(the\s*)?(act|section|provision)",
    r"rights?\s*under", r"procedure\s*for",
    r"how\s*to\s*(file|register|lodge)",
    r"punishment\s*for", r"penalty\s*for",
    r"difference\s*between", r"what\s*does\s*section",
    r"POSH\s*Act", r"DV\s*Act", r"IT\s*Act", r"IPC", r"BNS",
]


def detect_missing_factors(query: str, conversation_history: list[dict] = None) -> dict:
    """
    Analyze query + conversation history to identify missing legal context.

    Returns:
        {
            "needs_clarification": bool,
            "missing_factors": [factor_name, ...],
            "present_factors": [factor_name, ...],
            "suggestions": [...],
            "message": str
        }
    """
    # Combine query with conversation context for richer detection
    full_context = query.lower()
    if conversation_history:
        recent = conversation_history[-6:]  # last 3 exchanges
        for msg in recent:
            full_context += " " + msg.get("content", "").lower()

    # Check if this is a specific legal knowledge query (skip clarification)
    for pattern in SPECIFIC_QUERY_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return {
                "needs_clarification": False,
                "missing_factors": [],
                "present_factors": [],
                "suggestions": [],
                "message": None,
            }

    # Detect which factors are present vs missing
    present = []
    missing = []

    for factor_name, factor in LEGAL_FACTORS.items():
        found = any(re.search(p, full_context) for p in factor["indicators"])
        if found:
            present.append(factor_name)
        else:
            missing.append(factor_name)

    # Decide if clarification is needed
    needs_clarification = len(present) < MIN_FACTORS_FOR_ANSWER and len(missing) > 0

    if not needs_clarification:
        return {
            "needs_clarification": False,
            "missing_factors": missing,
            "present_factors": present,
            "suggestions": [],
            "message": None,
        }

    # Pick the most important missing factor to ask about (prioritized)
    priority_order = ["urgency", "incident_type", "relationship", "location", "evidence", "prior_action"]
    top_missing = None
    for factor in priority_order:
        if factor in missing:
            top_missing = factor
            break

    if top_missing is None:
        top_missing = missing[0]

    factor_data = LEGAL_FACTORS[top_missing]
    suggestions = factor_data["suggestions"]

    # Generate personalized message
    message = _generate_clarification_message(query, top_missing, factor_data, present)

    return {
        "needs_clarification": True,
        "missing_factors": missing,
        "present_factors": present,
        "asking_about": top_missing,
        "suggestions": suggestions,
        "message": message,
    }


def _generate_clarification_message(query: str, factor: str, factor_data: dict, present: list) -> str:
    """Generate a natural, empathetic clarification question."""
    messages = {
        "urgency": (
            "I want to make sure I give you the right guidance. "
            "Could you help me understand the urgency of your situation?"
        ),
        "incident_type": (
            "I understand you're going through something difficult. "
            "To guide you accurately, could you share a bit more about what's happening?"
        ),
        "relationship": (
            "I want to help you. To point you to the exact legal protections available, "
            "could you tell me who is involved?"
        ),
        "location": (
            "To give you the most relevant legal guidance, "
            "could you share where this is happening?"
        ),
        "evidence": (
            "This will help me advise you on building a strong case. "
            "Do you have any evidence or documentation?"
        ),
        "prior_action": (
            "Understanding what steps you've already taken will help me guide you better. "
            "Have you reported this to anyone?"
        ),
    }
    return messages.get(factor, "Could you share a few more details so I can guide you accurately?")


def expand_query(
    original_query: str,
    selected_intent: str,
    conversation_history: list[dict] = None,
    user_profile: dict = None,
) -> str:
    """
    Expand the original query with the user's clarification selection.

    Instead of sending the raw suggestion label, this builds a rich,
    context-aware internal query for the RAG pipeline.
    """
    # Find the expansion text for this intent
    expansion = ""
    for factor_data in LEGAL_FACTORS.values():
        for suggestion in factor_data["suggestions"]:
            if suggestion["intent"] == selected_intent:
                expansion = suggestion.get("expansion", "")
                break
        if expansion:
            break

    if not expansion:
        # Fall back to just appending the intent
        expansion = f" ({selected_intent.replace('_', ' ')})"

    # Build expanded query
    name = user_profile.get("name", "") if user_profile else ""
    age = user_profile.get("age", "") if user_profile else ""

    # Get the most recent user messages for context
    context_parts = []
    if conversation_history:
        for msg in reversed(conversation_history):
            if msg["role"] == "user" and msg["content"] != original_query:
                context_parts.append(msg["content"])
                if len(context_parts) >= 2:
                    break

    # Merge everything into a rich query
    base = original_query.rstrip(".")
    expanded = f"{base}{expansion}."

    if context_parts:
        prior_context = " Previously mentioned: " + "; ".join(reversed(context_parts))
        expanded += prior_context

    if name:
        expanded = f"[User: {name}" + (f", age {age}] " if age else "] ") + expanded

    logger.info(f"Query expanded: '{original_query[:50]}...' → '{expanded[:80]}...'")
    return expanded
