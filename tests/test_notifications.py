"""Regression tests for checkout notifications and per-user isolation (AF-875)."""

import os
import sqlite3
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Point the app at a throwaway database before importing it so the import-time
# notifications bootstrap never touches the real database.db.
BOOTSTRAP_DIR = tempfile.mkdtemp(prefix='nielit-notifications-bootstrap-')
os.environ['NIELIT_DATABASE'] = os.path.join(BOOTSTRAP_DIR, 'bootstrap.db')

import app as app_module  # noqa: E402

ADMIN_EMAIL = app_module.ADMIN_EMAILS[0]

SCHEMA = """
CREATE TABLE users (
    userId INTEGER PRIMARY KEY AUTOINCREMENT,
    password TEXT,
    email TEXT,
    firstName TEXT,
    lastName TEXT,
    address1 TEXT,
    address2 TEXT,
    zipcode TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    phone TEXT
);

CREATE TABLE categories (
    categoryId INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT
);

CREATE TABLE products (
    productId INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price REAL,
    description TEXT,
    image TEXT,
    stock INTEGER,
    categoryId INTEGER
);

CREATE TABLE kart (
    kartId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER
);

CREATE TABLE allorders (
    orderId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER,
    quantity INTEGER,
    total_price REAL,
    order_date TEXT
);

CREATE TABLE wishlist (
    wishlistId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER
);

CREATE TABLE notifications (
    notificationId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER NOT NULL,
    message TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    isRead INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_notifications_user_read
    ON notifications (userId, isRead, createdAt);
"""


def query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def execute(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_user(db_path, email, first_name='Shopper'):
    return execute(
        db_path,
        "INSERT INTO users (password, email, firstName, lastName, address1, address2, "
        "zipcode, city, state, country, phone) VALUES (?, ?, ?, ?, '', '', '', '', '', '', '')",
        ('secret', email, first_name, 'Tester')
    )


def add_product(db_path, name='Notebook', price=10.0):
    return execute(
        db_path,
        "INSERT INTO products (name, price, description, image, stock, categoryId) "
        "VALUES (?, ?, 'desc', 'product.jpg', 10, 1)",
        (name, price)
    )


def add_to_cart(db_path, user_id, product_id):
    execute(db_path, "INSERT INTO kart (userId, productId) VALUES (?, ?)", (user_id, product_id))


def login_as(client, email):
    with client.session_transaction() as session_data:
        session_data['email'] = email


def shopper_notifications(db_path, user_id):
    return query(
        db_path,
        "SELECT notificationId, message, createdAt, isRead FROM notifications "
        "WHERE userId = ? ORDER BY notificationId",
        (user_id,)
    )


def order_ids(db_path, user_id):
    return [row[0] for row in query(
        db_path,
        "SELECT orderId FROM allorders WHERE userId = ? ORDER BY orderId",
        (user_id,)
    )]


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / 'test.db')
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture()
def client(db_path):
    app_module.app.config['DATABASE'] = db_path
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as test_client:
        yield test_client
    app_module.app.config['DATABASE'] = os.environ['NIELIT_DATABASE']


def test_single_product_checkout_notifies_shopper_and_admin(client, db_path):
    shopper_id = add_user(db_path, 'shopper@example.com', 'Asha')
    admin_id = add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Notebook', 99.5)
    add_to_cart(db_path, shopper_id, product_id)
    login_as(client, 'shopper@example.com')

    response = client.get('/saveorder')

    assert response.status_code == 200
    created_orders = order_ids(db_path, shopper_id)
    assert len(created_orders) == 1

    shopper_rows = shopper_notifications(db_path, shopper_id)
    assert len(shopper_rows) == 1
    message = shopper_rows[0][1]
    assert '#{}'.format(created_orders[0]) in message
    assert 'Rs 99.50' in message
    assert shopper_rows[0][3] == 0  # unread

    admin_rows = shopper_notifications(db_path, admin_id)
    assert len(admin_rows) == 1
    assert 'Asha' in admin_rows[0][1]
    assert 'Rs 99.50' in admin_rows[0][1]
    assert admin_rows[0][3] == 0

    # Cart is still cleared and the confirmation page renders.
    assert query(db_path, "SELECT COUNT(*) FROM kart WHERE userId = ?", (shopper_id,))[0][0] == 0
    assert b'Order Placed Successfully' in response.data


