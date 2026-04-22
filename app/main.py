"""
app/main.py
------------
FastAPI server for NyayaDepaaAI Women Safety Legal Advisor.

Conversation flow:
  greeting       -> ask name
  onboarding     -> ask situation type
  deep_dive      -> situation-specific + common follow-up questions
  addl_info      -> ask if user wants to add anything extra (Yes / No)
  addl_info_type -> user types additional details freely, then summary is generated
  followup       -> open Q&A; any new message re-generates summary with added context

Usage:
    python -m uvicorn app.main:app --port 8000 --reload
"""

import uuid
import logging
import threading
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

# Case Analysis Integration
try:
    from case_analysis.analyzer import CasePipeline
    from case_analysis.reasoning import extract_judge_statements
    case_pipeline = CasePipeline()
except Exception as _e:
    logging.warning(f"Case analysis unavailable: {_e}")
    case_pipeline = None
    def extract_judge_statements(*a, **kw): return {}
from pydantic import BaseModel, Field
from app.config import FRONTEND_DIR, GROQ_API_KEY, PINECONE_API_KEY, JINA_API_KEY, PDF_DIR
from app.legal_agent import LegalResearchAgent
from app.llm_router import get_available_providers, get_failure_log
from app.clarifier import expand_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NyayaDepaaAI — Women Safety Legal Advisor",
    description="RAG-powered Women Safety & Rights Legal Advisor",
    version="4.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = LegalResearchAgent()
sessions: dict[str, dict] = {}
ingest_status = {"running": False, "last_result": None}

# ---------------------------------------------------------------------------
# LANGUAGE ENFORCEMENT
# Profile language is locked once chosen. Hindi uses Hindi-Hinglish style.
# User name is injected so the LLM addresses them naturally.
# ---------------------------------------------------------------------------
LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "English": "Respond ONLY in English. {name_instruction}",
    "Hindi": (
        "Respond ONLY in Hindi-Hinglish — a natural, warm mix of Hindi and English "
        "as spoken in everyday India. Write Hindi words in Devanagari script and English "
        "terms (legal acts, section numbers, technical words) in Roman script. "
        "Example: 'Aapke case mein IPC Section 498A apply hoti hai. Aap FIR file kar sakti hain.' "
        "NEVER write a fully-English response. Keep the tone warm, supportive, and simple. "
        "{name_instruction}"
    ),
    "Tamil":    "Respond ONLY in Tamil. Use Tamil script. Legal terms may remain in English. {name_instruction}",
    "Telugu":   "Respond ONLY in Telugu. Use Telugu script. Legal terms may remain in English. {name_instruction}",
    "Kannada":  "Respond ONLY in Kannada. Use Kannada script. Legal terms may remain in English. {name_instruction}",
    "Marathi":  "Respond ONLY in Marathi. Use Devanagari script. Legal terms may remain in English. {name_instruction}",
    "Bengali":  "Respond ONLY in Bengali. Use Bengali script. Legal terms may remain in English. {name_instruction}",
    "Gujarati": "Respond ONLY in Gujarati. Use Gujarati script. Legal terms may remain in English. {name_instruction}",
}

_NAME_INSTRUCTION_TEMPLATES: dict[str, str] = {
    "English": (
        "The user's name is {name}. Address them by name at warm or key moments "
        "(when starting a response, reassuring, or summarising next steps). "
        "Do NOT use the name in every sentence."
    ),
    "Hindi": (
        "User ka naam {name} hai. Unhe '{name} ji' kehke address karo jab response shuru ho, "
        "reassure karna ho, ya next steps bata rahe ho. Har sentence mein naam mat use karo."
    ),
    "Tamil":    "பயனரின் பெயர் {name}. முக்கியமான தருணங்களில் மட்டும் பெயரால் அழைக்கவும்.",
    "Telugu":   "వినియోగదారు పేరు {name}. ముఖ్యమైన సమయాలలో మాత్రమే పేరుతో పిలవండి.",
    "Kannada":  "ಬಳಕೆದಾರರ ಹೆಸರು {name}. ಪ್ರಮುಖ ಕ್ಷಣಗಳಲ್ಲಿ ಮಾತ್ರ ಹೆಸರಿನಿಂದ ಸಂಬೋಧಿಸಿ.",
    "Marathi":  "वापरकर्त्याचे नाव {name} आहे. महत्त्वाच्या क्षणीच नावाने संबोधा.",
    "Bengali":  "ব্যবহারকারীর নাম {name}। গুরুত্বপূর্ণ মুহূর্তেই কেবল নাম ধরে ডাকুন।",
    "Gujarati": "વપરાશકર્તાનું નામ {name} છે. મહત્વના સમયે જ નામ વડે સંબોધો.",
}

