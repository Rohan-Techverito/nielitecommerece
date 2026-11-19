"""Server-side validation tests for the admin add-product form."""

import pytest

ADMIN_EMAIL = 'admin@nielit.gov.in'
ADMIN_PASSWORD = 'admin@nielit.gov.in'
NORMAL_USER_EMAIL = 'User@Example.com'
NORMAL_USER_PASSWORD = 'password1'

ADD_FORM = {
    'name': 'New Book',
    'price': '12.50',
    'description': 'A new arrival',
    'stock': '3',
    'category': '1',
}


def _login_as_admin(client):
    return client.post('/login', data={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD})


def _login_as_shopper(client):
    return client.post('/login', data={'email': NORMAL_USER_EMAIL, 'password': NORMAL_USER_PASSWORD})


def _product_count(db):
    return db.execute('SELECT COUNT(*) FROM products').fetchone()[0]


@pytest.mark.parametrize('field,value,message', [
    ('price', '12.555', 'Price can have at most two decimal places'),
    ('price', '-1', 'Price must be a number of zero or greater'),
    ('price', 'abc', 'Price must be a number of zero or greater'),
    ('stock', '3.5', 'Stock must be a whole number of zero or greater'),
    ('stock', '-2', 'Stock must be a whole number of zero or greater'),
    ('name', '', 'Product name is required'),
    ('name', '   ', 'Product name is required'),
    ('name', 'N' * 201, 'Product name must be at most 200 characters'),
    ('category', '99', 'Select one of the listed categories'),
    ('category', '', 'Select one of the listed categories'),
])
def test_add_product_rejects_bad_input_without_saving(client, db, field, value, message):
    _login_as_admin(client)
    before = _product_count(db)
    data = dict(ADD_FORM)
    data[field] = value

    response = client.post('/admin/add', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">%s</p>' % message in body
    assert _product_count(db) == before


def test_add_product_failed_submission_keeps_typed_values(client, db):
    _login_as_admin(client)
    before = _product_count(db)
    data = dict(ADD_FORM)
    data['name'] = 'Typed Name'
    data['stock'] = '3.5'

    response = client.post('/admin/add', data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="Typed Name"' in body
    assert 'value="12.50"' in body
    assert '<p class="field-error">Stock must be a whole number of zero or greater</p>' in body
    assert _product_count(db) == before


def test_add_product_valid_redirects_and_saves(client, db):
    _login_as_admin(client)

    response = client.post('/admin/add', data=dict(ADD_FORM))

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin')

    row = db.execute(
        'SELECT name, price, stock, categoryId, description FROM products WHERE name = ?',
        ('New Book',)).fetchone()
    assert row == ('New Book', 12.5, 3, 1, 'A new arrival')
    assert _product_count(db) == 2


def test_add_product_empty_body_is_not_an_error_page(client, db):
    _login_as_admin(client)
    before = _product_count(db)

    response = client.post('/admin/add', data={})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">Product name is required</p>' in body
    assert 'Traceback' not in body
    assert _product_count(db) == before


def test_add_product_still_requires_admin(client, db):
    _login_as_shopper(client)
    before = _product_count(db)

    response = client.post('/admin/add', data=dict(ADD_FORM))

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/')
    assert _product_count(db) == before
