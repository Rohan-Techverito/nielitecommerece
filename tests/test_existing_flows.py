"""Regression smoke tests: the rest of the shop keeps working.

Profile photos live under static/uploads next to the product images, so these
tests drive the existing routes end to end against the temporary database that
conftest builds, and prove that uploading, replacing and removing a profile
photo never touches products, product image files, the cart, the wishlist or
the orders.
"""

import hashlib
import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Tuple

from flask.testing import FlaskClient

from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    image_bytes,
    post_photo,
)

PRODUCT_COLUMNS = 'productId, name, price, description, image, stock, categoryId'
COUNTED_TABLES = ('kart', 'wishlist', 'allorders')


def _row_count(db_path: Path, table: str) -> int:
    """Return the number of rows in one table."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute('SELECT count(*) FROM {0}'.format(table))
        return cur.fetchone()[0]
    finally:
        conn.close()


def _row_counts(db_path: Path) -> Dict[str, int]:
    """Return the row count of the cart, wishlist and order tables."""
    return {table: _row_count(db_path, table) for table in COUNTED_TABLES}


def _product_rows(db_path: Path) -> List[Tuple]:
    """Return every products row, in a stable order."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute('SELECT ' + PRODUCT_COLUMNS + ' FROM products ORDER BY productId')
        return cur.fetchall()
    finally:
        conn.close()


def _product_id(db_path: Path, name: str) -> int:
    """Return the productId of the product with that name."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute('SELECT productId, name FROM products')
        for product_id, product_name in cur.fetchall():
            if product_name == name:
                return product_id
    finally:
        conn.close()
    raise AssertionError('product {0!r} was not created'.format(name))


def _product_image_name(db_path: Path, product_id: int) -> str:
    """Return the image file name stored for one product."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute('SELECT image FROM products WHERE productId = ?', (product_id,))
        result = cur.fetchone()
    finally:
        conn.close()
    assert result is not None
    return result[0]


def _upload_file_hashes(upload_dir: Path) -> Dict[str, str]:
    """Hash every file directly inside static/uploads (product images live there)."""
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(upload_dir.iterdir())
        if path.is_file()
    }


def test_catalogue_and_category_pages(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    home = client.get('/')
    assert home.status_code == 200
    assert 'Sample Book' in home.get_data(as_text=True)

    category = client.get('/displayCategory?categoryId=1')
    assert category.status_code == 200
    assert 'Sample Book' in category.get_data(as_text=True)

    description = client.get('/productDescription?productId=1')
    assert description.status_code == 200
    assert 'Sample Book' in description.get_data(as_text=True)


def test_cart_checkout_and_order_flow(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    added = client.get('/addToCart?productId=1')
    assert added.status_code == 302
    assert _row_count(workspace.db_path, 'kart') == 1

    cart = client.get('/cart')
    assert cart.status_code == 200
    assert 'Sample Book' in cart.get_data(as_text=True)

    checkout = client.get('/checkout')
    assert checkout.status_code == 200
    assert 'Checkout' in checkout.get_data(as_text=True)

    ordered = client.get('/saveorder')
    assert ordered.status_code == 200
    assert 'Order Placed Successfully' in ordered.get_data(as_text=True)
    assert _row_count(workspace.db_path, 'allorders') == 1
    assert _row_count(workspace.db_path, 'kart') == 0

    orders = client.get('/account/orders')
    assert orders.status_code == 200
    assert 'Sample Book' in orders.get_data(as_text=True)

    removed = client.get('/removeFromCart?productId=1')
    assert removed.status_code == 302
    assert _row_count(workspace.db_path, 'kart') == 0


def test_wishlist_flow(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    added = client.get('/addToWishlist?productId=1')
    assert added.status_code == 302
    assert added.headers['Location'].endswith('/wishlist')
    assert _row_count(workspace.db_path, 'wishlist') == 1

    listing = client.get('/wishlist')
    assert listing.status_code == 200
    assert 'Sample Book' in listing.get_data(as_text=True)

    removed = client.post('/removeFromWishlist', data={'productId': '1'})
    assert removed.status_code == 302
    assert removed.headers['Location'].endswith('/wishlist')
    assert _row_count(workspace.db_path, 'wishlist') == 0

    empty = client.get('/wishlist')
    assert empty.status_code == 200
    assert 'Sample Book' not in empty.get_data(as_text=True)
    assert 'Your wishlist is empty.' in empty.get_data(as_text=True)


def test_admin_product_and_order_pages(client: FlaskClient, workspace: SimpleNamespace) -> None:
    login = client.post('/login', data={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD})
    assert login.status_code == 302

    dashboard = client.get('/admin')
    assert dashboard.status_code == 200
    assert 'Sample Book' in dashboard.get_data(as_text=True)

    added = client.post(
        '/admin/add',
        data={
            'name': 'Admin Book',
            'price': '150.50',
            'description': 'Added by the admin',
            'stock': '5',
            'category': '1',
            'image': (io.BytesIO(image_bytes('PNG')), 'admin-book.png'),
        },
        content_type='multipart/form-data',
    )
    assert added.status_code == 302
    assert added.headers['Location'].endswith('/admin')

    product_id = _product_id(workspace.db_path, 'Admin Book')
    assert _product_image_name(workspace.db_path, product_id) == 'admin-book.png'
    assert 'Admin Book' in client.get('/admin').get_data(as_text=True)

    edit_form = client.get('/admin/edit/{0}'.format(product_id))
    assert edit_form.status_code == 200
    assert 'Admin Book' in edit_form.get_data(as_text=True)

    edited = client.post(
        '/admin/edit/{0}'.format(product_id),
        data={
            'name': 'Edited Book',
            'price': '175.25',
            'description': 'Edited by the admin',
            'stock': '7',
            'category': '1',
            'image': (io.BytesIO(image_bytes('PNG')), 'edited-book.png'),
        },
        content_type='multipart/form-data',
    )
    assert edited.status_code == 302
    assert edited.headers['Location'].endswith('/admin')
    assert _product_image_name(workspace.db_path, product_id) == 'edited-book.png'

    deleted = client.get('/admin/delete/{0}'.format(product_id))
    assert deleted.status_code == 302
    assert deleted.headers['Location'].endswith('/admin')
    assert 'Edited Book' not in client.get('/admin').get_data(as_text=True)

    orders = client.get('/vieworders')
    assert orders.status_code == 200
    assert 'All Orders' in orders.get_data(as_text=True)


def test_profile_photo_upload_does_not_touch_product_images(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    # A real product image file next to the profile photo folder.
    product_image = workspace.upload_dir / 'product-default.png'
    product_image.write_bytes(image_bytes('PNG'))

    before_products = _product_rows(workspace.db_path)
    before_uploads = _upload_file_hashes(workspace.upload_dir)
    before_catalogue = client.get('/').get_data(as_text=True)
    before_counts = _row_counts(workspace.db_path)
    assert before_uploads == {'product-default.png': hashlib.sha256(product_image.read_bytes()).hexdigest()}

    # Upload with the original name of a product image, then replace, then remove.
    assert post_photo(client, image_bytes('PNG'), 'product-default.png').status_code == 302
    assert post_photo(client, image_bytes('JPEG'), 'product-default.png').status_code == 302
    assert client.post('/account/profile/photo/remove').status_code == 302

    assert _product_rows(workspace.db_path) == before_products
    assert _upload_file_hashes(workspace.upload_dir) == before_uploads
    assert product_image.read_bytes() == image_bytes('PNG')
    assert client.get('/').get_data(as_text=True) == before_catalogue
    assert _row_counts(workspace.db_path) == before_counts