# ---------------------------------------------------------------------------
# SITUATION-SPECIFIC DEEP-DIVE QUESTIONS
# Emojis removed from question text as requested.
# ---------------------------------------------------------------------------
DEEP_DIVE_QUESTIONS: dict[str, list[dict]] = {
    "Domestic Violence / Abuse": [
        {
            "key": "dv_type",
            "question": "To help you better, can you tell me what kind of abuse you have been experiencing?",
            "options": ["Physical Violence", "Emotional / Mental Abuse", "Financial Control / Deprivation", "Sexual Abuse", "Multiple / All of the above"],
            "free_text": False,
        },
        {
            "key": "dv_living",
            "question": "Are you currently still living with the person who is abusing you?",
            "options": ["Yes, I am still living with them", "No, I have left / am staying elsewhere", "I am trying to leave but feel unsafe"],
            "free_text": False,
        },
        {
            "key": "dv_reported",
            "question": "Have you reported this to the police or any authority so far?",
            "options": ["Yes, I have filed a complaint", "No, I haven't reported yet", "I tried but was turned away"],
            "free_text": False,
        },
    ],
    "Workplace Harassment": [
        {
            "key": "wh_type",
            "question": "What kind of harassment are you facing at work?",
            "options": ["Sexual Harassment (POSH)", "Bullying / Mental Harassment", "Unfair termination / Discrimination", "Salary / Benefits withheld", "Other workplace issue"],
            "free_text": False,
        },
        {
            "key": "wh_reported",
            "question": "Have you reported this to your company's Internal Complaints Committee (ICC) or HR?",
            "options": ["Yes, I reported but nothing happened", "No, I am afraid to report", "My company has no ICC / HR", "I don't know how to report"],
            "free_text": False,
        },
    ],
    "Sexual Assault / Harassment": [
        {
            "key": "sa_type",
            "question": "Can you tell me what happened? You only need to share what you are comfortable with.",
            "options": ["Sexual assault / rape", "Molestation / unwanted touch", "Verbal sexual harassment", "Online / cyber sexual harassment", "I prefer not to specify"],
            "free_text": False,
        },
        {
            "key": "sa_reported",
            "question": "Have you been able to report this to anyone — police, hospital, or a trusted person?",
            "options": ["Yes, I reported to police", "Yes, I told a trusted person", "No, I haven't reported yet", "I am scared to report"],
            "free_text": False,
        },
    ],
    "Divorce / Matrimonial Issue": [
        {
            "key": "dm_type",
            "question": "What is your main concern right now?",
            "options": ["I want a divorce / separation", "My spouse wants divorce but I don't", "Domestic violence in marriage", "Maintenance / alimony issue", "Child custody concern"],
            "free_text": False,
        },
        {
            "key": "dm_married",
            "question": "What type of marriage was yours?",
            "options": ["Hindu marriage", "Muslim marriage (Nikah)", "Christian marriage", "Court / civil marriage", "Live-in relationship"],
            "free_text": False,
        },
    ],
    "Property / Inheritance Rights": [
        {
            "key": "pi_type",
            "question": "What is your property or inheritance concern?",
            "options": ["Denied share in parents' property", "Husband's property rights after separation", "Streedhan / dowry property not returned", "Property dispute with in-laws", "I don't know my rights"],
            "free_text": False,
        },
        {
            "key": "pi_religion",
            "question": "Which personal law applies to your family?",
            "options": ["Hindu / Hindu Succession Act", "Muslim personal law", "Christian personal law", "Not sure / mixed religion"],
            "free_text": False,
        },
    ],
    "Dowry Harassment": [
        {
            "key": "dowry_type",
            "question": "What kind of dowry harassment are you facing?",
            "options": ["Demands for more dowry / cash / gifts", "Physical abuse because of dowry", "Threats of divorce / being sent back", "Emotional torture / humiliation", "Multiple issues"],
            "free_text": False,
        },
        {
            "key": "dowry_reported",
            "question": "Have you reported this to the police or any authority?",
            "options": ["Yes, FIR has been filed", "No, I am afraid", "My family is pressuring me to stay quiet", "I don't know how to report"],
            "free_text": False,
        },
    ],
    "Stalking / Cybercrime": [
        {
            "key": "sc_type",
            "question": "What are you experiencing?",
            "options": ["Being physically followed / watched", "Receiving unwanted calls / messages", "Fake profiles / morphed photos online", "Threatening messages / blackmail online", "Hacking / account takeover"],
            "free_text": False,
        },
        {
            "key": "sc_known",
            "question": "Do you know who is doing this?",
            "options": ["Yes, it's an ex-partner", "Yes, it's a colleague / acquaintance", "Yes, it's a stranger I can identify", "No, I don't know who it is"],
            "free_text": False,
        },
    ],
    "Child Custody": [
        {
            "key": "cc_situation",
            "question": "What is your custody situation?",
            "options": ["Separation / divorce pending, need interim custody", "Ex-partner took child without permission", "I want to change existing custody order", "Grandparents / in-laws are interfering", "Need child support / maintenance"],
            "free_text": False,
        },
        {
            "key": "cc_child_age",
            "question": "How old is your child?",
            "options": ["Below 5 years", "5 to 10 years", "11 to 14 years", "Above 14 years"],
            "free_text": False,
        },
    ],
    "Other / Not Sure": [
        {
            "key": "other_description",
            "question": "Please tell me what you are going through in your own words. I am here to listen and help.",
            "options": [],
            "free_text": True,
        },
    ],
}

# Common questions asked for all situations after the situation-specific ones
COMMON_FOLLOWUPS: list[dict] = [
    {
        "key": "evidence",
        "question": "What evidence or proof do you currently have? Select all that apply — this helps us predict your case outcome more accurately.",
        "options": [
            "FIR / Police Complaint filed",
            "Medical reports / injury records",
            "Photographs / Videos / CCTV",
            "WhatsApp chats / SMS / Emails",
            "Witness statements",
            "Financial records / bank statements",
            "Legal documents (marriage cert, property papers, etc.)",
            "Audio / video recordings",
            "No evidence yet",
            "Other (type your own)",
        ],
        "free_text": True,
        "multi_select": True,
    },
    {
        "key": "urgency",
        "question": "How urgent is your situation right now?",
        "options": [
            "I am in immediate danger — need help NOW",
            "Serious but not immediate — need advice soon",
            "Planning ahead / gathering information",
            "Just learning about my rights",
        ],
        "free_text": False,
    },
    {
        "key": "state",
        "question": "Which state are you in? This helps me give you location-specific legal information.",
        "options": [
            "Andhra Pradesh", "Delhi", "Gujarat", "Karnataka",
            "Kerala", "Maharashtra", "Rajasthan", "Tamil Nadu",
            "Telangana", "Uttar Pradesh", "West Bengal", "Other / Not Sure",
        ],
        "free_text": False,
        "skip_label": "Prefer not to say",
    },
]

# State question localised per language (after language is locked)
_STATE_QUESTION_L10N: dict[str, str] = {
    "English": "Which state are you in? This helps me give you location-specific legal information.",
    "Hindi":   "Aap kis state mein hain? Yeh mujhe state-specific laws batane mein help karega.",
    "Tamil":   "நீங்கள் எந்த மாநிலத்தில் இருக்கிறீர்கள்?",
    "Telugu":  "మీరు ఏ రాష్ట్రంలో ఉన్నారు?",
    "Kannada": "ನೀವು ಯಾವ ರಾಜ್ಯದಲ್ಲಿ ಇದ್ದೀರಿ?",
    "Marathi": "तुम्ही कोणत्या राज्यात आहात?",
    "Bengali": "আপনি কোন রাজ্যে আছেন?",
    "Gujarati": "તમે કયા રાજ્યમાં છો?",
}

# "Anything to add?" prompt — no emojis
_ADDL_INFO_PROMPT: dict[str, str] = {
    "English": (
        "Thank you for sharing all of that{name_part}.\n\n"
        "Is there anything else you would like to add — any other detail about your situation "
        "that might help me give you more complete advice?\n\n"
        "You can type it freely below, or choose one of the options."
    ),
    "Hindi": (
        "Itna sab batane ke liye shukriya{name_part}.\n\n"
        "Kya aap kuch aur bhi add karna chahti hain — koi aur detail jo mujhe "
        "better advice dene mein help kare?\n\n"
        "Aap freely type kar sakti hain, ya neeche se choose karein."
    ),
    "Tamil": (
        "எல்லாவற்றையும் பகிர்ந்துகொண்டதற்கு நன்றி{name_part}.\n\n"
        "வேறு ஏதாவது சேர்க்க விரும்புகிறீர்களா?\n\n"
        "தடையின்றி தட்டச்சு செய்யலாம் அல்லது கீழே தேர்வு செய்யலாம்."
    ),
    "Telugu": (
        "అన్నీ చెప్పినందుకు ధన్యవాదాలు{name_part}.\n\n"
        "మరేదైనా జోడించాలనుకుంటున్నారా?\n\n"
        "స్వేచ్ఛగా టైప్ చేయవచ్చు లేదా దిగువ నుండి ఎంచుకోండి."
    ),
    "Kannada": (
        "ಎಲ್ಲವನ್ನೂ ಹಂಚಿಕೊಂಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು{name_part}.\n\n"
        "ಇನ್ನೇನಾದರೂ ಸೇರಿಸಲು ಬಯಸುತ್ತೀರಾ?\n\n"
        "ಮುಕ್ತವಾಗಿ ಟೈಪ್ ಮಾಡಬಹುದು ಅಥವಾ ಕೆಳಗೆ ಆಯ್ಕೆ ಮಾಡಿ."
    ),
    "Marathi": (
        "सर्व काही शेअर केल्याबद्दल आभारी आहे{name_part}.\n\n"
        "आणखी काही जोडायचे आहे का?\n\n"
        "मुक्तपणे टाइप करा किंवा खाली निवडा."
    ),
    "Bengali": (
        "সব কিছু শেয়ার করার জন্য ধন্যবাদ{name_part}।\n\n"
        "আর কিছু যোগ করতে চান?\n\n"
        "স্বাধীনভাবে টাইপ করুন বা নিচে থেকে বেছে নিন।"
    ),
    "Gujarati": (
        "બધું શેર કરવા બદલ આભાર{name_part}.\n\n"
        "બીજું કંઈ ઉમેરવા માગો છો?\n\n"
        "મુક્તપણે ટાઈપ કરો અથવા નીચેથી પસંદ કરો."
    ),
}

