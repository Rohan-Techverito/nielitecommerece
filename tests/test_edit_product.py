"""Server-side validation tests for the admin edit-product form."""

import pytest

ADMIN_EMAIL = 'admin@nielit.gov.in'
ADMIN_PASSWORD = 'admin@nielit.gov.in'
NORMAL_USER_EMAIL = 'User@Example.com'
NORMAL_USER_PASSWORD = 'password1'

PRODUCT_ID = 1

EDIT_FORM = {
    'name': 'Updated Handbook',
    'price': '12.50',
    'description': 'An updated handbook',
    'stock': '3',
    'category': '1',
}

PRODUCT_ROW = '''SELECT name, price, description, image, stock, categoryId
                 FROM products WHERE productId = ?'''


def _login_as_admin(client):
    return client.post('/login', data={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD})


def _login_as_shopper(client):
    return client.post('/login', data={'email': NORMAL_USER_EMAIL, 'password': NORMAL_USER_PASSWORD})


def _row(db):
    return db.execute(PRODUCT_ROW, (PRODUCT_ID,)).fetchone()


def _product_count(db):
    return db.execute('SELECT COUNT(*) FROM products').fetchone()[0]


def test_edit_product_form_is_prefilled(client):
    _login_as_admin(client)

    response = client.get('/admin/edit/%d' % PRODUCT_ID)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="Flask Handbook"' in body
    assert 'value="10"' in body
    assert 'class="field-error"' not in body


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
def test_edit_product_rejects_bad_input_without_saving(client, db, field, value, message):
    _login_as_admin(client)
    before = _row(db)
    data = dict(EDIT_FORM)
    data[field] = value

    response = client.post('/admin/edit/%d' % PRODUCT_ID, data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Edit Product' in body
    assert '<p class="field-error">%s</p>' % message in body
    assert _row(db) == before


def test_edit_product_failed_submission_keeps_typed_values(client, db):
    _login_as_admin(client)
    before = _row(db)
    data = dict(EDIT_FORM)
    data['name'] = 'Typed Name'
    data['stock'] = '3.5'

    response = client.post('/admin/edit/%d' % PRODUCT_ID, data=data)
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="Typed Name"' in body
    assert 'value="12.50"' in body
    assert '<p class="field-error">Stock must be a whole number of zero or greater</p>' in body
    assert 'product-default.png' in body
    assert _row(db) == before


def test_edit_product_valid_redirects_and_saves(client, db):
    _login_as_admin(client)

    response = client.post('/admin/edit/%d' % PRODUCT_ID, data=dict(EDIT_FORM))

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin')

    assert _row(db) == ('Updated Handbook', 12.5, 'An updated handbook',
                        'product-default.png', 3, 1)
    assert _product_count(db) == 1


def test_edit_product_empty_body_is_not_an_error_page(client, db):
    _login_as_admin(client)
    before = _row(db)

    response = client.post('/admin/edit/%d' % PRODUCT_ID, data={})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<p class="field-error">Product name is required</p>' in body
    assert '<p class="field-error">Price must be a number of zero or greater</p>' in body
    assert 'Traceback' not in body
    assert _row(db) == before


def test_edit_product_still_requires_admin(client, db):
    _login_as_shopper(client)
    before = _row(db)

    response = client.post('/admin/edit/%d' % PRODUCT_ID, data=dict(EDIT_FORM))

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/')
    assert _row(db) == before
