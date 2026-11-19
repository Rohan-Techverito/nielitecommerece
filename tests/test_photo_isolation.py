"""Acceptance tests for photo ownership and unsafe file names.

Both photo routes resolve the shopper from the session and storage derives the
stored file name from the user id plus a uuid, so the client supplied name never
reaches the path. These tests make that true in fact: a signed-out visitor is
sent to sign in, a forged user id in the form changes nothing, unusual names
cannot escape the photo folder, and two shoppers uploading the same original
name each keep their own picture.
"""

import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Tuple

import pytest
from flask.testing import FlaskClient
from PIL import Image

from conftest import (
    SHOPPER_EMAIL,
    fetch_profile_photo,
    fetch_user_row,
    image_bytes,
    md5,
    post_photo,
    stored_photo_names,
)
from profile_photos import PHOTO_ERROR_MESSAGE

OTHER_EMAIL = 'second.shopper@example.com'
OTHER_PASSWORD = 'second-pass'

# Preserved file at the working directory root (there is exactly one).
DATABASE_FILE = 'database.db'
# Every stored photo must land inside this folder.
PHOTO_PREFIX = 'static/uploads/profile_photos/'


def _insert_shopper(db_path: Path, email: str, first_name: str, last_name: str) -> int:
    """Insert one extra shopper row and return its userId."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO users (password, email, firstName, lastName, address1, address2, '
            'zipcode, city, state, country, phone, profile_photo) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (md5(OTHER_PASSWORD), email, first_name, last_name, '', '', '', '', '', '', '', None),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _solid_image(colour: Tuple[int, int, int], fmt: str = 'PNG') -> bytes:
    """Return a solid coloured image encoded in fmt."""
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), colour).save(buffer, format=fmt)
    return buffer.getvalue()


def _first_pixel(path: Path) -> Tuple[int, int, int]:
    """Return the top left pixel of a stored image as RGB."""
    with Image.open(str(path)) as image:
        return image.convert('RGB').getpixel((0, 0))


def _files_under(root: Path) -> List[str]:
    """Return every file below root as a sorted, root relative posix path."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())


def test_signed_out_upload_redirects_to_sign_in(
    client: FlaskClient, workspace: SimpleNamespace
) -> None:
    before_row = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)

    response = post_photo(client, image_bytes('JPEG'), 'photo.jpg')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/loginForm')
    assert stored_photo_names(workspace.photo_dir) == []
    assert fetch_user_row(workspace.db_path, SHOPPER_EMAIL) == before_row


def test_signed_out_edit_profile_redirects_to_root(client: FlaskClient) -> None:
    response = client.get('/account/profile/edit')

    assert response.status_code == 302
    assert response.headers['Location'] == '/'


def test_cannot_change_another_shoppers_photo(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    other_id = _insert_shopper(workspace.db_path, OTHER_EMAIL, 'Second', 'Shopper')
    sign_in()
    user_id = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)[0]

    # The form carries a foreign user id; the session decides who is updated.
    response = post_photo(
        client,
        image_bytes('JPEG'),
        'photo.jpg',
        userId=str(other_id),
        user_id=str(other_id),
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/account/profile/edit')
    own_photo = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert own_photo
    assert own_photo.startswith('user_{0}_'.format(user_id))
    assert fetch_profile_photo(workspace.db_path, OTHER_EMAIL) is None
    assert stored_photo_names(workspace.photo_dir) == [own_photo]


@pytest.mark.parametrize('filename, fmt, extension', [
    ('my photo.jpg', 'JPEG', '.jpg'),
    ('quote"photo.jpg', 'JPEG', '.jpg'),
    ('café.png', 'PNG', '.png'),
    ('../../evil.jpg', 'JPEG', '.jpg'),
    ('a..b.jpg', 'JPEG', '.jpg'),
])
def test_unusual_filenames_are_safe(
    client: FlaskClient,
    workspace: SimpleNamespace,
    sign_in: Callable[..., None],
    filename: str,
    fmt: str,
    extension: str,
) -> None:
    sign_in()
    user_id = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)[0]

    response = post_photo(client, image_bytes(fmt), filename)

    # The odd name must not break the request.
    assert response.status_code in (200, 302), response.status_code
    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    assert stored.startswith('user_{0}_'.format(user_id))
    assert stored.endswith(extension)

    # Nothing may be written outside the profile photo folder.
    written = _files_under(workspace.db_path.parent)
    assert written
    for relative in written:
        assert relative == DATABASE_FILE or relative.startswith(PHOTO_PREFIX), relative
    assert stored in stored_photo_names(workspace.photo_dir)

    # The page still renders the shopper's own photo.
    html = client.get('/account/profile').get_data(as_text=True)
    assert '/static/uploads/profile_photos/{0}'.format(stored) in html


def test_unusable_filename_refused(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    before_row = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)

    response = post_photo(client, image_bytes('JPEG'), 'photo.txt')

    assert response.status_code == 200
    assert PHOTO_ERROR_MESSAGE in response.get_data(as_text=True)
    assert fetch_user_row(workspace.db_path, SHOPPER_EMAIL) == before_row
    assert stored_photo_names(workspace.photo_dir) == []


def test_same_original_name_two_shoppers_keep_own_photo(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    other_id = _insert_shopper(workspace.db_path, OTHER_EMAIL, 'Second', 'Shopper')
    user_id = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)[0]
    own_image = _solid_image((200, 30, 30))
    other_image = _solid_image((30, 30, 200))

    sign_in()
    assert post_photo(client, own_image, 'shared-name.png').status_code == 302
    client.get('/logout')
    sign_in(OTHER_EMAIL, OTHER_PASSWORD)
    assert post_photo(client, other_image, 'shared-name.png').status_code == 302

    own_photo = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    other_photo = fetch_profile_photo(workspace.db_path, OTHER_EMAIL)
    assert own_photo
    assert other_photo
    assert own_photo != other_photo
    assert own_photo.startswith('user_{0}_'.format(user_id))
    assert other_photo.startswith('user_{0}_'.format(other_id))
    assert stored_photo_names(workspace.photo_dir) == sorted([own_photo, other_photo])

    # Each shopper's stored file holds that shopper's own picture.
    assert _first_pixel(workspace.photo_dir / own_photo) == (200, 30, 30)
    assert _first_pixel(workspace.photo_dir / other_photo) == (30, 30, 200)