# "Yes / No" options for the additional info prompt
_ADDL_INFO_OPTIONS: dict[str, list[str]] = {
    "English": ["No, generate my legal summary now", "Yes, I want to add more details"],
    "Hindi":   ["Nahi, abhi meri legal summary generate karo", "Haan, main aur details add karna chahti hoon"],
    "Tamil":   ["இல்லை, இப்போது சட்ட சுருக்கம் தரவும்", "ஆம், மேலும் விவரங்கள் சேர்க்க விரும்புகிறேன்"],
    "Telugu":  ["లేదు, ఇప్పుడే చట్టపరమైన సారాంశం ఇవ్వండి", "అవును, మరిన్ని వివరాలు జోడించాలనుకుంటున్నాను"],
    "Kannada": ["ಇಲ್ಲ, ಈಗ ಕಾನೂನು ಸಾರಾಂಶ ನೀಡಿ", "ಹೌದು, ಇನ್ನಷ್ಟು ವಿವರ ಸೇರಿಸಲು ಬಯಸುತ್ತೇನೆ"],
    "Marathi": ["नाही, आत्ता कायदेशीर सारांश द्या", "हो, मला आणखी तपशील जोडायचे आहेत"],
    "Bengali": ["না, এখনই আইনি সারসংক্ষেপ দিন", "হ্যাঁ, আমি আরও বিবরণ যোগ করতে চাই"],
    "Gujarati": ["ના, હવે કાનૂની સારાંશ આપો", "હા, હું વધુ વિગતો ઉમેરવા માગું છું"],
}

# Prompt shown when user says "Yes, add more" — asks them to type
_TYPE_ADDL_PROMPT: dict[str, str] = {
    "English": "Please go ahead and type any additional details you would like to share. I will include everything in your legal summary.",
    "Hindi":   "Kripya jo bhi additional details share karna chahti hain, woh type karein. Main sab kuch aapki legal summary mein include karungi.",
    "Tamil":   "கூடுதல் விவரங்களை தட்டச்சு செய்யுங்கள். அனைத்தையும் உங்கள் சட்ட சுருக்கத்தில் சேர்ப்பேன்.",
    "Telugu":  "దయచేసి మీరు పంచుకోవాలనుకున్న అదనపు వివరాలు టైప్ చేయండి. అన్నీ మీ చట్టపరమైన సారాంశంలో చేర్చుతాను.",
    "Kannada": "ದಯವಿಟ್ಟು ಹೆಚ್ಚುವರಿ ವಿವರಗಳನ್ನು ಟೈಪ್ ಮಾಡಿ. ಎಲ್ಲವನ್ನೂ ನಿಮ್ಮ ಕಾನೂನು ಸಾರಾಂಶದಲ್ಲಿ ಸೇರಿಸುತ್ತೇನೆ.",
    "Marathi": "कृपया जे काही अतिरिक्त तपशील सांगायचे आहेत ते टाइप करा. सर्व काही तुमच्या कायदेशीर सारांशात समाविष्ट केले जाईल.",
    "Bengali": "অনুগ্রহ করে অতিরিক্ত বিবরণ টাইপ করুন। সবকিছু আপনার আইনি সারসংক্ষেপে অন্তর্ভুক্ত করব।",
    "Gujarati": "કૃપા કરીને વધારાની વિગતો ટાઈપ કરો. બધું જ તમારા કાનૂની સારાંશમાં સામેલ કરીશ.",
}

# Emergency warning — no emoji prefix
_EMERGENCY_WARNING: dict[str, str] = {
    "English": "IMPORTANT: If you are in immediate danger, please call 112 (Emergency) or 181 (Women Helpline) right now.\n\n",
    "Hindi":   "ZAROORI: Agar aap abhi khatare mein hain, turant 112 ya 181 (Women Helpline) call karein.\n\n",
    "Tamil":   "முக்கியம்: நீங்கள் உடனடி ஆபத்தில் இருந்தால், இப்போதே 112 அல்லது 181 அழைக்கவும்.\n\n",
    "Telugu":  "ముఖ్యమైనది: మీరు వెంటనే ప్రమాదంలో ఉంటే, ఇప్పుడే 112 లేదా 181 కి కాల్ చేయండి.\n\n",
    "Kannada": "ಮುಖ್ಯ: ನೀವు ತಕ್ಷಣದ ಅಪಾಯದಲ್ಲಿದ್ದರೆ, ಈಗಲೇ 112 ಅಥವಾ 181 ಕರೆ ಮಾಡಿ.\n\n",
    "Marathi": "महत्त्वाचे: तुम्ही तात्काळ धोक्यात असल्यास, आत्ताच 112 किंवा 181 वर कॉल करा.\n\n",
    "Bengali": "গুরুত্বপূর্ণ: আপনি যদি এখনই বিপদে থাকেন, তাহলে এখনই 112 বা 181 কল করুন।\n\n",
    "Gujarati": "મહત્વનું: જો તમે અત્યારે ખતરામાં છો, તો તરત જ 112 અથવા 181 કૉલ કરો.\n\n",
}

# Initial greeting shown to every new user
INITIAL_GREETING = (
    "Welcome to NyayaDepaaAI — your safe, confidential space for women's legal guidance.\n\n"
    "I am here to listen without judgement, and help you understand your rights and legal options "
    "at your own pace. Everything you share is completely confidential.\n\n"
    "To get started, may I know your name? "
    "This helps me make our conversation more personal. You can also choose to stay anonymous."
)

# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def get_session_language(session: dict) -> str:
    """Profile language always wins over per-request value."""
    return session["profile"].get("language") or session.get("language") or "English"


