"""Shared, framework-free validation helpers for shop forms.

Every validator returns a ``(cleaned_value, error_message)`` pair.  When the
input is valid the error is ``None``; when it is invalid the cleaned value is
``None`` and the error contains a message that is safe to show to a shopper.

Nothing in this module touches Flask or the database so it can be imported and
unit tested without an application context.
"""

import re
from decimal import Decimal, InvalidOperation

MAX_LENGTH = 200

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PRICE_RE = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_STOCK_RE = re.compile(r"-?[0-9]+")
_LETTER_RE = re.compile(r"[A-Za-z]")
_DIGIT_RE = re.compile(r"[0-9]")


def _as_text(value):
    """Return *value* as a string without raising on ``None``."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _too_long(label, max_length=MAX_LENGTH):
    return "%s must be %s characters or fewer." % (label, max_length)


def validate_required_text(value, label, max_length=MAX_LENGTH):
    """Validate a required text field, trimming surrounding whitespace."""
    cleaned = _as_text(value).strip()
    if not cleaned:
        return None, "%s is required." % label
    if len(cleaned) > max_length:
        return None, _too_long(label, max_length)
    return cleaned, None


def validate_name(value, label, max_length=MAX_LENGTH):
    """Names are required, trimmed and length limited."""
    return validate_required_text(value, label, max_length)


def validate_optional_text(value, label, max_length=MAX_LENGTH):
    """Validate an optional text field without changing what was typed."""
    raw = _as_text(value)
    if len(raw) > max_length:
        return None, _too_long(label, max_length)
    return raw, None


def validate_email(value, label="Email", max_length=MAX_LENGTH):
    """Validate and trim an email address.

    The address must contain exactly one ``@``, have no whitespace and have a
    dot in the domain part.
    """
    cleaned, error = validate_required_text(value, label, max_length)
    if error:
        return None, error
    if not _EMAIL_RE.fullmatch(cleaned):
        return None, (
            "Enter a valid email address with one @, no spaces, "
            "and a dot in the domain."
        )
    return cleaned, None


def validate_password(value, label="Password", max_length=MAX_LENGTH):
    """Passwords are not trimmed and must be 8+ chars with a letter and digit."""
    password = _as_text(value)
    if not password:
        return None, "%s is required." % label
    if len(password) > max_length:
        return None, _too_long(label, max_length)
    if len(password) < 8:
        return None, "%s must be at least 8 characters long." % label
    if not _LETTER_RE.search(password):
        return None, "%s must contain at least one letter." % label
    if not _DIGIT_RE.search(password):
        return None, "%s must contain at least one number." % label
    return password, None


def validate_confirmation(value, original, label="Confirmation", required=False):
    """Check a confirmation field against another password value."""
    confirmation = _as_text(value)
    if not confirmation:
        if required:
            return None, "%s is required." % label
        return None, None
    if confirmation != _as_text(original):
        return None, "Passwords do not match."
    return confirmation, None


def validate_phone(value, label="Phone number"):
    """Phone numbers must be exactly ten digits."""
    cleaned = _as_text(value).strip()
    if not cleaned:
        return None, "%s is required." % label
    if not re.fullmatch(r"[0-9]{10}", cleaned):
        return None, "%s must be exactly 10 digits." % label
    return cleaned, None


def validate_zipcode(value, label="Zipcode"):
    """Zipcodes must be exactly six digits."""
    cleaned = _as_text(value).strip()
    if not cleaned:
        return None, "%s is required." % label
    if not re.fullmatch(r"[0-9]{6}", cleaned):
        return None, "%s must be exactly 6 digits." % label
    return cleaned, None


def validate_price(value, label="Price", max_length=MAX_LENGTH):
    """Price must be a number, zero or greater, with at most two decimals."""
    cleaned = _as_text(value).strip()
    if not cleaned:
        return None, "%s is required." % label
    if len(cleaned) > max_length:
        return None, _too_long(label, max_length)

    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None, "%s must be a number." % label

    if not amount.is_finite():
        return None, "%s must be a number." % label
    if amount < 0:
        return None, "%s cannot be negative." % label
    if not _PRICE_RE.fullmatch(cleaned):
        return None, "%s must be a number." % label

    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return None, "%s can have at most two decimal places." % label

    return float(amount), None


def validate_stock(value, label="Stock", max_length=MAX_LENGTH):
    """Stock must be a whole number, zero or greater."""
    cleaned = _as_text(value).strip()
    if not cleaned:
        return None, "%s is required." % label
    if len(cleaned) > max_length:
        return None, _too_long(label, max_length)

    if _STOCK_RE.fullmatch(cleaned):
        amount = int(cleaned)
        if amount < 0:
            return None, "%s cannot be negative." % label
        return amount, None

    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None, "%s must be a whole number." % label
    if amount.is_finite() and amount < 0:
        return None, "%s cannot be negative." % label
    return None, "%s must be a whole number." % label


def validate_category(value, categories, label="Category"):
    """Category must be present in the set of categories the shop already has.

    *categories* may be an iterable of ``(id, name)`` pairs or a plain
    iterable of ids.
    """
    cleaned = _as_text(value).strip()
    if not cleaned:
        return None, "%s is required." % label

    allowed = set()
    for category in categories or ():
        if isinstance(category, (tuple, list)) and category:
            allowed.add(str(category[0]))
        else:
            allowed.add(str(category))

    if cleaned not in allowed:
        return None, "Select a valid %s." % label.lower()
    try:
        return int(cleaned), None
    except (TypeError, ValueError):
        return None, "Select a valid %s." % label.lower()
