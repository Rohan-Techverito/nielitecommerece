"""Server-side validation tests for the registration form."""

import pytest

REGISTER_FORM = {
    'email': 'new.user@example.com',
    'password': 'secret123',
    'cpassword': 'secret123',
    'firstName': 'Asha',
    'lastName': 'Verma',
    'address1': '1 MG Road',
    'address2': 'Near the park',
    'zipcode': '110001',
    'city': 'New Delhi',
    'state': 'Delhi',
    'country': 'India',
    'phone': '9876543210',
}


def _user_count(db):
    return db.execute('SELECT COUNT(*) FROM users').fetchone()[0]


@pytest.mark.parametrize('field,value,message', [
    ('firstName', '', 'First name is required'),
    ('firstName', '   ', 'First name is required'),
    ('lastName', '', 'Last name is required'),
    ('lastName', '   ', 'Last name is required'),
    ('city', '', 'City is required'),
    ('state', '   ', 'State is required'),
    ('country', '', 'Country is required'),
    ('city', 'C' * 201, 'City must be at most 200 characters'),
    ('email', 'admin@nielit.gov.in', 'An account with this email already exists'),
    ('email', 'ADMIN@NIELIT.GOV.IN', 'An account with this email already exists'),
    ('email', 'a@@b.com', 'Enter a valid email address'),
    ('email', 'a b@c.com', 'Enter a valid email address'),
    ('email', 'abc@def', 'Enter a valid email address'),
    ('password', 'abcdefgh',
     'Password must be at least 8 characters and include both a letter and a digit'),
    ('password', '12345678',
     'Password must be at least 8 characters and include both a letter and a digit'),
    ('password', 'abc1',
     'Password must be at least 8 characters and include both a letter and a digit'),
    ('cpassword', 'different12', 'Passwords do not match'),
    ('phone', '98765 43210', 'Phone number must be exactly 10 digits'),
    ('phone', '+919876543210', 'Phone number must be exactly 10 digits'),
    ('phone', '987654321', 'Phone number must be exactly 10 digits'),
    ('zipcode', '11001', 'Zipcode must be exactly 6 digits'),
])
def test_register_rejects_bad_input_without_saving(client, db, field, value, message):
    before = _user_count(db)
    data = dict(REGISTER_FORM)
    data[field] = value

    response = client.post('/register', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">%s</p>' % message in body
    assert _user_count(db) == before


def test_register_failed_submission_keeps_typed_values(client, db):
    before = _user_count(db)
    data = dict(REGISTER_FORM)
    data['lastName'] = 'Subramaniam'
    data['phone'] = '98765 43210'

    response = client.post('/register', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="Subramaniam"' in body
    assert '<p class="field-error">Phone number must be exactly 10 digits</p>' in body
    assert _user_count(db) == before


def test_register_accepts_valid_input(client, db):
    data = dict(REGISTER_FORM)
    data['firstName'] = '  Asha  '
    data['lastName'] = '  Verma  '
    data['email'] = '  new.user@example.com  '

    response = client.post('/register', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Registered Successfully' in body

    row = db.execute(
        'SELECT email, firstName, lastName, zipcode, phone FROM users WHERE email = ?',
        ('new.user@example.com',)).fetchone()
    assert row == ('new.user@example.com', 'Asha', 'Verma', '110001', '9876543210')
    assert _user_count(db) == 3


def test_register_empty_body_is_not_an_error_page(client):
    response = client.post('/register', data={})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">Email is required</p>' in body
    assert '<p class="field-error">First name is required</p>' in body
    assert 'Traceback' not in body
    assert 'werkzeug' not in body.lower()
