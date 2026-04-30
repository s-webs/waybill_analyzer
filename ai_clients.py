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

from prompts import (
    INVOICE_SYSTEM_PROMPT,
    INVOICE_USER_PROMPT,
    MARKETPLACE_USER_PROMPT,
    MARKET_SOURCE_ROUTER_SYSTEM_PROMPT,
    MARKET_SOURCE_ROUTER_USER_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    ROUTER_USER_PROMPT,
    SYSTEM_PROMPT,
    USER_PROMPT,
    OZON_SIGNAL_SYSTEM_PROMPT,
    OZON_SIGNAL_USER_PROMPT,
    WB_SIGNAL_SYSTEM_PROMPT,
    WB_SIGNAL_USER_PROMPT,
    build_marketplace_system_prompt,
)

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


def _chat_completion_with_image(
    client,
    b64: str,
    mime: str,
    model: str,
    temperature: float,
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
) -> str:
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
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
                        "text": user_prompt,
                    },
                ],
            },
        ],
    )
    return response.choices[0].message.content


def _normalize_route(route: object) -> str:
    value = str(route or "").strip().lower()
    if value in {"invoice", "wildberries", "ozon"}:
        return value
    return "unknown"


def _classify_route(
    client,
    b64: str,
    mime: str,
    model: str,
) -> tuple[str, str | None]:
    try:
        raw = _chat_completion_with_image(
            client=client,
            b64=b64,
            mime=mime,
            model=model,
            temperature=0.0,
            max_tokens=250,
            system_prompt=ROUTER_SYSTEM_PROMPT,
            user_prompt=ROUTER_USER_PROMPT,
        )
        parsed = _parse_response(raw)
        if parsed.get("ok"):
            route = _normalize_route((parsed.get("data") or {}).get("route"))
            return route, raw
        return "unknown", raw
    except Exception:
        return "unknown", None


def _classify_market_source(
    client,
    b64: str,
    mime: str,
    model: str,
) -> tuple[str, str | None]:
    try:
        raw = _chat_completion_with_image(
            client=client,
            b64=b64,
            mime=mime,
            model=model,
            temperature=0.0,
            max_tokens=220,
            system_prompt=MARKET_SOURCE_ROUTER_SYSTEM_PROMPT,
            user_prompt=MARKET_SOURCE_ROUTER_USER_PROMPT,
        )
        parsed = _parse_response(raw)
        if parsed.get("ok"):
            route = _normalize_route((parsed.get("data") or {}).get("route"))
            if route in {"ozon", "wildberries"}:
                return route, raw
            return "unknown", raw
        return "unknown", raw
    except Exception:
        return "unknown", None


def _prompts_for_route(route: str) -> tuple[str, str]:
    if route == "invoice":
        return INVOICE_SYSTEM_PROMPT, INVOICE_USER_PROMPT
    if route == "wildberries":
        return build_marketplace_system_prompt("Wildberries"), MARKETPLACE_USER_PROMPT
    if route == "ozon":
        return build_marketplace_system_prompt("Ozon"), MARKETPLACE_USER_PROMPT
    return SYSTEM_PROMPT, USER_PROMPT


def _extract_wb_signals(
    client,
    b64: str,
    mime: str,
    model: str,
) -> dict:
    try:
        raw = _chat_completion_with_image(
            client=client,
            b64=b64,
            mime=mime,
            model=model,
            temperature=0.0,
            max_tokens=160,
            system_prompt=WB_SIGNAL_SYSTEM_PROMPT,
            user_prompt=WB_SIGNAL_USER_PROMPT,
        )
        parsed = _parse_response(raw)
        if parsed.get("ok") and isinstance(parsed.get("data"), dict):
            return parsed["data"]
        return {}
    except Exception:
        return {}


def _extract_ozon_signals(
    client,
    b64: str,
    mime: str,
    model: str,
) -> dict:
    try:
        raw = _chat_completion_with_image(
            client=client,
            b64=b64,
            mime=mime,
            model=model,
            temperature=0.0,
            max_tokens=160,
            system_prompt=OZON_SIGNAL_SYSTEM_PROMPT,
            user_prompt=OZON_SIGNAL_USER_PROMPT,
        )
        parsed = _parse_response(raw)
        if parsed.get("ok") and isinstance(parsed.get("data"), dict):
            return parsed["data"]
        return {}
    except Exception:
        return {}


