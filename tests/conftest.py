"""Shared pytest fixtures for the profile photo acceptance tests.

app.py resolves 'database.db', 'static/uploads' and the profile photo folder
relative to the process working directory, so every test runs inside its own
temporary directory instead of the repository checkout: the repository's
database.db and static/uploads are never touched by the suite.
"""

import hashlib
import io
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional, Tuple

import pytest
from flask.testing import FlaskClient
from PIL import Image
from werkzeug.test import TestResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SHOPPER_EMAIL = 'shopper@example.com'
SHOPPER_PASSWORD = 'shopper-pass'
SHOPPER_FIRST_NAME = 'Lovnish'
SHOPPER_LAST_NAME = 'Verma'
SHOPPER_INITIALS = 'LV'

ADMIN_EMAIL = 'admin@nielit.gov.in'
ADMIN_PASSWORD = 'admin@nielit.gov.in'

# Column order used by fetch_user_row, so a test can compare a whole users row.
USER_COLUMNS = ('userId, password, email, firstName, lastName, address1, address2, '
                'zipcode, city, state, country, phone, profile_photo')

SCHEMA_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS users (
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
    phone TEXT,
    profile_photo TEXT
)''',
    '''CREATE TABLE IF NOT EXISTS products (
    productId INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price REAL,
    description TEXT,
    image TEXT,
    stock INTEGER,
    categoryId INTEGER
)''',
    '''CREATE TABLE IF NOT EXISTS categories (
    categoryId INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT
)''',
    '''CREATE TABLE IF NOT EXISTS kart (
    userId INTEGER,
    productId INTEGER
)''',
    '''CREATE TABLE IF NOT EXISTS allorders (
    orderId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER,
    quantity INTEGER,
    total_price REAL,
    order_date TEXT
)''',
    '''CREATE TABLE IF NOT EXISTS wishlist (
    wishlistId INTEGER PRIMARY KEY AUTOINCREMENT,
    userId INTEGER,
    productId INTEGER
)''',
)


def md5(text: str) -> str:
    """Return the hex md5 the shop stores for passwords."""
    return hashlib.md5(text.encode()).hexdigest()


def seed_database(db_path: Path) -> None:
    """Create the shop tables and seed one shopper, one admin and one product."""
    conn = sqlite3.connect(str(db_path))
    try:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute(
            'INSERT INTO users (password, email, firstName, lastName, address1, address2, '
            'zipcode, city, state, country, phone, profile_photo) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                md5(SHOPPER_PASSWORD), SHOPPER_EMAIL, SHOPPER_FIRST_NAME, SHOPPER_LAST_NAME,
                '1 Test Street', '', '110001', 'Delhi', 'Delhi', 'India', '9999999999', None,
            ),
        )
        conn.execute(
            'INSERT INTO users (password, email, firstName, lastName, address1, address2, '
            'zipcode, city, state, country, phone, profile_photo) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (md5(ADMIN_PASSWORD), ADMIN_EMAIL, 'Admin', 'User', '', '', '', '', '', '', '', None),
        )
        conn.execute("INSERT INTO categories (name) VALUES ('Books')")
        conn.execute(
            'INSERT INTO products (name, price, description, image, stock, categoryId) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            ('Sample Book', 100.0, 'A sample product', 'product-default.png', 10, 1),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_user_row(db_path: Path, email: str) -> Optional[Tuple]:
    """Return the whole users row of a shopper, or None."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute('SELECT ' + USER_COLUMNS + ' FROM users WHERE email = ?', (email,))
        return cur.fetchone()
    finally:
        conn.close()


def fetch_profile_photo(db_path: Path, email: str) -> Optional[str]:
    """Return users.profile_photo for a shopper, or None."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute('SELECT profile_photo FROM users WHERE email = ?', (email,))
        result = cur.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


def count_users(db_path: Path) -> int:
    """Return the number of users rows."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute('SELECT count(*) FROM users')
        return cur.fetchone()[0]
    finally:
        conn.close()


def stored_photo_names(photo_dir: Path) -> List[str]:
    """Return the sorted file names currently stored in the profile photo folder."""
    return sorted(os.listdir(str(photo_dir)))


def image_bytes(fmt: str, size_bytes: Optional[int] = None) -> bytes:
    """Return a real image in 'JPEG', 'PNG', 'WEBP' or 'GIF' format.

    When size_bytes is given the encoded image is padded with trailing zero
    bytes so len(result) == size_bytes exactly; size_bytes=0 returns b''.
    """
    if size_bytes == 0:
        return b''
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (180, 40, 40)).save(buffer, format=fmt)
    data = buffer.getvalue()
    if size_bytes is None:
        return data
    if size_bytes < len(data):
        raise ValueError('size_bytes is smaller than the encoded image')
    return data + b'\x00' * (size_bytes - len(data))


def post_photo(client: FlaskClient, data: bytes, filename: str, **extra_fields: str) -> TestResponse:
    """POST a profile photo upload exactly as the edit-profile form does."""
    form = {'photo': (io.BytesIO(data), filename)}
    form.update(extra_fields)
    return client.post('/account/profile/photo', data=form, content_type='multipart/form-data')


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Run a test inside a temporary working directory with its own database.

    The temporary directory holds database.db (schema plus seed rows) and
    static/uploads/profile_photos, so the app's relative paths resolve inside
    it. monkeypatch.chdir restores the working directory at teardown.
    """
    db_path = tmp_path / 'database.db'
    seed_database(db_path)
    upload_dir = tmp_path / 'static' / 'uploads'
    photo_dir = upload_dir / 'profile_photos'
    photo_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    # Imported after the chdir so app.py's ensure_schema() and makedirs() calls
    # act on the temporary directory, never on the repository checkout.
    import app as app_module  # noqa: F401

    return SimpleNamespace(
        db_path=db_path,
        photo_dir=photo_dir,
        upload_dir=upload_dir,
        app=app_module.app,
    )


@pytest.fixture
def client(workspace: SimpleNamespace) -> FlaskClient:
    """Return a Flask test client; depends on workspace so the temp cwd is active."""
    application = workspace.app
    application.testing = True
    return application.test_client()


@pytest.fixture
def sign_in(client: FlaskClient) -> Callable[..., None]:
    """Return a helper that signs a seeded shopper in through /login."""

    def _sign_in(email: str = SHOPPER_EMAIL, password: str = SHOPPER_PASSWORD) -> None:
        response = client.post('/login', data={'email': email, 'password': password})
        assert response.status_code == 302, response.status_code
        assert response.headers['Location'].rstrip('/') in ('', 'http://localhost'), \
            response.headers['Location']

    return _sign_in
