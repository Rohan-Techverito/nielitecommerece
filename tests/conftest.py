"""Shared pytest fixtures for the shop's server-side validation tests.

The application keeps its data in ``database.db`` relative to the current
working directory, so every test runs inside its own temporary directory with
a freshly created database. The schema holds the columns the routes in
``app.py`` query, and these rows are seeded for every test:

* the shopper ``User@Example.com`` (userId 1, password ``password1``)
* the administrator ``admin@nielit.gov.in`` (userId 2)
* one category (``Books``, categoryId 1) and one product inside it
"""

import hashlib
import os
import sqlite3
import sys

import pytest

# Make app.py and validators.py importable no matter where pytest was started.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as shop  # noqa: E402


NORMAL_USER_EMAIL = 'User@Example.com'
NORMAL_USER_PASSWORD = 'password1'
ADMIN_EMAIL = 'admin@nielit.gov.in'
ADMIN_PASSWORD = 'admin@nielit.gov.in'

SCHEMA = (
    '''CREATE TABLE users (
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
    )''',
    '''CREATE TABLE products (
        productId INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        description TEXT,
        image TEXT,
        stock INTEGER,
        categoryId INTEGER
    )''',
    '''CREATE TABLE categories (
        categoryId INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT
    )''',
    '''CREATE TABLE kart (
        kartId INTEGER PRIMARY KEY AUTOINCREMENT,
        userId INTEGER,
        productId INTEGER
    )''',
    '''CREATE TABLE wishlist (
        wishlistId INTEGER PRIMARY KEY AUTOINCREMENT,
        userId INTEGER,
        productId INTEGER
    )''',
    '''CREATE TABLE allorders (
        orderId INTEGER PRIMARY KEY AUTOINCREMENT,
        userId INTEGER,
        productId INTEGER,
        quantity INTEGER,
        total_price REAL,
        order_date TEXT
    )''',
)

USER_COLUMNS = '''INSERT INTO users
    (password, email, firstName, lastName, address1, address2, zipcode, city, state, country, phone)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''


def _md5(password):
    return hashlib.md5(password.encode()).hexdigest()


def _seed_database():
    conn = sqlite3.connect('database.db')
    try:
        for statement in SCHEMA:
            conn.execute(statement)
        conn.execute(USER_COLUMNS, (_md5(NORMAL_USER_PASSWORD), NORMAL_USER_EMAIL, 'Asha', 'Verma',
                                    '1 MG Road', 'Near the park', '110001', 'New Delhi', 'Delhi',
                                    'India', '9876543210'))
        conn.execute(USER_COLUMNS, (_md5(ADMIN_PASSWORD), ADMIN_EMAIL, 'Admin', 'Nielit',
                                    '2 MG Road', '', '110001', 'New Delhi', 'Delhi',
                                    'India', '9876543211'))
        conn.execute('INSERT INTO categories (name) VALUES (?)', ('Books',))
        conn.execute('''INSERT INTO products (name, price, description, image, stock, categoryId)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                     ('Flask Handbook', 499.0, 'A short handbook', 'product-default.png', 10, 1))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A Flask test client backed by a temporary, freshly seeded database."""
    monkeypatch.chdir(tmp_path)
    _seed_database()
    return shop.app.test_client()


@pytest.fixture()
def db(client):
    """A connection to the same temporary database, for assertions."""
    conn = sqlite3.connect('database.db')
    try:
        yield conn
    finally:
        conn.close()
