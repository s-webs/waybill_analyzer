"""
HTTP API transport for waybill analyzer.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_clients import analyze_invoice_with_ai
from validators import validate_invoice_result

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024

app = FastAPI(title="alfoods_waybill_analyzer", version="1.0.0")
WEB_DIR = Path(__file__).parent / "web"

if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


class AnalyzeResponse(BaseModel):
    ok: bool
    schema_version: str = "1.0"
    result: dict | None = None
    error: str | None = None
    raw_response: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ui")
def ui() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI is not available.")
    return FileResponse(index_path)


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile = File(...),
    provider: str = Form("openai"),
    model: str = Form("gpt-4.1-mini"),
    temperature: float = Form(0.05),
    max_tokens: int = Form(3000),
) -> AnalyzeResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="File size exceeds 10 MB.")

    suffix = Path(file.filename or "").suffix.lower()
    content_type_allowed = file.content_type in ALLOWED_MIME_TYPES
    extension_allowed = suffix in ALLOWED_EXTENSIONS
    signature_allowed = _looks_like_image(data)

    # Accept if at least one signal confirms image type.
    # This handles clients that send octet-stream or temp filenames.
    if not (content_type_allowed or extension_allowed or signature_allowed):
        raise HTTPException(status_code=422, detail="Unsupported image type.")
    if not signature_allowed:
        raise HTTPException(status_code=422, detail="Uploaded file is not a valid image.")

    output_suffix = suffix if suffix in ALLOWED_EXTENSIONS else _guess_suffix_from_bytes(data)
    with tempfile.NamedTemporaryFile(delete=False, suffix=output_suffix) as tmp_file:
        tmp_file.write(data)
        image_path = tmp_file.name

    try:
        ai_result = analyze_invoice_with_ai(
            image_path=image_path,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw_response = ai_result.get("raw_response")
        if not ai_result.get("ok"):
            return AnalyzeResponse(
                ok=False,
                error=ai_result.get("error", "Failed to parse AI response."),
                raw_response=raw_response,
            )

        validated = validate_invoice_result(ai_result["data"])
        validated.setdefault("schema_version", "1.0")
        return AnalyzeResponse(ok=True, result=validated, raw_response=raw_response)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Analyzer upstream error: {exc}") from exc
    finally:
        Path(image_path).unlink(missing_ok=True)


def _looks_like_image(data: bytes) -> bool:
    # JPEG
    if data.startswith(b"\xFF\xD8\xFF"):
        return True
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    # WEBP: RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def _guess_suffix_from_bytes(data: bytes) -> str:
    if data.startswith(b"\xFF\xD8\xFF"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"