def get_language_instruction(language: str, name: str | None = None) -> str:
    """Return the LLM language + optional name instruction string."""
    template = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["English"])
    if name:
        name_tpl = _NAME_INSTRUCTION_TEMPLATES.get(language, _NAME_INSTRUCTION_TEMPLATES["English"])
        name_instruction = name_tpl.format(name=name)
    else:
        name_instruction = ""
    return template.format(name_instruction=name_instruction).strip()


def name_part_str(name: str | None, language: str) -> str:
    """Return ', Name' or ', Name ji' for use in message templates."""
    if not name:
        return ""
    return f", {name} ji" if language == "Hindi" else f", {name}"


def get_deep_dive_steps(situation: str) -> list[dict]:
    """Return all questions for a given situation (specific + common)."""
    return DEEP_DIVE_QUESTIONS.get(situation, DEEP_DIVE_QUESTIONS["Other / Not Sure"]) + COMMON_FOLLOWUPS


def get_next_deep_dive_step(session: dict) -> dict | None:
    """Return the next unanswered question in the deep-dive sequence."""
    situation = session["profile"].get("situation_type", "Other / Not Sure")
    for step in get_deep_dive_steps(situation):
        if step["key"] not in session["profile"]:
            return step
    return None


def build_step_response(step: dict, language: str = "English") -> dict:
    """Build a response dict for a single question step."""
    question = _STATE_QUESTION_L10N.get(language, step["question"]) if step["key"] == "state" else step["question"]
    options = step.get("options") or []
    suggestions = [{"label": o, "intent": o} for o in options]
    if step.get("skip_label"):
        suggestions.append({"label": step["skip_label"], "intent": "__skip__"})
    return {
        "response": question,
        "options": options,
        "suggestions": suggestions,
        "free_text": step.get("free_text", False),
        "onboarding_key": step["key"],
        "multi_select": step.get("multi_select", False),
    }


def build_summary_query(profile: dict, extra_info: str = "") -> str:
    """
    Build a rich, structured query for the RAG agent to generate the full legal summary.
    No emojis in section headers — uses plain text markers instead.
    """
    name = profile.get("name") or "the user"
    situation = profile.get("situation_type", "general women safety issue")
    state = profile.get("state") or "India"
    urgency = profile.get("urgency", "not specified")
    language = profile.get("language", "English")

    # Collect all answered deep-dive questions as context lines
    context_lines = []
    for step in get_deep_dive_steps(situation):
        val = profile.get(step["key"])
        if val and val not in ("__skip__", None):
            # Strip trailing question/punctuation for cleaner label
            label = step["question"].rstrip("?. ").split("?")[0].strip()
            context_lines.append(f"  - {label}: {val}")

    # Merge stored additional_info with any new extra_info passed in
    stored_extra = profile.get("additional_info") or ""
    all_extra_parts = [p for p in [stored_extra, extra_info] if p.strip()]
    all_extra = "; ".join(all_extra_parts)

    context_block = "\n".join(context_lines) if context_lines else "  No additional details."
    extra_block = f"\n  Additional information from user: {all_extra}" if all_extra else ""

    # Evidence block
    evidence = profile.get("evidence", "")
    evidence_block = ""
    if evidence and evidence not in ("__skip__", "No evidence yet"):
        evidence_block = f"\n  EVIDENCE AVAILABLE: {evidence}"

    return (
        f"Generate a comprehensive, personalised legal summary for {name} located in {state}.\n\n"
        f"SITUATION: {situation}\n"
        f"URGENCY: {urgency}\n\n"
        f"CASE DETAILS:\n{context_block}{extra_block}{evidence_block}\n\n"
        f"The response MUST be structured with these clearly labelled sections. "
        f"Use plain text headings without asterisks, EXACTLY AS WRITTEN BELOW. Output bullet points. "
        f"Bold the most important information such as law names, section numbers, and action items.\n\n"
        f"### SITUATION SUMMARY\n"
        f"Briefly acknowledge what {name} is going through. Be empathetic and direct.\n\n"
        f"### LEGAL RIGHTS\n"
        f"What are her specific legal rights under Indian law in this situation?\n\n"
        f"### RELEVANT INDIAN LAWS\n"
        f"List the specific laws, sections, and acts that apply "
        f"(e.g. IPC sections, PWDVA, POSH Act, Hindu Marriage Act, IT Act, etc.).\n\n"
        f"### CASE PREDICTION & POSSIBLE OUTCOMES\n"
        f"Based on patterns from similar legal cases in the database, analyze:\n"
        f"a) The most probable outcome and why — explain the judicial reasoning (on what basis judges decided)\n"
        f"b) Alternative possible outcomes with approximate likelihood\n"
        f"c) Key factors from the user's case that influence each outcome\n"
        f"d) What evidence and legal provisions judges relied on to reach their decisions\n"
        f"Present this as a personalized advocate would — not generic.\n\n"
        f"### ESTIMATED TIMELINE\n"
        f"Estimate realistic duration based on similar case patterns, court level, and complexity.\n\n"
        f"### STRATEGIC CONSIDERATIONS\n"
        f"Explain strategic advantages, risks, and recommended precautions based on similar cases.\n\n"
        f"### IMMEDIATE NEXT STEPS\n"
        f"What should {name} do right now? Provide numbered, actionable steps.\n\n"
        f"### HELPLINES AND RESOURCES\n"
        f"List relevant helplines, NGOs, legal aid contacts, and police resources for {state}.\n\n"
        f"### ADDITIONAL ADVICE\n"
        f"Any other important information specific to her situation.\n\n"
        f"Respond in {language}. Be compassionate, clear, and actionable. "
        f"Do not use emojis anywhere in the response."
    )


def set_language_instruction(session: dict) -> None:
    """Inject the language + name instruction into the session profile for the LLM."""
    lang = get_session_language(session)
    name = session["profile"].get("name")
    session["profile"]["_language_instruction"] = get_language_instruction(lang, name)


# ---------------------------------------------------------------------------
# PYDANTIC MODELS
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None
    language: str = "English"


class ChatResponse(BaseModel):
    response: str
    sources: list[dict]
    session_id: str
    stage: str
    domain: list[str]
    risk_level: str
    provider: str | None
    timestamp: str
    emotional_state: str | None = None
    user_name: str | None = None
    retrieval_error: str | None = None
    needs_clarification: bool = False
    suggestions: list[dict] | None = None
    options: list[str] | None = None
    free_text: bool | None = None
    onboarding_key: str | None = None
    multi_select: bool | None = None


def _resp(
    response: str,
    session_id: str,
    session: dict,
    stage: str,
    *,
    suggestions: list | None = None,
    options: list | None = None,
    free_text: bool | None = None,
    onboarding_key: str | None = None,
    multi_select: bool | None = None,
    sources: list | None = None,
    provider: str | None = None,
    risk_level: str = "low",
    domain: list | None = None,
    emotional_state: str | None = None,
    retrieval_error: str | None = None,
    needs_clarification: bool = False,
) -> ChatResponse:
    return ChatResponse(
        response=response,
        sources=sources or [],
        session_id=session_id,
        stage=stage,
        domain=domain or [],
        risk_level=risk_level,
        provider=provider,
        timestamp=datetime.now().isoformat(),
        emotional_state=emotional_state,
        user_name=session["profile"].get("name"),
        retrieval_error=retrieval_error,
        needs_clarification=needs_clarification,
        suggestions=suggestions,
        options=options or [],
        free_text=free_text,
        onboarding_key=onboarding_key,
        multi_select=multi_select,
    )


