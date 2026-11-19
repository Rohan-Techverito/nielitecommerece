"""Acceptance tests for profile photo validation.

Pins the ticket's upload rules against profile_photos.validate_photo /
save_photo and the /account/profile/photo route: accepted types, the inclusive
2 MB boundary, one clear refusal message, and nothing saved on refusal.
"""

from types import SimpleNamespace
from typing import Callable

import pytest
from flask.testing import FlaskClient

from conftest import (
    SHOPPER_EMAIL,
    count_users,
    fetch_profile_photo,
    fetch_user_row,
    image_bytes,
    post_photo,
    stored_photo_names,
)
from profile_photos import PHOTO_ERROR_MESSAGE, PHOTO_MAX_BYTES


@pytest.mark.parametrize('fmt, filename, stored_extension', [
    ('JPEG', 'photo.jpg', '.jpg'),
    ('PNG', 'photo.png', '.png'),
    ('WEBP', 'photo.webp', '.webp'),
])
def test_valid_formats_accepted(
    client: FlaskClient,
    workspace: SimpleNamespace,
    sign_in: Callable[..., None],
    fmt: str,
    filename: str,
    stored_extension: str,
) -> None:
    sign_in()
    user_id = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)[0]

    response = post_photo(client, image_bytes(fmt), filename)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/account/profile/edit')
    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    assert stored.startswith('user_{0}_'.format(user_id))
    assert stored.endswith(stored_extension)
    assert stored_photo_names(workspace.photo_dir) == [stored]


def test_uppercase_extension_accepted(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    response = post_photo(client, image_bytes('JPEG'), 'photo.JPG')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/account/profile/edit')
    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    assert stored.endswith('.jpg')
    assert stored_photo_names(workspace.photo_dir) == [stored]


def test_non_image_renamed_to_jpg_refused(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    response = post_photo(client, b'not an image', 'photo.jpg')

    assert response.status_code == 200
    assert PHOTO_ERROR_MESSAGE in response.get_data(as_text=True)
    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) is None
    assert stored_photo_names(workspace.photo_dir) == []


def test_gif_refused(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    response = post_photo(client, image_bytes('GIF'), 'animation.gif')

    assert response.status_code == 200
    assert PHOTO_ERROR_MESSAGE in response.get_data(as_text=True)
    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) is None
    assert stored_photo_names(workspace.photo_dir) == []


def test_zero_byte_file_refused(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    response = post_photo(client, image_bytes('JPEG', 0), 'photo.jpg')

    assert response.status_code == 200
    assert PHOTO_ERROR_MESSAGE in response.get_data(as_text=True)
    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) is None
    assert stored_photo_names(workspace.photo_dir) == []


def test_two_megabyte_boundary(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()

    at_limit = image_bytes('JPEG', PHOTO_MAX_BYTES)
    assert len(at_limit) == 2097152
    accepted = post_photo(client, at_limit, 'at-limit.jpg')
    assert accepted.status_code == 302
    assert accepted.headers['Location'].endswith('/account/profile/edit')
    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    assert stored_photo_names(workspace.photo_dir) == [stored]

    over_limit = image_bytes('JPEG', PHOTO_MAX_BYTES + 1)
    assert len(over_limit) == 2097153
    refused = post_photo(client, over_limit, 'over-limit.jpg')
    assert refused.status_code == 200
    assert PHOTO_ERROR_MESSAGE in refused.get_data(as_text=True)
    # The refusal must leave the already stored photo untouched.
    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) == stored
    assert stored_photo_names(workspace.photo_dir) == [stored]


def test_refusal_message_names_types_and_limit(client: FlaskClient, sign_in: Callable[..., None]) -> None:
    sign_in()

    body = post_photo(client, b'not an image', 'photo.jpg').get_data(as_text=True)

    assert PHOTO_ERROR_MESSAGE in body
    assert body.count(PHOTO_ERROR_MESSAGE) == 1
    assert 'JPEG' in PHOTO_ERROR_MESSAGE
    assert 'PNG' in PHOTO_ERROR_MESSAGE
    assert 'WebP' in PHOTO_ERROR_MESSAGE
    assert '2 MB' in PHOTO_ERROR_MESSAGE


def test_invalid_upload_saves_nothing(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    before_row = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)
    before_users = count_users(workspace.db_path)
    before_files = stored_photo_names(workspace.photo_dir)

    refused_uploads = (
        (b'not an image', 'photo.jpg'),
        (image_bytes('GIF'), 'animation.gif'),
        (image_bytes('JPEG', 0), 'photo.jpg'),
        (image_bytes('JPEG', PHOTO_MAX_BYTES + 1), 'photo.jpg'),
    )
    for data, filename in refused_uploads:
        response = post_photo(client, data, filename)
        assert response.status_code == 200
        assert PHOTO_ERROR_MESSAGE in response.get_data(as_text=True)
        assert fetch_user_row(workspace.db_path, SHOPPER_EMAIL) == before_row
        assert count_users(workspace.db_path) == before_users
        assert stored_photo_names(workspace.photo_dir) == before_files