def test_multi_product_checkout_creates_one_notification_naming_all_orders(client, db_path):
    shopper_id = add_user(db_path, 'multi@example.com', 'Ravi')
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    first_product = add_product(db_path, 'Pen', 50.25)
    second_product = add_product(db_path, 'Paper', 20.75)
    add_to_cart(db_path, shopper_id, first_product)
    add_to_cart(db_path, shopper_id, second_product)
    login_as(client, 'multi@example.com')

    client.get('/saveorder')

    created_orders = order_ids(db_path, shopper_id)
    assert len(created_orders) == 2

    shopper_rows = shopper_notifications(db_path, shopper_id)
    assert len(shopper_rows) == 1
    message = shopper_rows[0][1]
    for order_id in created_orders:
        assert '#{}'.format(order_id) in message
    assert 'Rs 71.00' in message


def test_two_checkouts_create_two_separate_notifications(client, db_path):
    shopper_id = add_user(db_path, 'repeat@example.com', 'Meera')
    admin_id = add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Marker', 15.0)
    login_as(client, 'repeat@example.com')

    add_to_cart(db_path, shopper_id, product_id)
    client.get('/saveorder')
    add_to_cart(db_path, shopper_id, product_id)
    client.get('/saveorder')

    assert len(shopper_notifications(db_path, shopper_id)) == 2
    assert len(shopper_notifications(db_path, admin_id)) == 2


def test_empty_cart_creates_no_notifications(client, db_path):
    shopper_id = add_user(db_path, 'empty@example.com', 'Kiran')
    admin_id = add_user(db_path, ADMIN_EMAIL, 'Admin')
    login_as(client, 'empty@example.com')

    response = client.get('/saveorder')

    assert response.status_code == 200
    assert shopper_notifications(db_path, shopper_id) == []
    assert shopper_notifications(db_path, admin_id) == []
    assert order_ids(db_path, shopper_id) == []


def test_every_admin_gets_a_new_order_notification(client, db_path, monkeypatch):
    monkeypatch.setattr(
        app_module,
        'ADMIN_EMAILS',
        ('admin@nielit.gov.in', 'operations@nielit.gov.in')
    )
    shopper_id = add_user(db_path, 'buyer@example.com', 'Neha')
    first_admin_id = add_user(db_path, 'admin@nielit.gov.in', 'Admin One')
    second_admin_id = add_user(db_path, 'operations@nielit.gov.in', 'Admin Two')
    product_id = add_product(db_path, 'Lamp', 40.0)
    add_to_cart(db_path, shopper_id, product_id)
    login_as(client, 'buyer@example.com')

    client.get('/saveorder')

    for admin_id in (first_admin_id, second_admin_id):
        admin_rows = shopper_notifications(db_path, admin_id)
        assert len(admin_rows) == 1
        assert 'Neha' in admin_rows[0][1]
        assert 'Rs 40.00' in admin_rows[0][1]


def test_anonymous_notification_endpoints_return_401(client, db_path):
    add_user(db_path, 'someone@example.com', 'Someone')
    execute(
        db_path,
        "INSERT INTO notifications (userId, message, createdAt, isRead) VALUES (1, 'secret', '2026-01-01 00:00:00', 0)"
    )

    list_response = client.get('/notifications')
    mark_response = client.post('/notifications/mark-read', json={'ids': [1]})

    assert list_response.status_code == 401
    assert mark_response.status_code == 401
    assert b'secret' not in list_response.data
    # Nothing was marked read.
    assert query(db_path, "SELECT isRead FROM notifications WHERE notificationId = 1")[0][0] == 0


def test_each_user_only_sees_their_own_notifications(client, db_path):
    first_shopper = add_user(db_path, 'first@example.com', 'First')
    second_shopper = add_user(db_path, 'second@example.com', 'Second')
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Brush', 12.0)

    login_as(client, 'first@example.com')
    add_to_cart(db_path, first_shopper, product_id)
    client.get('/saveorder')

    login_as(client, 'second@example.com')
    add_to_cart(db_path, second_shopper, product_id)
    client.get('/saveorder')

    login_as(client, 'first@example.com')
    payload = client.get('/notifications').get_json()

    assert payload['unreadCount'] == 1
    returned_ids = {row['id'] for row in payload['notifications']}
    first_ids = {row[0] for row in shopper_notifications(db_path, first_shopper)}
    second_ids = {row[0] for row in shopper_notifications(db_path, second_shopper)}
    assert returned_ids == first_ids
    assert returned_ids.isdisjoint(second_ids)


