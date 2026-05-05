import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
]
# Model selection: light for simple tasks, heavy for complex reasoning
MODEL_LIGHT = os.getenv("MODEL_LIGHT", "MiniMax-M2.5")
MODEL_HEAVY = os.getenv("MODEL_HEAVY", "MiniMax-M2.7")

# Max number of message pairs (user+assistant) to keep in chat memory
CHAT_MEMORY_SIZE = int(os.getenv("CHAT_MEMORY_SIZE", "20"))
