import os
from dotenv import load_dotenv

load_dotenv()

# Ollama — defaults allow zero-config on a standard local install
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "llama3.1:8b")

# Telegram — required; no sensible default exists
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

_REQUIRED = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID":   TELEGRAM_CHAT_ID,
}

missing = [k for k, v in _REQUIRED.items() if not v]
if missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(missing)}\n"
        "Copy .env.example to .env and fill in your values."
    )