def test_mark_read_cannot_touch_another_users_rows(client, db_path):
    first_shopper = add_user(db_path, 'alpha@example.com', 'Alpha')
    second_shopper = add_user(db_path, 'beta@example.com', 'Beta')
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Clip', 5.0)

    login_as(client, 'alpha@example.com')
    add_to_cart(db_path, first_shopper, product_id)
    client.get('/saveorder')

    login_as(client, 'beta@example.com')
    add_to_cart(db_path, second_shopper, product_id)
    client.get('/saveorder')

    beta_ids = [row[0] for row in shopper_notifications(db_path, second_shopper)]

    login_as(client, 'alpha@example.com')
    response = client.post('/notifications/mark-read', json={'ids': beta_ids})

    assert response.status_code == 200
    assert response.get_json()['unreadCount'] == 1  # alpha's own item is still unread
    assert query(
        db_path,
        "SELECT COUNT(*) FROM notifications WHERE userId = ? AND isRead = 1",
        (second_shopper,)
    )[0][0] == 0


def test_mark_read_is_idempotent(client, db_path):
    shopper_id = add_user(db_path, 'idem@example.com', 'Idem')
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Eraser', 3.5)
    add_to_cart(db_path, shopper_id, product_id)
    login_as(client, 'idem@example.com')
    client.get('/saveorder')

    first = client.post('/notifications/mark-read').get_json()
    second = client.post('/notifications/mark-read').get_json()

    assert first['unreadCount'] == 0
    assert second['unreadCount'] == 0
    assert query(
        db_path,
        "SELECT COUNT(*) FROM notifications WHERE userId = ? AND isRead = 0",
        (shopper_id,)
    )[0][0] == 0


def test_mark_read_with_empty_id_list_changes_nothing(client, db_path):
    shopper_id = add_user(db_path, 'emptyids@example.com', 'EmptyIds')
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Folder', 6.0)
    add_to_cart(db_path, shopper_id, product_id)
    login_as(client, 'emptyids@example.com')
    client.get('/saveorder')

    response = client.post('/notifications/mark-read', json={'ids': []})

    assert response.status_code == 200
    assert response.get_json()['unreadCount'] == 1
    assert query(
        db_path,
        "SELECT COUNT(*) FROM notifications WHERE userId = ? AND isRead = 0",
        (shopper_id,)
    )[0][0] == 1


def test_notifications_return_latest_twenty_newest_first(client, db_path):
    user_id = add_user(db_path, 'many@example.com', 'Many')
    for index in range(1, 26):
        execute(
            db_path,
            "INSERT INTO notifications (userId, message, createdAt, isRead) VALUES (?, ?, ?, 0)",
            (user_id, 'Message {}'.format(index), '2026-01-01 00:{:02d}:00'.format(index))
        )
    login_as(client, 'many@example.com')

    payload = client.get('/notifications').get_json()

    assert len(payload['notifications']) == 20
    assert [row['id'] for row in payload['notifications']] == list(range(25, 5, -1))
    assert payload['unreadCount'] == 25
    assert set(payload['notifications'][0]) == {'id', 'message', 'createdAt', 'isRead'}


def test_notification_text_survives_product_deletion(client, db_path):
    shopper_id = add_user(db_path, 'historic@example.com', 'Historic')
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Vintage Item', 25.0)
    add_to_cart(db_path, shopper_id, product_id)
    login_as(client, 'historic@example.com')
    client.get('/saveorder')

    original_message = shopper_notifications(db_path, shopper_id)[0][1]
    execute(db_path, "DELETE FROM products WHERE productId = ?", (product_id,))

    payload = client.get('/notifications').get_json()

    assert payload['notifications'][0]['message'] == original_message
    assert 'Vintage Item' not in original_message


def test_bell_is_rendered_only_for_signed_in_users(client, db_path):
    shopper_id = add_user(db_path, 'bell@example.com', 'Bell')
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    product_id = add_product(db_path, 'Cup', 8.0)

    signed_out_page = client.get('/')
    assert b'notification-bell' not in signed_out_page.data

    login_as(client, 'bell@example.com')
    zero_unread_page = client.get('/')
    assert b'notification-bell' in zero_unread_page.data
    assert b'notification-badge-hidden' in zero_unread_page.data

    add_to_cart(db_path, shopper_id, product_id)
    client.get('/saveorder')
    unread_page = client.get('/')
    assert b'notification-bell' in unread_page.data


def test_admin_flag_matches_the_previous_behaviour(client, db_path):
    add_user(db_path, ADMIN_EMAIL, 'Admin')
    add_user(db_path, 'plain@example.com', 'Plain')

    login_as(client, 'plain@example.com')
    assert client.get('/admin').status_code == 302

    login_as(client, ADMIN_EMAIL)
    assert client.get('/admin').status_code == 200
