"""Shared deterministic rendering for validated analysis Claim text."""

from __future__ import annotations


def format_numeric_value(value: float, unit: str) -> str:
    numeric = float(value)
    if numeric.is_integer():
        number = str(int(numeric))
    else:
        number = f"{numeric:.3g}"
    return f"{number} {unit}"


def render_validated_claim_text(claim) -> str:
    text = claim.text_template
    for binding in claim.numeric_bindings:
        text = text.replace(
            "{" + binding.binding_id + "}",
            format_numeric_value(binding.value, binding.unit),
        )
    return text


__all__ = ["format_numeric_value", "render_validated_claim_text"]
