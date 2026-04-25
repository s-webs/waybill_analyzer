"""
AI client layer — OpenAI vision integration.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from prompts import SYSTEM_PROMPT, USER_PROMPT

load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _image_to_base64(image_path: str) -> str:
    """Read an image file and return base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _detect_mime_type(image_path: str) -> str:
    suffix = Path(image_path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")


def _clean_json_response(raw: str) -> str:
    """
    Strip markdown fences and leading/trailing whitespace from AI response.
    Handles ```json ... ``` and ``` ... ``` blocks.
    """
    raw = raw.strip()
    # Remove ```json ... ``` or ``` ... ```
    pattern = r"^```(?:json)?\s*([\s\S]*?)\s*```$"
    match = re.match(pattern, raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw


def _parse_response(raw: str) -> dict:
    """
    Try to parse JSON from AI response.
    Returns {"ok": True, "data": dict} or {"ok": False, "error": str, "raw": str}.
    """
    cleaned = _clean_json_response(raw)
    try:
        data = json.loads(cleaned)
        return {"ok": True, "data": data}
    except json.JSONDecodeError as e:
        # Try to find JSON object inside the text (fallback)
        match = re.search(r"\{[\s\S]+\}", cleaned)
        if match:
            try:
                data = json.loads(match.group(0))
                return {"ok": True, "data": data}
            except json.JSONDecodeError:
                pass
        return {"ok": False, "error": str(e), "raw": raw}


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def _analyze_with_openai(
    image_path: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "openai package is not installed. Run: pip install openai"
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to your .env file."
        )

    b64 = _image_to_base64(image_path)
    mime = _detect_mime_type(image_path)

    client = OpenAI(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": USER_PROMPT,
                        },
                    ],
                },
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    raw_content = response.choices[0].message.content
    parsed = _parse_response(raw_content)
    parsed["raw_response"] = raw_content
    return parsed


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def analyze_invoice_with_ai(
    image_path: str,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict:
    """
    Unified entry point.

    Returns:
        {
            "ok": bool,
            "data": dict | None,        # parsed JSON result
            "error": str | None,        # error message if ok=False
            "raw_response": str | None, # raw AI text
        }
    """
    if provider != "openai":
        raise ValueError(f"Unknown provider: {provider!r}")

    return _analyze_with_openai(
        image_path=image_path,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
