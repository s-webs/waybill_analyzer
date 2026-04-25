"""
Post-processing validation for AI invoice results.
"""
from __future__ import annotations


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

    validation["warnings"] = warnings
    result["validation"] = validation
    return result
