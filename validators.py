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


_QTY_FORMULA_RE = re.compile(
    r"quantity\s*=\s*(\d+(?:[.,]\d+)?)\s*([+*xX])\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _extract_package_sizes(text: str | None) -> list[float]:
    if not text:
        return []
    matches = _PACK_UNITS_RE.findall(text)
    if not matches:
        return []
    candidates = []
    for match in matches:
        size = _to_float(match)
        if size and size > 1:
            candidates.append(size)
    # Keep order, remove near-duplicates.
    unique: list[float] = []
    for value in candidates:
        if not any(abs(value - existing) < 1e-6 for existing in unique):
            unique.append(value)
    return unique


def _merge_sizes(primary: list[float], secondary: list[float]) -> list[float]:
    merged: list[float] = []
    for value in [*primary, *secondary]:
        if not any(abs(value - existing) < 1e-6 for existing in merged):
            merged.append(value)
    return merged


def _is_wildberries_result(result: dict) -> bool:
    observations = result.get("raw_text_observations") or []
    return any(str(x).strip().lower() == "route=wildberries" for x in observations)


def _is_ozon_result(result: dict) -> bool:
    observations = result.get("raw_text_observations") or []
    return any(str(x).strip().lower() == "route=ozon" for x in observations)


def _extract_wb_observation_number(observations: list[object], key: str) -> float | None:
    prefix = f"{key}="
    for value in observations:
        s = str(value).strip()
        if s.startswith(prefix):
            return _to_float(s[len(prefix):])
    return None


def _apply_wildberries_quantity_fix(item: dict, wb_sizes: list[float]) -> None:
    """
    Wildberries-specific quantity correction:
    - "2 шт" near status badge means number of orders
    - "10 шт" on product card means units per order
    So total quantity should be multiplication, not addition.
    """
    quantity = _to_float(item.get("quantity"))
    if quantity is None or quantity <= 0:
        return

    a = b = None
    notes = str(item.get("notes") or "")
    formula_match = _QTY_FORMULA_RE.search(notes)
    if formula_match:
        left = _to_float(formula_match.group(1))
        op = formula_match.group(2)
        right = _to_float(formula_match.group(3))
        if left and right and left > 1 and right > 1:
            if op == "+":
                a, b = left, right
            elif op in {"*", "x", "X"}:
                return

    if a is None or b is None:
        if len(wb_sizes) >= 2:
            # Use two largest distinct sizes as order_count and units_per_order.
            sorted_sizes = sorted(wb_sizes, reverse=True)
            a, b = sorted_sizes[0], next((x for x in sorted_sizes[1:] if abs(x - sorted_sizes[0]) >= 1e-6), None)
            if b is None:
                return
        else:
            return

    product_qty = a * b
    sum_qty = a + b
    # Correct only when current quantity looks like an additive/read error.
    if abs(quantity - sum_qty) >= 1e-6 and abs(quantity - a) >= 1e-6 and abs(quantity - b) >= 1e-6:
        return

    item["quantity"] = int(product_qty) if float(product_qty).is_integer() else round(product_qty, 4)
    item["notes"] = f"quantity={_format_number(a)}*{_format_number(b)}"
    if item.get("confidence") == "high":
        item["confidence"] = "medium"

    amount = _to_float(item.get("amount"))
    final_qty = _to_float(item.get("quantity"))
    if amount is not None and final_qty is not None and final_qty > 0:
        item["price"] = round(amount / final_qty, 4)


def _apply_wildberries_quantity_from_signals(
    item: dict,
    orders_count: float | None,
    units_per_order: float | None,
) -> bool:
    if not orders_count or not units_per_order or orders_count <= 0 or units_per_order <= 0:
        return False
    # Guard against duplicated extraction of the same visible number (e.g. 24 and 24),
    # which leads to invalid 24*24 multiplication.
    if abs(orders_count - units_per_order) < 1e-6:
        return False
    total_qty = orders_count * units_per_order
    item["quantity"] = int(total_qty) if float(total_qty).is_integer() else round(total_qty, 4)
    item["notes"] = f"quantity={_format_number(units_per_order)}*{_format_number(orders_count)}"
    if item.get("confidence") == "high":
        item["confidence"] = "medium"
    amount = _to_float(item.get("amount"))
    final_qty = _to_float(item.get("quantity"))
    if amount is not None and final_qty and final_qty > 0:
        item["price"] = round(amount / final_qty, 4)
    return True


def _apply_ozon_quantity_from_signals(
    item: dict,
    orders_count: float | None,
    units_per_order: float | None,
) -> bool:
    if not orders_count or not units_per_order or orders_count <= 0 or units_per_order <= 0:
        return False
    if abs(orders_count - units_per_order) < 1e-6:
        return False
    current_qty = _to_float(item.get("quantity"))
    # Apply only when current quantity is likely order count (or close to it).
    if current_qty is not None and abs(current_qty - orders_count) > 1e-6:
        return False
    total_qty = orders_count * units_per_order
    item["quantity"] = int(total_qty) if float(total_qty).is_integer() else round(total_qty, 4)
    item["notes"] = f"quantity={_format_number(orders_count)}*{_format_number(units_per_order)}"
    if item.get("confidence") == "high":
        item["confidence"] = "medium"
    amount = _to_float(item.get("amount"))
    final_qty = _to_float(item.get("quantity"))
    if amount is not None and final_qty and final_qty > 0:
        item["price"] = round(amount / final_qty, 4)
    return True


def _apply_marketplace_quantity_multiplier(item: dict, fallback_package_sizes: list[float] | None = None) -> None:
    """
    If quantity is the number of positions (e.g. 3) and the name contains
    "30 штук", convert quantity to total units (3 * 30 = 90).
    """
    quantity = _to_float(item.get("quantity"))
    name = (item.get("name") or "").strip()
    if quantity is None or quantity <= 0 or not name:
        return

    package_sizes = _extract_package_sizes(name)
    if fallback_package_sizes:
        package_sizes = _merge_sizes(package_sizes, fallback_package_sizes)
    if not package_sizes:
        return

    # Safety: if we only detected one size and it is equal to current quantity,
    # this is usually the same signal duplicated (e.g. "10 шт" in one bubble),
    # not "positions * pack_size". Do not multiply in this case.
    if len(package_sizes) == 1 and abs(package_sizes[0] - quantity) < 1e-6:
        return

    # Choose multiplier robustly:
    # - if quantity equals one detected size (e.g. quantity=10 and text has "2 шт" + "10 шт"),
    #   then multiply by the other size (=> 10 * 2).
    # - otherwise use the largest detected size.
    package_size = max(package_sizes)
    same_as_qty = [size for size in package_sizes if abs(size - quantity) < 1e-6]
    if same_as_qty:
        others = [size for size in package_sizes if abs(size - quantity) >= 1e-6]
        if others:
            package_size = max(others)

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
    document_type = str(result.get("document_type") or "").strip().lower()
    is_invoice_document = document_type == "invoice"
    is_wildberries_document = _is_wildberries_result(result)
    is_ozon_document = _is_ozon_result(result)

    items: list[dict] = result.get("items") or []
    for item in items:
        item["unit"] = "pcs"

    # Apply marketplace quantity/pack heuristics only for non-invoice docs.
    # For invoices we should trust table columns, not package hints in item names.
    if not is_invoice_document:
        raw_observations = result.get("raw_text_observations") or []
        fallback_package_sizes: list[float] = []
        if len(items) == 1 and raw_observations:
            fallback_package_sizes = _extract_package_sizes(" ".join(str(x) for x in raw_observations))

        if is_wildberries_document:
            wb_orders = _extract_wb_observation_number(raw_observations, "wb_orders")
            wb_units = _extract_wb_observation_number(raw_observations, "wb_units_per_order")
            for item in items:
                applied = _apply_wildberries_quantity_from_signals(
                    item,
                    orders_count=wb_orders,
                    units_per_order=wb_units,
                )
                if not applied:
                    # For multi-item WB screenshots, rely on per-item name patterns
                    # (e.g. "30 штук") to avoid cross-item contamination from shared observations.
                    _apply_marketplace_quantity_multiplier(item, fallback_package_sizes=None)
        elif is_ozon_document:
            ozon_orders = _extract_wb_observation_number(raw_observations, "ozon_orders")
            ozon_units = _extract_wb_observation_number(raw_observations, "ozon_units_per_order")
            for item in items:
                applied = _apply_ozon_quantity_from_signals(
                    item,
                    orders_count=ozon_orders,
                    units_per_order=ozon_units,
                )
                if not applied:
                    _apply_marketplace_quantity_multiplier(item, fallback_package_sizes=fallback_package_sizes)
        else:
            for item in items:
                _apply_marketplace_quantity_multiplier(item, fallback_package_sizes=fallback_package_sizes)

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

    # Reconcile inconsistent quantity using amount/price when both are reliable.
    # This guards against occasional LLM spikes like quantity=72 while amount/price imply 12.
    for item in items:
        amount = _to_float(item.get("amount"))
        price = _to_float(item.get("price"))
        quantity = _to_float(item.get("quantity"))
        if amount is None or price is None or quantity is None or price <= 0 or quantity <= 0:
            continue

        implied_qty = amount / price
        # Apply only for material mismatches.
        if abs(implied_qty - quantity) < 0.51:
            continue

        rounded_implied = round(implied_qty)
        if abs(implied_qty - rounded_implied) <= 0.25 and rounded_implied > 0:
            item["quantity"] = int(rounded_implied)
        else:
            item["quantity"] = round(implied_qty, 4)

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
