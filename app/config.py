"""
app/config.py
--------------
Central configuration for NyayaDepaaAI Women Safety Legal Advisor.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Pinecone ──────────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "nyayadepaa")

# ── Jina Embeddings ───────────────────────────────────────
JINA_API_KEY = os.getenv("JINA_API_KEY", "")
JINA_MODEL = os.getenv("JINA_MODEL", "jina-embeddings-v2-base-en")
EMBEDDING_DIM = 768

# ── LLM Providers (fallback chain) ────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.5"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1500"))

# ── Server ────────────────────────────────────────────────
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")

# ── Chunking ──────────────────────────────────────────────
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
MIN_CHUNK_SIZE = 100

# ── Retrieval ─────────────────────────────────────────────
TOP_K_RETRIEVE = int(os.getenv("TOP_K_RETRIEVE", "8"))
TOP_K_RERANK = int(os.getenv("TOP_K_RERANK", "4"))
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() == "true"
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "4000"))

# ── Namespaces ────────────────────────────────────────────
LEGAL_NAMESPACES = [
    "criminal_law",
    "workplace_harassment",
    "domestic_violence",
    "cyber_crime",
    "reporting_procedure",
    "case_duration",
    "general",
]

# ── Paths ─────────────────────────────────────────────────
FRONTEND_DIR = PROJECT_ROOT / "frontend"
PDF_DIR = PROJECT_ROOT / "pdfs"
DATA_DIR = PROJECT_ROOT / "data"
DATASET_FILE = DATA_DIR / "dataset.jsonl"
INGEST_HASH_FILE = DATA_DIR / "ingested_hashes.json"

# ── Case Analysis System ──────────────────────────────────
CASE_DB_PATH = PROJECT_ROOT / "chroma_db" / "legal_cases"
CASE_COLLECTION_NAME = os.getenv("CASE_COLLECTION_NAME", "legal_cases")
CASE_TOP_K = int(os.getenv("CASE_TOP_K", "8"))
CASE_DATASET_FILE = DATA_DIR / "legal_cases.json"
