import re
import sqlite3
from typing import List

import app


def connect() -> sqlite3.Connection:
    return sqlite3.connect(app.DB_PATH)


def add_category(name: str = 'Books') -> int:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute('INSERT INTO categories (name) VALUES (?)', (name,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_product(name: str = 'Pen', price: float = 1000.0, stock: int = 10) -> int:
    category_id = add_category()
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute('''INSERT INTO products (name, price, description, image, stock, categoryId)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (name, price, 'Test product', 'product-default.png', stock, category_id))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_to_kart(userId: int, productId: int) -> None:
    conn = connect()
    try:
        conn.execute('INSERT INTO kart (userId, productId) VALUES (?, ?)', (userId, productId))
        conn.commit()
    finally:
        conn.close()


def order_ids(userId: int) -> List[int]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT orderId FROM allorders WHERE userId = ? ORDER BY orderId', (userId,))
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def notification_rows(userId: int, kind: str = '') -> List[tuple]:
    query = ('SELECT notificationId, userId, kind, message, created_at, is_read '
             'FROM notifications WHERE userId = ?')
    args = [userId]
    if kind:
        query += ' AND kind = ?'
        args.append(kind)
    query += ' ORDER BY notificationId'
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(query, tuple(args))
        return cur.fetchall()
    finally:
        conn.close()


def count_notifications(userId: int, kind: str = '') -> int:
    return len(notification_rows(userId, kind))


def unread_rows(userId: int) -> int:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM notifications WHERE userId = ? AND is_read = 0', (userId,))
        return cur.fetchone()[0]
    finally:
        conn.close()


def kind_counts() -> dict:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT kind, COUNT(*) FROM notifications GROUP BY kind')
        return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def rendered_notification_ids(body: str) -> List[int]:
    return [int(match) for match in re.findall(r'data-notification-id="(\d+)"', body)]


def test_bell_shows_no_badge_when_nothing_unread(client, make_user, login) -> None:
    email, password, _ = make_user()
    login(client, email, password)

    response = client.get('/')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="notification-bell"' in body
    assert 'notification-badge' not in body


def test_bell_badge_counts_unread(client, make_user, login) -> None:
    email, password, userId = make_user()
    login(client, email, password)
    app.create_notification(userId, app.NOTIFICATION_ORDER_PLACED, 'First message', '2025-01-01 10:00:00')
    app.create_notification(userId, app.NOTIFICATION_NEW_ORDER, 'Second message', '2025-01-01 10:01:00')

    body = client.get('/').get_data(as_text=True)
    assert 'id="notification-bell"' in body
    assert 'id="notification-badge">2</span>' in body


def test_checkout_creates_one_shopper_and_one_admin_notification(client, make_user, login) -> None:
    shopper_email, password, shopper_id = make_user(firstName='Rohan')
    _, _, admin_id = make_user(email=app.ADMIN_EMAIL, password='adminpass', firstName='Site Admin')
    login(client, shopper_email, password)

    pen_id = add_product('Pen', 1000.0)
    book_id = add_product('Book', 499.0)
    add_to_kart(shopper_id, pen_id)
    add_to_kart(shopper_id, book_id)

    response = client.get('/saveorder')
    assert response.status_code == 200
    assert 'Order Placed Successfully' in response.get_data(as_text=True)

    created_order_ids = order_ids(shopper_id)
    assert len(created_order_ids) == 2

    shopper_rows = notification_rows(shopper_id)
    assert len(shopper_rows) == 1
    assert shopper_rows[0][2] == app.NOTIFICATION_ORDER_PLACED
    assert shopper_rows[0][5] == 0
    expected_message = ('Your order(s) ' + ', '.join('#' + str(order_id) for order_id in created_order_ids)
                        + ' placed successfully. Total paid: Rs 1499.00')
    assert shopper_rows[0][3] == expected_message

    admin_rows = notification_rows(admin_id)
    assert len(admin_rows) == 1
    assert admin_rows[0][2] == app.NOTIFICATION_NEW_ORDER
    assert admin_rows[0][5] == 0
    assert admin_rows[0][3] == 'New order from Rohan. Total: Rs 1499.00'

    assert kind_counts() == {'order_placed': 1, 'new_order': 1}


def test_two_checkouts_create_two_notifications(client, make_user, login) -> None:
    shopper_email, password, shopper_id = make_user()
    _, _, admin_id = make_user(email=app.ADMIN_EMAIL, password='adminpass')
    login(client, shopper_email, password)

    product_id = add_product('Pen', 250.0)
    for _ in range(2):
        add_to_kart(shopper_id, product_id)
        assert client.get('/saveorder').status_code == 200

    assert count_notifications(shopper_id, app.NOTIFICATION_ORDER_PLACED) == 2
    assert count_notifications(admin_id, app.NOTIFICATION_NEW_ORDER) == 2


def test_empty_cart_checkout_creates_no_notification(client, make_user, login) -> None:
    shopper_email, password, shopper_id = make_user()
    _, _, admin_id = make_user(email=app.ADMIN_EMAIL, password='adminpass')
    login(client, shopper_email, password)

    response = client.get('/saveorder')
    assert response.status_code == 200

    assert notification_rows(shopper_id) == []
    assert notification_rows(admin_id) == []
    assert app.get_unread_notification_count(shopper_id) == 0
    assert app.get_unread_notification_count(admin_id) == 0


def test_notification_text_survives_product_edit_and_delete(client, make_user, login) -> None:
    shopper_email, password, shopper_id = make_user()
    login(client, shopper_email, password)
    product_id = add_product('Pen', 300.0)
    add_to_kart(shopper_id, product_id)

    assert client.get('/saveorder').status_code == 200
    rows = notification_rows(shopper_id)
    assert len(rows) == 1
    message_before = rows[0][3]
    assert 'Pen' not in message_before  # the snapshot names the order, not the product

    conn = connect()
    try:
        conn.execute("UPDATE products SET name = 'Renamed pen' WHERE productId = ?", (product_id,))
        conn.commit()
    finally:
        conn.close()
    assert notification_rows(shopper_id)[0][3] == message_before

    conn = connect()
    try:
        conn.execute('DELETE FROM products WHERE productId = ?', (product_id,))
        conn.commit()
    finally:
        conn.close()
    assert notification_rows(shopper_id)[0][3] == message_before


def test_panel_lists_latest_twenty_newest_first(client, make_user, login) -> None:
    email, password, userId = make_user()
    login(client, email, password)
    for index in range(25):
        app.create_notification(userId, app.NOTIFICATION_ORDER_PLACED,
                                'Message ' + str(index), '2025-01-01 10:00:%02d' % index)

    response = client.get('/notifications/panel')
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    ids = rendered_notification_ids(body)
    assert len(ids) == 20
    assert ids == sorted(ids, reverse=True)

    first_item = re.search(r'data-notification-id="\d+">\s*'
                           r'<span class="notification-message">([^<]+)</span>', body)
    assert first_item is not None
    assert first_item.group(1) == 'Message 24'


def test_panel_empty_state(client, make_user, login) -> None:
    email, password, _ = make_user()
    login(client, email, password)

    response = client.get('/notifications/panel')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'You have no notifications yet.' in body
    assert rendered_notification_ids(body) == []


def test_mark_read_updates_count_and_is_idempotent(client, make_user, login) -> None:
    email, password, userId = make_user()
    login(client, email, password)
    first = app.create_notification(userId, app.NOTIFICATION_ORDER_PLACED, 'One', '2025-01-01 10:00:00')
    second = app.create_notification(userId, app.NOTIFICATION_NEW_ORDER, 'Two', '2025-01-01 10:01:00')
    assert app.get_unread_notification_count(userId) == 2

    response = client.post('/notifications/mark-read', data={'ids': '%d,%d' % (first, second)})
    assert response.status_code == 200
    assert response.get_json() == {'unread_count': 0}
    assert unread_rows(userId) == 0

    # Sending the same ids again must not push the count below zero
    again = client.post('/notifications/mark-read', data={'ids': '%d,%d' % (first, second)})
    assert again.status_code == 200
    assert again.get_json() == {'unread_count': 0}

    # Non numeric tokens are ignored rather than raising
    junk = client.post('/notifications/mark-read', data={'ids': 'abc,-1,  '})
    assert junk.status_code == 200
    assert junk.get_json() == {'unread_count': 0}


def test_notifications_are_per_user(client, make_user, login) -> None:
    a_email, a_password, a_id = make_user(email='a@example.com', password='apass', firstName='Aarti')
    b_email, b_password, b_id = make_user(email='b@example.com', password='bpass', firstName='Bharat')

    login(client, a_email, a_password)
    product_id = add_product('Pen', 500.0)
    add_to_kart(a_id, product_id)
    assert client.get('/saveorder').status_code == 200

    a_rows = notification_rows(a_id)
    assert len(a_rows) == 1
    a_notification_id = a_rows[0][0]
    a_message = a_rows[0][3]

    # A separate browser session for user B sees nothing of A's notifications
    other_client = app.app.test_client()
    login(other_client, b_email, b_password)
    panel = other_client.get('/notifications/panel')
    assert panel.status_code == 200
    other_body = panel.get_data(as_text=True)
    assert a_message not in other_body
    assert rendered_notification_ids(other_body) == []
    assert 'You have no notifications yet.' in other_body

    # B marking A's id read leaves A's row untouched
    marked = other_client.post('/notifications/mark-read', data={'ids': str(a_notification_id)})
    assert marked.status_code == 200
    assert marked.get_json() == {'unread_count': 0}
    assert unread_rows(a_id) == 1
    assert unread_rows(b_id) == 0


def test_read_state_survives_relogin(client, make_user, login) -> None:
    email, password, userId = make_user()
    login(client, email, password)
    first = app.create_notification(userId, app.NOTIFICATION_ORDER_PLACED, 'First message', '2025-01-01 10:00:00')
    second = app.create_notification(userId, app.NOTIFICATION_NEW_ORDER, 'Second message', '2025-01-01 10:01:00')

    body = client.get('/notifications/panel').get_data(as_text=True)
    assert 'notification-item unread' in body

    marked = client.post('/notifications/mark-read', data={'ids': '%d,%d' % (first, second)})
    assert marked.get_json() == {'unread_count': 0}

    assert client.get('/logout').status_code == 302
    login(client, email, password)

    assert app.get_unread_notification_count(userId) == 0
    body = client.get('/notifications/panel').get_data(as_text=True)
    assert 'notification-item unread' not in body
    assert 'First message' in body
    assert 'Second message' in body

    home = client.get('/').get_data(as_text=True)
    assert 'id="notification-bell"' in home
    assert 'notification-badge' not in home


def test_panel_requires_login(client, make_user) -> None:
    _, _, userId = make_user()
    app.create_notification(userId, app.NOTIFICATION_ORDER_PLACED,
                            'Private message for the signed-in owner', '2025-01-01 10:00:00')

    response = client.get('/notifications/panel')
    assert response.status_code == 401
    assert 'Private message for the signed-in owner' not in response.get_data(as_text=True)

    marked = client.post('/notifications/mark-read', data={'ids': '1'})
    assert marked.status_code == 401
    assert unread_rows(userId) == 1


def test_existing_shop_routes_unchanged(client, make_user, login) -> None:
    email, password, _ = make_user()
    login(client, email, password)

    for path in ('/', '/cart', '/checkout', '/account/orders', '/wishlist', '/account/profile'):
        assert client.get(path).status_code == 200, path

    assert client.get('/vieworders').status_code == 403
    assert client.get('/admin').status_code == 302

    admin_email, admin_password, _ = make_user(email=app.ADMIN_EMAIL, password='adminpass')
    login(client, admin_email, admin_password)

    for path in ('/', '/cart', '/checkout', '/account/orders', '/wishlist', '/account/profile'):
        assert client.get(path).status_code == 200, path

    assert client.get('/admin').status_code == 200
    assert client.get('/vieworders').status_code == 200
