"""Framework-free input validation shared by the shop's forms.

Each helper takes the raw string that arrived in ``request.form`` and returns
the message to show beside that field, or ``None`` when the value is
acceptable. The rules live here instead of inside the Flask routes so they can
be tested without a request and reused by every form. Flask is deliberately
not imported: this module stays pure Python.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

MAX_LENGTH = 200

MESSAGES = {
    'required': '{label} is required',
    'too_long': '{label} must be at most {max_length} characters',
    'email_format': 'Enter a valid email address',
    'email_in_use': 'An account with this email already exists',
    'password_rule': 'Password must be at least 8 characters and include both a letter and a digit',
    'password_same': 'New password must be different from the current password',
    'confirm_mismatch': 'Passwords do not match',
    'old_password_wrong': 'Current password is incorrect',
    'price_number': 'Price must be a number of zero or greater',
    'price_decimals': 'Price can have at most two decimal places',
    'stock_number': 'Stock must be a whole number of zero or greater',
    'category_invalid': 'Select one of the listed categories',
    'phone_invalid': 'Phone number must be exactly 10 digits',
    'zipcode_invalid': 'Zipcode must be exactly 6 digits',
}

_PHONE_PATTERN = re.compile(r'[0-9]{10}')
_ZIPCODE_PATTERN = re.compile(r'[0-9]{6}')
_WHOLE_NUMBER_PATTERN = re.compile(r'[0-9]+')


def trim(value: str) -> str:
    """Return ``value`` without surrounding spaces, treating ``None`` as ''."""
    if value is None:
        return ''
    return str(value).strip()


def text_field(value, label, required=True):
    """Return the trimmed value together with an error message (or ``None``).

    A whitespace-only value counts as empty, and the returned value is never
    shortened: a value that is too long is reported through the error instead.
    """
    trimmed = trim(value)
    if required and not trimmed:
        return trimmed, MESSAGES['required'].format(label=label)
    if len(trimmed) > MAX_LENGTH:
        return trimmed, MESSAGES['too_long'].format(label=label, max_length=MAX_LENGTH)
    return trimmed, None


def email_error(value: str) -> Optional[str]:
    """Check that ``value`` looks like an email address."""
    email = trim(value)
    if not email:
        return MESSAGES['required'].format(label='Email')
    if len(email) > MAX_LENGTH:
        return MESSAGES['too_long'].format(label='Email', max_length=MAX_LENGTH)
    if any(char.isspace() for char in email) or email.count('@') != 1:
        return MESSAGES['email_format']
    local_part, _, domain = email.partition('@')
    if not local_part or '.' not in domain:
        return MESSAGES['email_format']
    if any(not label for label in domain.split('.')):
        return MESSAGES['email_format']
    return None


def email_in_use(conn, email: str, exclude_user_id: Optional[int] = None) -> bool:
    """Return True when another account already uses ``email``.

    The comparison ignores letter case, and ``exclude_user_id`` lets the
    profile form accept the address of the account being edited.
    """
    cur = conn.cursor()
    if exclude_user_id is None:
        cur.execute("SELECT userId FROM users WHERE LOWER(email) = LOWER(?)", (trim(email),))
    else:
        cur.execute("SELECT userId FROM users WHERE LOWER(email) = LOWER(?) AND userId != ?",
                    (trim(email), exclude_user_id))
    return cur.fetchone() is not None


def password_error(value: str) -> Optional[str]:
    """Check the password rule: 8+ characters with a letter and a digit."""
    password = trim_password(value)
    if len(password) < 8:
        return MESSAGES['password_rule']
    if not any(char.isalpha() for char in password):
        return MESSAGES['password_rule']
    if not any(char.isdigit() for char in password):
        return MESSAGES['password_rule']
    return None


def trim_password(value: str) -> str:
    """Return the password unchanged: spaces inside a password are meaningful."""
    if value is None:
        return ''
    return str(value)


def phone_error(value: str) -> Optional[str]:
    """Check that the phone number is exactly ten digits."""
    phone = trim(value)
    if not phone:
        return MESSAGES['required'].format(label='Phone number')
    if not _PHONE_PATTERN.fullmatch(phone):
        return MESSAGES['phone_invalid']
    return None


def zipcode_error(value: str) -> Optional[str]:
    """Check that the zipcode is exactly six digits."""
    zipcode = trim(value)
    if not zipcode:
        return MESSAGES['required'].format(label='Zipcode')
    if not _ZIPCODE_PATTERN.fullmatch(zipcode):
        return MESSAGES['zipcode_invalid']
    return None


def price_error(value: str) -> Optional[str]:
    """Check that the price is a number of zero or greater with <= 2 decimals."""
    raw = trim(value)
    if not raw:
        return MESSAGES['price_number']
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return MESSAGES['price_number']
    if not amount.is_finite() or amount < 0:
        return MESSAGES['price_number']
    if amount.as_tuple().exponent < -2:
        return MESSAGES['price_decimals']
    return None


def stock_error(value: str) -> Optional[str]:
    """Check that the stock is a whole number of zero or greater."""
    raw = trim(value)
    if not raw or not _WHOLE_NUMBER_PATTERN.fullmatch(raw):
        return MESSAGES['stock_number']
    return None


def category_error(value: str, valid_ids) -> Optional[str]:
    """Check that the submitted category is one the shop already has."""
    valid = {int(valid_id) for valid_id in valid_ids}
    try:
        category_id = int(trim(value))
    except (TypeError, ValueError):
        return MESSAGES['category_invalid']
    if category_id not in valid:
        return MESSAGES['category_invalid']
    return None
