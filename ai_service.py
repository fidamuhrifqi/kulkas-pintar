import json
import logging
import re
from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError

from config import MINIMAX_API_KEY, MINIMAX_BASE_URL, MODEL_LIGHT, MODEL_HEAVY

logger = logging.getLogger("kulkas-bot")

# OpenAI-compatible client pointed at MiniMax
ai = OpenAI(api_key=MINIMAX_API_KEY, base_url=MINIMAX_BASE_URL)

def call_ai(system_prompt: str, user_message: str, model: str = None) -> str:
    """
    Call MiniMax API via OpenAI-compatible SDK.
    Uses the specified model, defaults to MODEL_LIGHT.
    Returns the assistant's reply text.
    Raises on timeout / connection / API errors.
    """
    try:
        response = ai.chat.completions.create(
            model=model or MODEL_LIGHT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=2048,
            timeout=30,
        )
        result = response.choices[0].message.content.strip()
        # Strip <think>...</think> reasoning blocks (MiniMax M2.7 thinking model)
        result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
        return result
    except APITimeoutError:
        logger.error("MiniMax API timeout")
        raise
    except APIConnectionError:
        logger.error("MiniMax API connection error")
        raise
    except APIStatusError as e:
        logger.error("MiniMax API status error: %s", e)
        raise

def call_ai_chat(system_prompt: str, user_message: str, history: list, model: str = None) -> str:
    """
    Call MiniMax API with conversation history for multi-turn chat.
    'history' is a list of {"role": ..., "content": ...} dicts.
    Returns the assistant's reply text.
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = ai.chat.completions.create(
            model=model or MODEL_HEAVY,
            messages=messages,
            temperature=0.4,
            max_tokens=2048,
            timeout=30,
        )
        result = response.choices[0].message.content.strip()
        # Strip <think>...</think> reasoning blocks (MiniMax thinking model)
        result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
        return result
    except APITimeoutError:
        logger.error("MiniMax API timeout")
        raise
    except APIConnectionError:
        logger.error("MiniMax API connection error")
        raise
    except APIStatusError as e:
        logger.error("MiniMax API status error: %s", e)
        raise

def parse_ai_json(raw: str) -> dict | None:
    """
    Attempt to extract a JSON object from the AI response.
    Strips <think> reasoning blocks and markdown fences if present.
    Returns parsed dict or None.
    """
    text = raw.strip()

    # Strip <think>...</think> reasoning blocks (MiniMax M2.7 thinking model)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines if they are fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI JSON: %s", text[:300])
        return None
