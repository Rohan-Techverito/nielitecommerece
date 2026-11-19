"""Server-side validation tests for changing the account password."""

import hashlib

import pytest

NORMAL_USER_EMAIL = 'User@Example.com'
NORMAL_USER_PASSWORD = 'password1'

PASSWORD_RULE = 'Password must be at least 8 characters and include both a letter and a digit'


def _login(client):
    return client.post('/login', data={'email': NORMAL_USER_EMAIL, 'password': NORMAL_USER_PASSWORD})


def _stored_hash(db):
    return db.execute('SELECT password FROM users WHERE email = ?', (NORMAL_USER_EMAIL,)).fetchone()[0]


def _md5(value):
    return hashlib.md5(value.encode()).hexdigest()


def _change(client, oldpassword, newpassword, cpassword):
    return client.post('/account/profile/changePassword',
                       data={'oldpassword': oldpassword,
                             'newpassword': newpassword,
                             'cpassword': cpassword})


@pytest.mark.parametrize('oldpassword,newpassword,cpassword,message', [
    ('wrongpass1', 'newsecret1', 'newsecret1', 'Current password is incorrect'),
    ('password1', 'newsecret1', 'different12', 'Passwords do not match'),
    ('password1', 'password1', 'password1', 'New password must be different from the current password'),
    ('password1', 'abc1', 'abc1', PASSWORD_RULE),
    ('password1', 'abcdefgh', 'abcdefgh', PASSWORD_RULE),
    ('password1', '12345678', '12345678', PASSWORD_RULE),
])
def test_change_password_failures_are_specific_and_save_nothing(client, db, oldpassword,
                                                                newpassword, cpassword, message):
    _login(client)
    before = _stored_hash(db)

    response = _change(client, oldpassword, newpassword, cpassword)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">%s</p>' % message in body
    assert _stored_hash(db) == before


def test_change_password_messages_belong_to_their_own_field(client, db):
    _login(client)
    before = _stored_hash(db)

    wrong_current = _change(client, 'wrongpass1', 'newsecret1', 'newsecret1').get_data(as_text=True)
    mismatched_confirm = _change(client, 'password1', 'newsecret1', 'different12').get_data(as_text=True)

    assert '<p class="field-error">Current password is incorrect</p>' in wrong_current
    assert 'Passwords do not match' not in wrong_current
    assert '<p class="field-error">Passwords do not match</p>' in mismatched_confirm
    assert 'Current password is incorrect' not in mismatched_confirm
    assert _stored_hash(db) == before


def test_change_password_success_updates_hash(client, db):
    _login(client)

    response = _change(client, 'password1', 'newsecret1', 'newsecret1')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Changed successfully' in body
    assert _stored_hash(db) == _md5('newsecret1')


def test_change_password_empty_body_is_not_an_error_page(client, db):
    _login(client)
    before = _stored_hash(db)

    response = client.post('/account/profile/changePassword', data={})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">Current password is incorrect</p>' in body
    assert '<p class="field-error">%s</p>' % PASSWORD_RULE in body
    assert 'Traceback' not in body
    assert _stored_hash(db) == before
