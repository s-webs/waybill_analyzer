# Waybill Analyzer HTTP API Contract

## Endpoints

### `GET /health`
- **200 OK**
```json
{"status":"ok"}
```

### `POST /analyze`
- `multipart/form-data`
- Required field: `file` (`image/jpeg`, `image/png`, `image/webp`, max 10 MB)
- Optional fields:
  - `provider` (default: `openai`)
  - `model` (default: `gpt-4.1-mini`)
  - `temperature` (default: `0.05`)
  - `max_tokens` (default: `3000`)

## Success response

- **200 OK**
```json
{
  "ok": true,
  "schema_version": "1.0",
  "result": {
    "schema_version": "1.0",
    "document_type": "invoice",
    "invoice_number": null,
    "invoice_date": null,
    "supplier": null,
    "buyer": null,
    "currency": "KZT",
    "items": [
      {
        "row": 1,
        "name": "Product name",
        "quantity": 1,
        "unit": "pcs",
        "price": 100,
        "amount": 100,
        "barcode": "4876543210987",
        "nomenclature_code": null,
        "confidence": "high",
        "notes": null
      }
    ],
    "totals": {
      "items_count": 1,
      "total_quantity": 1,
      "total_amount": 100
    },
    "validation": {
      "amounts_sum": 100,
      "amounts_match_total": true,
      "has_unclear_rows": false,
      "needs_review": false,
      "warnings": []
    },
    "raw_text_observations": []
  },
  "error": null,
  "raw_response": "{\"...\": \"...\"}"
}
```

## Parse failure response

- **200 OK**
```json
{
  "ok": false,
  "schema_version": "1.0",
  "result": null,
  "error": "JSON decode error details",
  "raw_response": "raw model output"
}
```

## Validation and transport errors

- **422** unsupported type, empty file, or too large file.
- **502** upstream provider error.
