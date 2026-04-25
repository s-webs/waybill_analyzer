from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class InvoiceItem(BaseModel):
    row: Optional[int] = None
    name: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    price: Optional[float] = None
    amount: Optional[float] = None
    barcode: Optional[str] = None
    nomenclature_code: Optional[str] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None
    notes: Optional[str] = None


class InvoiceTotals(BaseModel):
    items_count: int = 0
    total_quantity: Optional[float] = None
    total_amount: Optional[float] = None


class InvoiceValidation(BaseModel):
    amounts_sum: Optional[float] = None
    amounts_match_total: Optional[bool] = None
    has_unclear_rows: bool = False
    needs_review: bool = True
    warnings: List[str] = Field(default_factory=list)


class InvoiceResult(BaseModel):
    schema_version: str = "1.0"
    document_type: Literal["invoice", "handwritten_list", "receipt", "unknown"] = "unknown"
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    supplier: Optional[str] = None
    buyer: Optional[str] = None
    currency: str = "KZT"
    items: List[InvoiceItem] = Field(default_factory=list)
    totals: InvoiceTotals = Field(default_factory=InvoiceTotals)
    validation: InvoiceValidation = Field(default_factory=InvoiceValidation)
    raw_text_observations: List[str] = Field(default_factory=list)


class PreprocessingSettings(BaseModel):
    enable_preprocessing: bool = True
    auto_rotate: bool = True
    detect_corners: bool = True
    perspective_correction: bool = True
    grayscale: bool = False
    clahe_contrast: bool = True
    denoise: bool = True
    sharpen: bool = True
    threshold: bool = False
    resize_max_side: int = 1800


class AISettings(BaseModel):
    provider: Literal["openai"] = "openai"
    model: str = "gpt-4.1-mini"
    temperature: float = 0.05
    max_tokens: int = 3000
    image_source: Literal["original"] = "original"