def _ensure_object_payload(parsed: dict) -> dict:
    """
    Ensure extraction result is a JSON object.
    If model returns array/scalar, mark as parse failure to avoid downstream crashes.
    """
    if not parsed.get("ok"):
        return parsed
    data = parsed.get("data")
    if isinstance(data, dict):
        return parsed
    return {
        "ok": False,
        "error": f"Expected JSON object, got {type(data).__name__}",
        "raw": parsed.get("raw_response") or "",
    }


def _items_count_from_parsed(parsed: dict) -> int:
    if not parsed.get("ok"):
        return 0
    data = parsed.get("data")
    if not isinstance(data, dict):
        return 0
    items = data.get("items")
    if not isinstance(items, list):
        return 0
    return len(items)


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

    route, route_raw = _classify_route(client=client, b64=b64, mime=mime, model=model)
    # Second-pass router for marketplace-like screenshots:
    # if first pass is unknown, try to force ozon/wildberries discrimination.
    if route == "unknown":
        source_route, source_raw = _classify_market_source(client=client, b64=b64, mime=mime, model=model)
        if source_route in {"ozon", "wildberries"}:
            route = source_route
            if source_raw:
                route_raw = source_raw

    system_prompt, user_prompt = _prompts_for_route(route)

    try:
        raw_content = _chat_completion_with_image(
            client=client,
            b64=b64,
            mime=mime,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    parsed = _parse_response(raw_content)
    parsed["raw_response"] = raw_content
    parsed = _ensure_object_payload(parsed)

    # Fallback: if route-specific prompt produced invalid JSON object
    # or empty items, try universal prompt once and keep the better result.
    if route != "unknown" and (
        not parsed.get("ok") or _items_count_from_parsed(parsed) == 0
    ):
        try:
            fallback_raw = _chat_completion_with_image(
                client=client,
                b64=b64,
                mime=mime,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT,
            )
            fallback_parsed = _parse_response(fallback_raw)
            fallback_parsed["raw_response"] = fallback_raw
            fallback_parsed = _ensure_object_payload(fallback_parsed)
            if (
                fallback_parsed.get("ok")
                and _items_count_from_parsed(fallback_parsed) >= _items_count_from_parsed(parsed)
            ):
                parsed = fallback_parsed
        except Exception:
            pass

    if parsed.get("ok"):
        data = parsed.get("data") or {}
        if isinstance(data, dict):
            raw_obs = data.get("raw_text_observations")
            if not isinstance(raw_obs, list):
                raw_obs = []
            raw_obs = [str(x) for x in raw_obs]
            raw_obs.insert(0, f"route={route}")
            if route == "wildberries":
                wb_signals = _extract_wb_signals(client=client, b64=b64, mime=mime, model=model)
                orders_count = wb_signals.get("orders_count")
                units_per_order = wb_signals.get("units_per_order")
                if isinstance(orders_count, (int, float)) and orders_count > 0:
                    raw_obs.insert(1, f"wb_orders={orders_count}")
                if isinstance(units_per_order, (int, float)) and units_per_order > 0:
                    raw_obs.insert(1, f"wb_units_per_order={units_per_order}")
            elif route == "ozon":
                ozon_signals = _extract_ozon_signals(client=client, b64=b64, mime=mime, model=model)
                orders_count = ozon_signals.get("orders_count")
                units_per_order = ozon_signals.get("units_per_order")
                if isinstance(orders_count, (int, float)) and orders_count > 0:
                    raw_obs.insert(1, f"ozon_orders={orders_count}")
                if isinstance(units_per_order, (int, float)) and units_per_order > 0:
                    raw_obs.insert(1, f"ozon_units_per_order={units_per_order}")
            data["raw_text_observations"] = raw_obs
            if route == "invoice":
                data["document_type"] = "invoice"
            elif route in {"wildberries", "ozon"}:
                data["document_type"] = "receipt"
                data["supplier"] = "Wildberries" if route == "wildberries" else "Ozon"
            parsed["data"] = data

    if not parsed.get("raw_response"):
        parsed["raw_response"] = raw_content
    if route_raw:
        parsed["route_raw_response"] = route_raw
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
