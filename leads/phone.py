"""Canonical lead-phone normalization for FR-P4-04."""


def normalize_phone(value):
    """Return a canonical phone string, or ``None`` when it cannot be normalized."""
    raw = str(value or "").strip()
    compact = "".join(character for character in raw if character.isdigit() or character == "+")

    if compact.startswith("+"):
        digits = compact[1:]
        if digits.startswith("91") and len(digits) == 12:
            return "+91" + digits[2:]
        if 7 <= len(digits) <= 15:
            return "+" + digits
        return None

    digits = "".join(character for character in compact if character.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        return "+91" + digits[-10:]
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    return None