async def _generate_summary(session_id: str, session: dict, extra_info: str = "") -> ChatResponse:
    """
    Build the summary query and call the RAG agent.
    Used both from addl_info stage and from followup stage (re-generation).
    """
    lang = get_session_language(session)
    set_language_instruction(session)

    # Store extra_info persistently in the profile so future re-generations include it
    if extra_info.strip():
        existing = session["profile"].get("additional_info") or ""
        combined = "; ".join(p for p in [existing, extra_info.strip()] if p)
        session["profile"]["additional_info"] = combined

    query = build_summary_query(session["profile"])

    urgency = session["profile"].get("urgency", "")
    session["history"].append({
        "role": "user",
        "content": f"[Profile: situation={session['profile'].get('situation_type')}, urgency={urgency}, state={session['profile'].get('state', 'India')}]"
    })

    result = agent.generate_response(
        query=query,
        stage="summary",
        conversation_history=session["history"],
        language=lang,
        user_profile=session["profile"],
    )

    session["history"].append({"role": "user", "content": "[Requested full legal summary]"})
    session["history"].append({"role": "assistant", "content": result["response"]})
    session["stage"] = "followup"

    if len(session["history"]) > 40:
        session["history"] = session["history"][-40:]

    # --- Append Pinecone Prediction Analysis to Chatbot Response ---
    pinecone_pred = result.get("_pinecone_prediction")
    analysis_text = ""

    if pinecone_pred and not pinecone_pred.get("error"):
        outcome_preds = pinecone_pred.get("outcome_predictions", {})
        preds_list = outcome_preds.get("predictions", [])
        top_outcome = outcome_preds.get("top_outcome", "Unknown")
        top_prob = outcome_preds.get("top_probability", 0)
        factors = pinecone_pred.get("user_factors", [])
        factor_analysis = pinecone_pred.get("factor_analysis", [])
        duration = pinecone_pred.get("duration_estimate", {})
        strategic = pinecone_pred.get("strategic_analysis", {})
        user_name = session["profile"].get("name") or "you"

        if preds_list:
            analysis_text += "\n\n---\n\n### Predicted Case Outcome\n"

            # Primary prediction — stated like an advocate's opinion
            if top_prob >= 60:
                analysis_text += f"Based on the legal circumstances described, your case is **strongly positioned** towards **{top_outcome}**. "
                analysis_text += f"The combination of facts and applicable laws indicates this is the most likely result a court would reach in your situation.\n\n"
            elif top_prob >= 35:
                analysis_text += f"Your case has a **reasonable prospect** of resulting in **{top_outcome}**. "
                analysis_text += f"However, the outcome will depend significantly on the strength of evidence and legal representation.\n\n"
            else:
                analysis_text += f"The case could result in **{top_outcome}**, but the outcome remains **contested** — "
                analysis_text += f"multiple directions are possible depending on how the facts are presented and argued in court.\n\n"

            # Factor-based reasoning — personalized
            if factors and len(factors) > 1:
                analysis_text += "### Key Legal Dimensions of Your Case\n"
                for fa in factor_analysis:
                    factor = fa["factor"]
                    dominant = fa["dominant_outcome"]
                    if fa["matched_cases"] > 0:
                        analysis_text += f"- **{factor}** — In cases involving this factor, courts have predominantly ruled towards *{dominant}*. This aspect of your case carries weight.\n"
                analysis_text += "\n"

            # Alternative outcomes — stated as scenarios
            if len(preds_list) > 1:
                analysis_text += "### Possible Outcomes for Your Case\n"
                scenario_labels = ["Most Likely", "Alternative Scenario", "Less Likely but Possible"]
                for i, p in enumerate(preds_list[:3]):
                    label = scenario_labels[i] if i < len(scenario_labels) else "Other"
                    analysis_text += f"- **{label}: {p['outcome']}** — "
                    if i == 0:
                        analysis_text += f"Given the facts, this is the direction the court is most likely to take.\n"
                    elif i == 1:
                        analysis_text += f"This outcome is possible if the opposing side presents strong counter-evidence or procedural arguments.\n"
                    else:
                        analysis_text += f"This could happen under specific circumstances, such as a change in evidence or settlement negotiation.\n"
                analysis_text += "\n"

            # Duration — personalized
            if duration and duration.get("avg_months"):
                avg_m = duration["avg_months"]
                min_m = duration["min_months"]
                max_m = duration["max_months"]
                analysis_text += "### Expected Timeline\n"
                if avg_m < 6:
                    analysis_text += f"Cases like yours typically resolve within **{min_m:.0f} to {max_m:.0f} months**. This is relatively quick for the Indian judicial system. "
                elif avg_m < 18:
                    analysis_text += f"Expect this case to take approximately **{min_m:.0f} to {max_m:.0f} months**. "
                else:
                    analysis_text += f"This type of case typically takes **{min_m:.0f} to {max_m:.0f} months** to reach a final order. "
                analysis_text += f"Factors like court backlogs, evidence complexity, and whether a settlement is explored will affect the actual timeline.\n\n"
            elif duration and duration.get("estimate_text"):
                analysis_text += "### Expected Timeline\n"
                analysis_text += f"{duration['estimate_text']}\n\n"

            # Strategic — as advocate advice
            advantages = strategic.get("advantages", [])
            risks = strategic.get("risks", [])
            recommendations = strategic.get("recommendations", [])

            if advantages or risks:
                analysis_text += "### What Works in Your Favour — and What to Watch Out For\n"
                for a in advantages:
                    analysis_text += f"- **In your favour:** {a}\n"
                for r in risks:
                    analysis_text += f"- **Be cautious:** {r}\n"
                analysis_text += "\n"

            if recommendations:
                analysis_text += "### My Advice for Your Next Steps\n"
                for i, r in enumerate(recommendations, 1):
                    analysis_text += f"{i}. {r}\n"
                analysis_text += "\n"

            # --- Judge Reasoning Patterns (from similar cases) ---
            judge_reasoning = pinecone_pred.get("judge_reasoning_patterns", {})
            reasoning_by_outcome = judge_reasoning.get("reasoning_by_outcome", {})
            top_bases = judge_reasoning.get("top_decision_bases", [])

            if reasoning_by_outcome:
                analysis_text += "### How Courts Have Decided in Similar Cases\n"
                analysis_text += "Based on precedents from similar legal matters, here is how judges have reasoned:\n\n"

                for outcome, data in reasoning_by_outcome.items():
                    count = data.get("case_count", 0)
                    bases = data.get("decision_bases", [])
                    key_laws = data.get("key_laws", [])
                    observations = data.get("court_observations", [])
                    evidence = data.get("common_evidence", [])

                    analysis_text += f"**When courts ruled: {outcome}**\n"

                    # Why they decided this way
                    if bases:
                        analysis_text += f"- **Basis for decision:** {', '.join(bases)}\n"
                    if key_laws:
                        law_str = ", ".join(f"**{law}**" for law in key_laws[:4])
                        analysis_text += f"- **Laws applied:** {law_str}\n"
                    if evidence:
                        analysis_text += f"- **Evidence relied on:** {', '.join(evidence[:4])}\n"

                    # Court observations — the actual judge reasoning quotes
                    for obs in observations[:2]:
                        clean = obs.replace("\n", " ").strip()[:300]
                        if clean:
                            analysis_text += f"- Court observed: *\"{clean}\"*\n"

                    analysis_text += "\n"

                # Summary of common judicial reasoning patterns
                if top_bases:
                    analysis_text += "**Key judicial reasoning patterns in cases like yours:** "
                    analysis_text += ", ".join(f"*{b}*" for b in top_bases[:4])
                    analysis_text += "\n\n"

    # --- Fallback: ChromaDB Case Analysis (if Pinecone prediction unavailable) ---
    if not analysis_text:
        situation = session["profile"].get("situation_type", "")
        addl_info = session["profile"].get("additional_info", "")
        full_case_desc = f"{situation} {addl_info}".strip()

        if len(full_case_desc) > 20:
            try:
                analysis_result = case_pipeline.analyze(user_description=full_case_desc, top_k=5)
            except Exception as _cp_err:
                logger.warning(f"[CASE PIPELINE] Prediction skipped (ChromaDB unavailable): {_cp_err}")
                analysis_result = {}

            preds = analysis_result.get("outcome_predictions", {}).get("predictions", [])
            top_outcome = analysis_result.get("top_outcome", "Unknown")
            conf_score = analysis_result.get("confidence_score", 0.0)
            sim_cases = analysis_result.get("similar_cases", [])

            if preds:
                analysis_text += "\n\n---\n\n### Predicted Case Outcome\n"
                analysis_text += f"Based on analysis of cases with similar legal circumstances, the most probable result is **{top_outcome}**.\n\n"

                if len(preds) > 1:
                    analysis_text += "**Possible Outcomes:**\n"
                    scenario_labels = ["Most Likely", "Alternative", "Less Likely"]
                    for i, p in enumerate(preds[:3]):
                        label = scenario_labels[i] if i < len(scenario_labels) else "Other"
                        analysis_text += f"- **{label}:** {p['outcome']}\n"

                # Extract Judge Statements
                statements = extract_judge_statements(sim_cases, top_outcome)
                if statements:
                    analysis_text += "\n**Possible Statements by the Judge based on Precedent:**\n"
                    for s in statements:
                        analysis_text += f"- *{s}*\n"

    final_response = result["response"].strip() + analysis_text

    return _resp(
        final_response, session_id, session, "followup",
        sources=result.get("sources", []),
        provider=result.get("provider"),
        risk_level=result.get("risk", {}).get("level", "low"),
        domain=result.get("domain", []),
        emotional_state=result.get("emotional_state"),
        retrieval_error=result.get("retrieval_error"),
    )


