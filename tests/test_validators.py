"""Unit tests for the pure-Python rules in validators.py."""

import validators
from validators import MESSAGES


def test_text_field_trims_and_requires():
    assert validators.text_field('   ', 'First name') == ('', 'First name is required')
    assert validators.text_field('  Asha  ', 'First name') == ('Asha', None)
    assert validators.text_field('', 'Address line 2', required=False) == ('', None)

    long_value = 'a' * (validators.MAX_LENGTH + 1)
    value, error = validators.text_field(long_value, 'City')
    assert value == long_value
    assert error == MESSAGES['too_long'].format(label='City', max_length=validators.MAX_LENGTH)


def test_email_rules():
    assert validators.email_error('user@example.com') is None
    for bad_email in ('a@@b.com', 'a b@c.com', 'abc@def', '@example.com', 'user@'):
        assert validators.email_error(bad_email) == MESSAGES['email_format']


def test_email_uniqueness_is_case_insensitive(db):
    row = db.execute('SELECT userId FROM users WHERE email = ?', ('User@Example.com',)).fetchone()
    user_id = row[0]

    assert validators.email_in_use(db, 'user@example.com') is True
    assert validators.email_in_use(db, 'user@example.com', exclude_user_id=user_id) is False
    assert validators.email_in_use(db, 'someone-else@example.com') is False


def test_price_stock_phone_zipcode_password_rules():
    assert validators.price_error('12.50') is None
    assert validators.price_error('0') is None
    assert validators.price_error('12.555') == MESSAGES['price_decimals']
    assert validators.price_error('-1') == MESSAGES['price_number']
    assert validators.price_error('abc') == MESSAGES['price_number']

    assert validators.stock_error('3') is None
    assert validators.stock_error('0') is None
    assert validators.stock_error('3.5') == MESSAGES['stock_number']
    assert validators.stock_error('-2') == MESSAGES['stock_number']

    assert validators.phone_error('9876543210') is None
    assert validators.phone_error('98765 43210') is not None
    assert validators.phone_error('+919876543210') is not None
    assert validators.phone_error('987654321') is not None

    assert validators.zipcode_error('110001') is None
    assert validators.zipcode_error('11001') is not None

    assert validators.password_error('abcdefg1') is None
    assert validators.password_error('abcdefgh') == MESSAGES['password_rule']
    assert validators.password_error('12345678') == MESSAGES['password_rule']
    assert validators.password_error('abc1') == MESSAGES['password_rule']

    assert validators.category_error('1', [1, 2]) is None
    assert validators.category_error('99', [1, 2]) == MESSAGES['category_invalid']
    assert validators.category_error('', [1, 2]) == MESSAGES['category_invalid']
