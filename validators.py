"""
Post-processing validation for AI invoice results.
"""
from __future__ import annotations

import re


_PACK_UNITS_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:шт(?:\.|ук|уки|ука)?|pcs?|pieces?)(?:\b|(?=\s|$|[.,;:]))",
    re.IGNORECASE,
)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(round(value, 4))


def _extract_package_size(text: str | None) -> float | None:
    if not text:
        return None
    matches = _PACK_UNITS_RE.findall(text)
    if not matches:
        return None
    candidates = []
    for match in matches:
        size = _to_float(match)
        if size and size > 1:
            candidates.append(size)
    if not candidates:
        return None
    return max(candidates)


def _apply_marketplace_quantity_multiplier(item: dict, fallback_package_size: float | None = None) -> None:
    """
    If quantity is the number of positions (e.g. 3) and the name contains
    "30 штук", convert quantity to total units (3 * 30 = 90).
    """
    quantity = _to_float(item.get("quantity"))
    name = (item.get("name") or "").strip()
    if quantity is None or quantity <= 0 or not name:
        return

    package_size = _extract_package_size(name) or fallback_package_size
    if not package_size:
        return

    total_units = quantity * package_size
    item["quantity"] = int(total_units) if total_units.is_integer() else round(total_units, 4)

    # If price was recognized as "per package", normalize to "per 1 unit".
    # Example: 658 KZT for 6 pcs => 109.6667 KZT per unit.
    price = _to_float(item.get("price"))
    if price is not None and price > 0:
        unit_price = price / package_size
        item["price"] = round(unit_price, 4)

    # If amount is present and we have final quantity, keep price consistent with total amount.
    amount = _to_float(item.get("amount"))
    final_qty = _to_float(item.get("quantity"))
    if amount is not None and final_qty is not None and final_qty > 0:
        derived_unit_price = amount / final_qty
        if item.get("price") is None:
            item["price"] = round(derived_unit_price, 4)

    existing_notes = item.get("notes")
    formula = f"quantity={_format_number(quantity)}*{_format_number(package_size)}"
    if existing_notes:
        if "quantity=" not in str(existing_notes):
            item["notes"] = f"{existing_notes}; {formula}"
    else:
        item["notes"] = formula

    if item.get("confidence") == "high":
        item["confidence"] = "medium"


def validate_invoice_result(result: dict) -> dict:
    """
    Validate and enrich the invoice result dict returned by the AI.

    Checks:
    - items list is present and non-empty
    - computed sum of amounts vs totals.total_amount
    - confidence distribution
    - null coverage in key fields
    """
    validation = result.setdefault("validation", {})
    warnings: list[str] = validation.get("warnings") or []

    items: list[dict] = result.get("items") or []
    raw_observations = result.get("raw_text_observations") or []
    fallback_package_size = None
    if len(items) == 1 and raw_observations:
        fallback_package_size = _extract_package_size(" ".join(str(x) for x in raw_observations))

    for item in items:
        _apply_marketplace_quantity_multiplier(item, fallback_package_size=fallback_package_size)

    # Fill missing unit price for regular items:
    # if amount and quantity are known, derive price per one unit.
    for item in items:
        price = _to_float(item.get("price"))
        if price is not None and price > 0:
            continue
        amount = _to_float(item.get("amount"))
        quantity = _to_float(item.get("quantity"))
        if amount is None or quantity is None or quantity <= 0:
            continue
        item["price"] = round(amount / quantity, 4)

    # --- 1. Check items presence ----------------------------------------
    if not items:
        warnings.append("No items found in the document.")
        validation["needs_review"] = True
        validation["warnings"] = warnings
        return result

    # --- 2. Compute sum of amounts --------------------------------------
    amounts = []
    for item in items:
        amt = item.get("amount")
        if amt is not None:
            try:
                amounts.append(float(amt))
            except (TypeError, ValueError):
                pass

    if amounts:
        computed_sum = round(sum(amounts), 4)
        validation["amounts_sum"] = computed_sum

        total_amount = None
        totals = result.get("totals") or {}
        raw_total = totals.get("total_amount")
        if raw_total is not None:
            try:
                total_amount = float(raw_total)
            except (TypeError, ValueError):
                pass

        if total_amount is not None and total_amount > 0:
            diff_pct = abs(computed_sum - total_amount) / total_amount * 100
            if diff_pct > 5:
                validation["amounts_match_total"] = False
                warnings.append(
                    f"Sum of item amounts ({computed_sum:.2f}) differs from "
                    f"total_amount ({total_amount:.2f}) by {diff_pct:.1f}%."
                )
            else:
                validation["amounts_match_total"] = True
        else:
            validation["amounts_match_total"] = None
    else:
        validation["amounts_sum"] = None
        validation["amounts_match_total"] = None

    # --- 3. Confidence distribution ------------------------------------
    confidences = [item.get("confidence") for item in items]
    low_count = confidences.count("low")
    total_count = len(confidences)

    if total_count > 0 and low_count / total_count > 0.5:
        validation["needs_review"] = True
        warnings.append(
            f"{low_count} of {total_count} items have low confidence."
        )

    # --- 4. Null coverage in key fields --------------------------------
    key_fields = ["quantity", "price", "amount"]
    for field in key_fields:
        null_count = sum(1 for item in items if item.get(field) is None)
        null_pct = null_count / total_count * 100
        if null_pct > 50:
            validation["needs_review"] = True
            warnings.append(
                f"Field '{field}' is null for {null_count}/{total_count} items ({null_pct:.0f}%)."
            )

    # --- 5. Unclear rows flag -----------------------------------------
    has_unclear = any(
        item.get("confidence") == "low" or item.get("name") is None
        for item in items
    )
    validation["has_unclear_rows"] = has_unclear

    # --- 6. Update totals.items_count if missing ----------------------
    totals = result.setdefault("totals", {})
    if not totals.get("items_count"):
        totals["items_count"] = total_count

    quantity_values = []
    for item in items:
        qty = _to_float(item.get("quantity"))
        if qty is not None:
            quantity_values.append(qty)
    if quantity_values:
        total_quantity = round(sum(quantity_values), 4)
        totals["total_quantity"] = int(total_quantity) if total_quantity.is_integer() else total_quantity

    validation["warnings"] = warnings
    result["validation"] = validation
    return result