# ---------------------------------------------------------------------------
# API ROUTES
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health_check():
    providers = get_available_providers()
    return {
        "status": "ok",
        "services": {
            "pinecone": "configured" if PINECONE_API_KEY else "not_configured",
            "jina_embeddings": "configured" if JINA_API_KEY else "not_configured",
            **{f"llm_{k}": "configured" if v else "not_configured" for k, v in providers.items()},
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/debug_status")
async def debug_status():
    from app.llm_router import get_failure_log
    import os
    return {
        "groq_key_len": len(os.getenv("GROQ_API_KEY", "")),
        "gemini_key_len": len(os.getenv("GEMINI_API_KEY", "")),
        "gemini_ends": repr(os.getenv("GEMINI_API_KEY", "")[-5:]),
        "failure_log": get_failure_log()
    }


class NewSessionRequest(BaseModel):
    name: str | None = None
    language: str = "English"


@app.post("/api/new_session")
async def new_session(body: NewSessionRequest | None = None):
    """
    Create a session.
    If name + language are provided (from the login form), skip the greeting
    stage and go straight to onboarding (situation selection).
    """
    sid = str(uuid.uuid4())
    req_name = body.name if body else None
    req_lang = body.language if body else "English"

    sessions[sid] = {"history": [], "stage": "greeting", "language": req_lang, "profile": {}}
    session = sessions[sid]

    # If frontend already captured name + language, skip greeting
    if req_name:
        session["profile"]["name"] = req_name.strip().title()
        session["profile"]["language"] = req_lang
        session["language"] = req_lang
        session["stage"] = "onboarding"

        name = session["profile"]["name"]
        situation_opts = list(DEEP_DIVE_QUESTIONS.keys())
        greeting_line = f"Nice to meet you, {name}.\n\n" if name else "Welcome.\n\n"
        msg = (
            f"{greeting_line}"
            "To give you the most relevant legal guidance, I need to understand your situation.\n\n"
            "What best describes what you are going through?\n\n"
            "If none of the options fit, choose 'Other / Not Sure' and you can describe it in your own words."
        )
        logger.info(f"[{sid[:8]}] New session (pre-auth) name='{name}' lang='{req_lang}' -> onboarding")
        return {
            "session_id": sid,
            "response": msg,
            "stage": "onboarding",
            "sources": [], "domain": [], "risk_level": "low", "provider": None,
            "timestamp": datetime.now().isoformat(),
            "emotional_state": None, "user_name": name, "retrieval_error": None,
            "needs_clarification": False,
            "suggestions": [{"label": o, "intent": o} for o in situation_opts],
            "options": situation_opts,
            "free_text": False, "onboarding_key": "situation_type",
        }

    # Fallback: no name provided — classic greeting flow
    logger.info(f"[{sid[:8]}] New session (no name) -> greeting")
    return {
        "session_id": sid,
        "response": INITIAL_GREETING,
        "stage": "greeting",
        "sources": [], "domain": [], "risk_level": "low", "provider": None,
        "timestamp": datetime.now().isoformat(),
        "emotional_state": None, "user_name": None, "retrieval_error": None,
        "needs_clarification": False,
        "suggestions": [{"label": "Stay Anonymous", "intent": "stay anonymous"}],
        "options": ["Stay Anonymous"], 
        "free_text": True, "onboarding_key": "name",
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint.

    Stage transitions:
      greeting       -> save name -> onboarding
      onboarding     -> save situation -> deep_dive
      deep_dive      -> answer questions one by one -> addl_info
      addl_info      -> "Yes" -> addl_info_type | "No" -> generate summary -> followup
      addl_info_type -> save typed extra info -> generate summary -> followup
      followup       -> any message treated as additional info -> re-generate summary
    """
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = {"history": [], "stage": "greeting", "language": "English", "profile": {}}

    session = sessions[session_id]

    # ------------------------------------------------------------------
    # AUTO-INIT DETECTION
    # Frontends that auto-send a trigger word on load (e.g. "Hello_init",
    # "hi", "start") should see the greeting, not have that word saved as name.
    # ------------------------------------------------------------------
    AUTO_INIT_TRIGGERS = {
        "hello", "hello_init", "hello init", "hi", "start", "begin",
        "init", "__init__", "hey", "namaste", "hlo", "helo",
        "hello!", "hi!", "hey!", "test", "ping", "hii", "hiii",
    }
    q = request.query.strip()
    if session["stage"] == "greeting" and not session["profile"] and q.lower().rstrip("!.,") in AUTO_INIT_TRIGGERS:
        logger.info(f"[{session_id[:8]}] Auto-init '{q}' -> greeting")
        return _resp(
            INITIAL_GREETING, session_id, session, "greeting",
            suggestions=[{"label": "Stay Anonymous", "intent": "stay anonymous"}],
            options=["Stay Anonymous"], 
            free_text=True, onboarding_key="name",
        )

    lang = get_session_language(session)

    # ------------------------------------------------------------------
    # STAGE: greeting — capture name
    # ------------------------------------------------------------------
    if session["stage"] == "greeting":
        q_lower = q.lower().strip().rstrip(".,!")
        exact_skips = {"__skip__", "stay anonymous", "prefer not to say", "", "skip", "no", "none", "anonymous"}
        
        is_decline = (
            q_lower in exact_skips or 
            "dont prefer" in q_lower or 
            "don't prefer" in q_lower or 
            "prefer not" in q_lower or 
            "don't want" in q_lower or 
            "dont want" in q_lower or 
            "not comfortable" in q_lower or
            "no name" in q_lower
        )

        if is_decline or len(q_lower.split()) > 3 or len(q_lower) > 30:
            session["profile"]["name"] = None
        else:
            session["profile"]["name"] = q.strip().title()
            
        name = session["profile"].get("name")
        session["stage"] = "onboarding"

        greeting_line = f"Nice to meet you, {name}.\n\n" if name else "Welcome.\n\n"
        situation_opts = list(DEEP_DIVE_QUESTIONS.keys())
        msg = (
            f"{greeting_line}"
            "To give you the most relevant legal guidance, I need to understand your situation.\n\n"
            "What best describes what you are going through?\n\n"
            "If none of the options fit, choose 'Other / Not Sure' and you can describe it in your own words."
        )
        logger.info(f"[{session_id[:8]}] Name='{name}' -> onboarding")
        return _resp(
            msg, session_id, session, "onboarding",
            options=situation_opts,
            suggestions=[{"label": o, "intent": o} for o in situation_opts],
            free_text=False, onboarding_key="situation_type",
        )

    # ------------------------------------------------------------------
    # STAGE: onboarding — capture situation type
    # ------------------------------------------------------------------
    if session["stage"] == "onboarding":
        session["profile"]["situation_type"] = q
        session["stage"] = "deep_dive"
        logger.info(f"[{session_id[:8]}] Situation='{q}' -> deep_dive")

        next_step = get_next_deep_dive_step(session)
        if next_step:
            ob = build_step_response(next_step, lang)
            return _resp(ob["response"], session_id, session, "deep_dive",
                         options=ob["options"], suggestions=ob["suggestions"],
                         free_text=ob["free_text"], onboarding_key=ob["onboarding_key"],
                         multi_select=ob.get("multi_select", False))

    # ------------------------------------------------------------------
    # STAGE: deep_dive — answer situation-specific + common questions
    # ------------------------------------------------------------------
    if session["stage"] == "deep_dive":
        current_step = get_next_deep_dive_step(session)
        if current_step:
            key = current_step["key"]
            session["profile"][key] = None if q in ("__skip__", "") else q

            next_step = get_next_deep_dive_step(session)
            if next_step:
                ob = build_step_response(next_step, lang)
                return _resp(ob["response"], session_id, session, "deep_dive",
                             options=ob["options"], suggestions=ob["suggestions"],
                             free_text=ob["free_text"], onboarding_key=ob["onboarding_key"],
                             multi_select=ob.get("multi_select", False))

            # All deep-dive questions answered -> ask additional info
            session["stage"] = "addl_info"
            np = name_part_str(session["profile"].get("name"), lang)
            addl_msg = _ADDL_INFO_PROMPT.get(lang, _ADDL_INFO_PROMPT["English"]).format(name_part=np)
            addl_opts = _ADDL_INFO_OPTIONS.get(lang, _ADDL_INFO_OPTIONS["English"])

            urgency = session["profile"].get("urgency", "")
            if "immediate danger" in urgency.lower():
                addl_msg = _EMERGENCY_WARNING.get(lang, _EMERGENCY_WARNING["English"]) + addl_msg

            logger.info(f"[{session_id[:8]}] Deep-dive done -> addl_info")
            return _resp(addl_msg, session_id, session, "addl_info",
                         options=addl_opts,
                         suggestions=[{"label": o, "intent": o} for o in addl_opts],
                         free_text=True, onboarding_key="additional_info")

    # ------------------------------------------------------------------
    # STAGE: addl_info — user chose Yes or No (or typed something)
    # ------------------------------------------------------------------
    if session["stage"] == "addl_info":
        # Detect if user chose "Yes, add more details"
        yes_keywords = ["yes", "haan", "haa", "ஆம்", "అవును", "ಹೌದು", "हो", "হ্যাঁ", "હા"]
        wants_more = any(q.lower().startswith(k) for k in yes_keywords) or "add more" in q.lower() or "more details" in q.lower()

        if wants_more:
            # Move to a typing stage — let the user type freely
            session["stage"] = "addl_info_type"
            prompt = _TYPE_ADDL_PROMPT.get(lang, _TYPE_ADDL_PROMPT["English"])
            logger.info(f"[{session_id[:8]}] User wants to add more -> addl_info_type")
            return _resp(prompt, session_id, session, "addl_info_type",
                         options=[], suggestions=[], free_text=True,
                         onboarding_key="additional_info_text")
        else:
            # User said No or typed something non-yes — generate summary now
            # If they typed actual content (not just "no"), save it as extra info
            no_keywords = {"no", "nahi", "nope", "nahi,", "no,", "இல்லை", "లేదు", "ಇಲ್ಲ", "नाही", "না", "ના"}
            if q.lower().strip().rstrip(".,!") not in no_keywords and len(q) > 4:
                session["profile"]["additional_info"] = q
            logger.info(f"[{session_id[:8]}] No extra info -> generating summary")
            return await _generate_summary(session_id, session)

    # ------------------------------------------------------------------
    # STAGE: addl_info_type — user typed their additional details
    # ------------------------------------------------------------------
    if session["stage"] == "addl_info_type":
        logger.info(f"[{session_id[:8]}] Additional info typed -> generating summary")
        return await _generate_summary(session_id, session, extra_info=q)

    # ------------------------------------------------------------------
    # STAGE: followup — flexible Q&A
    # Instead of re-generating the entire summary every time, route the
    # user's question through the RAG agent as a focused follow-up query.
    # This produces a concise, targeted answer rather than repeating the
    # full legal summary layout.
    # ------------------------------------------------------------------
    set_language_instruction(session)
    logger.info(f"[{session_id[:8]}] Followup lang='{lang}' name='{session['profile'].get('name')}' query='{q[:60]}'")

    # Save any additional context into profile for completeness
    existing_extra = session["profile"].get("additional_info") or ""
    combined_extra = "; ".join(p for p in [existing_extra, q.strip()] if p)
    session["profile"]["additional_info"] = combined_extra

    # Build a focused follow-up prompt instead of the full summary prompt
    name = session["profile"].get("name") or "the user"
    situation = session["profile"].get("situation_type", "a legal matter")
    state = session["profile"].get("state", "India")

    followup_query = (
        f"The user ({name}) previously received a full legal summary about their "
        f"{situation} situation in {state}. Now they have a follow-up question or "
        f"additional information:\n\n"
        f"\"{q}\"\n\n"
        f"Please answer this specific question directly. If the new information "
        f"changes the case prediction or legal strategy, explain how and why. "
        f"Do NOT regenerate the entire legal summary — focus only on addressing "
        f"the user's current question with relevant legal analysis and updated predictions "
        f"where applicable. Be concise but thorough.\n\n"
        f"Respond in {lang}. Do not use emojis."
    )

    session["history"].append({"role": "user", "content": q})

    result = agent.generate_response(
        query=followup_query,
        stage="followup",
        conversation_history=session["history"],
        language=lang,
        user_profile=session["profile"],
    )

    response_text = result.get("response", "I could not generate a response. Please try again.")
    session["history"].append({"role": "assistant", "content": response_text})

    if len(session["history"]) > 40:
        session["history"] = session["history"][-40:]

    return _resp(
        response_text, session_id, session, "followup",
        sources=result.get("sources", []),
        provider=result.get("provider"),
        domain=result.get("domain", []),
        risk_level=result.get("risk", {}).get("level", "low"),
        emotional_state=result.get("emotional_state"),
        retrieval_error=result.get("retrieval_error"),
        free_text=True,
    )


class ClarifyRequest(BaseModel):
    session_id: str
    original_query: str
    selected_intent: str
    language: str = "English"


@app.post("/api/clarify", response_model=ChatResponse)
async def clarify(request: ClarifyRequest):
    """Handle option-click selections. Routes through /api/chat with the selected intent as the query."""
    session_id = request.session_id
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[session_id]
    pre_summary_stages = ("greeting", "onboarding", "deep_dive", "addl_info", "addl_info_type")

    if session["stage"] in pre_summary_stages:
        return await chat(ChatRequest(
            query=request.selected_intent,
            session_id=session_id,
            language=get_session_language(session),
        ))

    # Post-summary clarification — expand the selected intent and answer as a follow-up
    lang = get_session_language(session)
    set_language_instruction(session)

    expanded = expand_query(
        original_query=request.original_query,
        selected_intent=request.selected_intent,
        conversation_history=session["history"],
        user_profile=session["profile"],
    )

    result = agent.generate_response(
        query=expanded,
        stage=session["stage"],
        conversation_history=session["history"],
        language=lang,
        user_profile=session["profile"],
    )

    session["history"].append({"role": "user", "content": request.original_query})
    session["history"].append({"role": "user", "content": f"[Clarification: {request.selected_intent}]"})
    session["history"].append({"role": "assistant", "content": result["response"]})

    if not result.get("is_greeting", False):
        session["stage"] = result.get("stage", "followup")
    if len(session["history"]) > 40:
        session["history"] = session["history"][-40:]

    return _resp(
        result["response"], session_id, session, session["stage"],
        sources=result.get("sources", []),
        provider=result.get("provider"),
        risk_level=result.get("risk", {}).get("level", "low"),
        domain=result.get("domain", []),
        emotional_state=result.get("emotional_state"),
        retrieval_error=result.get("retrieval_error"),
        needs_clarification=result.get("needs_clarification", False),
        suggestions=result.get("suggestions"),
        options=result.get("options") or [],
    )


@app.post("/api/ingest")
async def trigger_ingest(force: bool = False):
    if ingest_status["running"]:
        return {"status": "already_running", "message": "Ingestion is already in progress."}

    def run_ingest():
        ingest_status["running"] = True
        try:
            from pipeline.ingest import run_ingestion
            run_ingestion(force=force)
            ingest_status["last_result"] = {"status": "success", "time": datetime.now().isoformat()}
        except Exception as e:
            logger.error(f"Ingestion failed: {e}")
            ingest_status["last_result"] = {"status": "error", "error": str(e), "time": datetime.now().isoformat()}
        finally:
            ingest_status["running"] = False

    threading.Thread(target=run_ingest, daemon=True).start()
    return {"status": "started", "message": "Ingestion pipeline started in background."}


@app.get("/api/ingest/status")
async def ingest_status_endpoint():
    return {"running": ingest_status["running"], "last_result": ingest_status["last_result"]}


@app.get("/api/providers")
async def list_providers():
    return {"providers": get_available_providers(), "recent_failures": get_failure_log()}


@app.post("/api/upload_pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")
    safe_name = file.filename.replace(" ", "_")
    content = await file.read()
    with open(PDF_DIR / safe_name, "wb") as f:
        f.write(content)
    return {"status": "uploaded", "filename": safe_name, "size_bytes": len(content),
            "message": "PDF saved. Use /api/ingest to index it."}


@app.post("/api/session/clear")
async def clear_session(session_id: str = ""):
    if session_id in sessions:
        del sessions[session_id]
    return {"status": "cleared"}


# ── Admin redirect: forward /admin/* to React dev server (local) ──
@app.get("/admin/{path:path}")
async def admin_redirect(path: str):
    return RedirectResponse(url=f"http://localhost:5173/admin/{path}", status_code=302)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
else:
    @app.get("/")
    async def no_frontend():
        return {"message": "Frontend not found. Place files in /frontend/"}


@app.on_event("startup")
async def startup_event():
    providers = get_available_providers()
    active = [k for k, v in providers.items() if v]
    logger.info("=" * 60)
    logger.info(" NyayaDepaaAI 4.0 — Women Safety Legal Advisor")
    logger.info("=" * 60)
    logger.info(f" LLM Providers: {', '.join(active) if active else 'NONE!'}")
    logger.info(f" Pinecone: {'✓' if PINECONE_API_KEY else '✗ NOT SET'}")
    logger.info(f" Jina Embed: {'✓' if JINA_API_KEY else '✗ NOT SET'}")
    logger.info(f" Frontend: {'✓' if FRONTEND_DIR.exists() else '✗ missing'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
