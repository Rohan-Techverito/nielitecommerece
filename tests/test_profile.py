"""Server-side validation tests for profile editing."""

import pytest

NORMAL_USER_EMAIL = 'User@Example.com'
NORMAL_USER_PASSWORD = 'password1'

PROFILE_FORM = {
    'email': NORMAL_USER_EMAIL,
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

USER_ROWS = '''SELECT email, firstName, lastName, address1, address2, zipcode, city, state,
                      country, phone
               FROM users ORDER BY userId'''


def _login(client):
    return client.post('/login', data={'email': NORMAL_USER_EMAIL, 'password': NORMAL_USER_PASSWORD})


def _rows(db):
    return db.execute(USER_ROWS).fetchall()


def test_profile_form_is_prefilled_without_errors(client):
    _login(client)

    response = client.get('/account/profile/edit')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="Asha"' in body
    assert 'value="110001"' in body
    assert 'class="field-error"' not in body


@pytest.mark.parametrize('field,value,message', [
    ('firstName', '   ', 'First name is required'),
    ('lastName', '', 'Last name is required'),
    ('city', '', 'City is required'),
    ('state', '   ', 'State is required'),
    ('country', '', 'Country is required'),
    ('zipcode', '11001', 'Zipcode must be exactly 6 digits'),
    ('phone', '98765 43210', 'Phone number must be exactly 10 digits'),
    ('phone', '+919876543210', 'Phone number must be exactly 10 digits'),
])
def test_profile_update_rejects_bad_input_without_saving(client, db, field, value, message):
    _login(client)
    before = _rows(db)
    data = dict(PROFILE_FORM)
    data[field] = value

    response = client.post('/updateProfile', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">%s</p>' % message in body
    assert _rows(db) == before


def test_profile_failed_update_keeps_typed_values(client, db):
    _login(client)
    before = _rows(db)
    data = dict(PROFILE_FORM)
    data['lastName'] = 'Sharma'
    data['zipcode'] = '11001'

    response = client.post('/updateProfile', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="Sharma"' in body
    assert '<p class="field-error">Zipcode must be exactly 6 digits</p>' in body
    assert _rows(db) == before


def test_profile_rejects_other_accounts_email(client, db):
    _login(client)
    before = _rows(db)
    data = dict(PROFILE_FORM)
    data['email'] = 'admin@nielit.gov.in'

    response = client.post('/updateProfile', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">An account with this email already exists</p>' in body
    assert _rows(db) == before


def test_profile_accepts_own_email_in_any_case(client, db):
    _login(client)
    data = dict(PROFILE_FORM)
    data['email'] = 'USER@EXAMPLE.COM'

    response = client.post('/updateProfile', data=data)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/account/profile/edit')


def test_profile_valid_update_redirects_and_persists(client, db):
    _login(client)
    data = dict(PROFILE_FORM)
    data['lastName'] = 'Sharma'
    data['phone'] = '9123456789'
    data['zipcode'] = '560001'
    data['city'] = '  Bengaluru  '
    data['state'] = 'Karnataka'

    response = client.post('/updateProfile', data=data)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/account/profile/edit')

    row = db.execute(
        '''SELECT firstName, lastName, phone, zipcode, city, state, country
           FROM users WHERE email = ?''', (NORMAL_USER_EMAIL,)).fetchone()
    assert row == ('Asha', 'Sharma', '9123456789', '560001', 'Bengaluru', 'Karnataka', 'India')


def test_profile_empty_body_is_not_an_error_page(client):
    _login(client)

    response = client.post('/updateProfile', data={})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">Email is required</p>' in body
    assert '<p class="field-error">First name is required</p>' in body
    assert 'Traceback' not in body
