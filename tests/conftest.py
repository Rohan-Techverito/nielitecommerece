import hashlib
import os
import sqlite3
import sys
import tempfile
from typing import Callable, Iterator, Tuple

import pytest
from flask.testing import FlaskClient

# Make the repository root importable no matter where pytest is started from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Point the application at a throwaway database *before* importing app, so app.DB_PATH
# resolves to the temp file and the shipped database.db is never touched by the tests
TEST_DB_PATH = os.path.join(tempfile.mkdtemp(prefix='nielit-tests-'), 'test-database.db')
os.environ['NIELIT_DB_PATH'] = TEST_DB_PATH

import app as app_module  # noqa: E402

assert app_module.DB_PATH == TEST_DB_PATH, 'app.DB_PATH must follow NIELIT_DB_PATH'

# Base schema the application assumes; database.py only creates allorders, wishlist and
# notifications, so users, categories, products and kart have to come from here
schema_sql = '''
CREATE TABLE IF NOT EXISTS users (
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
CREATE TABLE IF NOT EXISTS categories (
    categoryId INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT
);
CREATE TABLE IF NOT EXISTS products (
    productId INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price REAL,
    description TEXT,
    image TEXT,
    stock INTEGER,
    categoryId INTEGER
);
CREATE TABLE IF NOT EXISTS kart (
    userId INTEGER,
    productId INTEGER
);
CREATE TABLE IF NOT EXISTS allorders (
    orderId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER,
    quantity INTEGER,
    total_price REAL,
    order_date TEXT
);
CREATE TABLE IF NOT EXISTS wishlist (
    wishlistId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER
);
'''

TABLES_TO_CLEAR = ('notifications', 'kart', 'allorders', 'wishlist', 'products', 'categories', 'users')


def connect() -> sqlite3.Connection:
    return sqlite3.connect(app_module.DB_PATH)


def create_schema() -> None:
    conn = connect()
    try:
        conn.executescript(schema_sql)
        conn.execute(app_module.NOTIFICATIONS_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    create_schema()
    conn = connect()
    try:
        for table in TABLES_TO_CLEAR:
            conn.execute('DELETE FROM ' + table)
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture
def client() -> FlaskClient:
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


@pytest.fixture
def make_user() -> Callable[..., Tuple[str, str, int]]:
    def _make_user(email: str = 'shopper@example.com', password: str = 'secret123',
                   firstName: str = 'Rohan', lastName: str = 'Verma') -> Tuple[str, str, int]:
        conn = connect()
        try:
            cur = conn.cursor()
            cur.execute('''INSERT INTO users (password, email, firstName, lastName, address1, address2,
                                             zipcode, city, state, country, phone)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (hashlib.md5(password.encode()).hexdigest(), email, firstName, lastName,
                         '1 Test Street', '', '110001', 'New Delhi', 'Delhi', 'India', '9999999999'))
            conn.commit()
            return email, password, cur.lastrowid
        finally:
            conn.close()

    return _make_user


@pytest.fixture
def login() -> Callable[..., None]:
    def _login(client: FlaskClient, email: str, password: str) -> None:
        response = client.post('/login', data={'email': email, 'password': password})
        assert response.status_code == 302, 'a successful sign in should redirect'

    return _login
