"""Acceptance tests for the single-photo lifecycle.

Pins the ticket's lifecycle rules against app.upload_profile_photo,
app.remove_profile_photo and the profile_photos storage helpers: the photo is
shown on both profile pages, a replacement replaces the previous file, the same
picture twice leaves one stored file, removing restores the initials avatar, and
a photo whose file vanished behind the app's back falls back to the initials
avatar instead of a broken image.
"""

import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List

from flask.testing import FlaskClient

from conftest import (
    SHOPPER_EMAIL,
    SHOPPER_INITIALS,
    fetch_profile_photo,
    fetch_user_row,
    image_bytes,
    post_photo,
    stored_photo_names,
)

PROFILE_AVATAR_IMAGE_RE = re.compile(r'<img[^>]*class="profile-avatar"[^>]*>')


def _profile_photo_srcs(html: str) -> List[str]:
    """Return every profile-photo src rendered in the page."""
    return re.findall(r'src="(/static/uploads/profile_photos/[^"]+)"', html)


def _avatar_initials(html: str) -> List[str]:
    """Return the initials rendered inside the avatar placeholder."""
    return [text.strip() for text in re.findall(r'<div class="profile-avatar">([^<]*)</div>', html)]


def _users_photo_files(photo_dir: Path, user_id: int) -> List[str]:
    """Return the stored photo file names belonging to one shopper."""
    prefix = 'user_{0}_'.format(user_id)
    return [name for name in stored_photo_names(photo_dir) if name.startswith(prefix)]


def test_photo_shown_on_both_profile_pages(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    user_id = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)[0]

    upload = post_photo(client, image_bytes('JPEG'), 'photo.jpg')
    assert upload.status_code == 302
    assert upload.headers['Location'].endswith('/account/profile/edit')

    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    assert stored.startswith('user_{0}_'.format(user_id))
    expected_src = '/static/uploads/profile_photos/{0}'.format(stored)

    for page in ('/account/profile/edit', '/account/profile'):
        response = client.get(page)
        assert response.status_code == 200, page
        html = response.get_data(as_text=True)
        assert _profile_photo_srcs(html) == [expected_src], page
        images = PROFILE_AVATAR_IMAGE_RE.findall(html)
        assert len(images) == 1, page
        assert expected_src in images[0], page
        assert _avatar_initials(html) == [], page


def test_upload_replaces_previous_photo(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    user_id = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)[0]

    assert post_photo(client, image_bytes('JPEG'), 'first.jpg').status_code == 302
    first = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert first
    assert os.path.isfile(os.path.join(str(workspace.photo_dir), first))

    assert post_photo(client, image_bytes('PNG'), 'second.png').status_code == 302
    second = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert second
    assert second != first

    # Exactly one photo remains, it is the new one, and the old file is gone.
    assert _users_photo_files(workspace.photo_dir, user_id) == [second]
    assert stored_photo_names(workspace.photo_dir) == [second]
    assert not os.path.isfile(os.path.join(str(workspace.photo_dir), first))


def test_same_picture_twice_leaves_one_file(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    user_id = fetch_user_row(workspace.db_path, SHOPPER_EMAIL)[0]
    picture = image_bytes('JPEG')

    assert post_photo(client, picture, 'same.jpg').status_code == 302
    assert post_photo(client, picture, 'same.jpg').status_code == 302

    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    assert stored.startswith('user_{0}_'.format(user_id))
    assert _users_photo_files(workspace.photo_dir, user_id) == [stored]
    assert stored_photo_names(workspace.photo_dir) == [stored]


def test_remove_restores_initials_avatar(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    assert post_photo(client, image_bytes('JPEG'), 'photo.jpg').status_code == 302
    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    assert os.path.isfile(os.path.join(str(workspace.photo_dir), stored))

    removed = client.post('/account/profile/photo/remove')
    assert removed.status_code == 302
    assert removed.headers['Location'].endswith('/account/profile/edit')

    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) is None
    assert not os.path.isfile(os.path.join(str(workspace.photo_dir), stored))
    assert stored_photo_names(workspace.photo_dir) == []

    for page in ('/account/profile/edit', '/account/profile'):
        response = client.get(page)
        assert response.status_code == 200, page
        html = response.get_data(as_text=True)
        assert _profile_photo_srcs(html) == [], page
        assert PROFILE_AVATAR_IMAGE_RE.findall(html) == [], page
        assert _avatar_initials(html) == [SHOPPER_INITIALS], page

    # The Remove control is offered only while a photo exists.
    assert 'Remove Photo' not in client.get('/account/profile/edit').get_data(as_text=True)


def test_remove_without_photo_is_harmless(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    before_files = stored_photo_names(workspace.photo_dir)
    assert before_files == []

    removed = client.post('/account/profile/photo/remove')
    assert removed.status_code == 302
    assert removed.headers['Location'].endswith('/account/profile/edit')

    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) is None
    assert stored_photo_names(workspace.photo_dir) == before_files
    assert _avatar_initials(client.get('/account/profile/edit').get_data(as_text=True)) == [
        SHOPPER_INITIALS
    ]


def test_photo_survives_sign_out_and_in(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    assert post_photo(client, image_bytes('PNG'), 'photo.png').status_code == 302
    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    expected_src = '/static/uploads/profile_photos/{0}'.format(stored)

    logout = client.get('/logout')
    assert logout.status_code == 302
    signed_out = client.get('/account/profile')
    assert signed_out.status_code == 302

    sign_in()

    html = client.get('/account/profile').get_data(as_text=True)
    assert _profile_photo_srcs(html) == [expected_src]
    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) == stored


def test_missing_file_falls_back_to_initials(
    client: FlaskClient, workspace: SimpleNamespace, sign_in: Callable[..., None]
) -> None:
    sign_in()
    assert post_photo(client, image_bytes('JPEG'), 'photo.jpg').status_code == 302
    stored = fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL)
    assert stored
    stored_path = os.path.join(str(workspace.photo_dir), stored)
    assert os.path.isfile(stored_path)

    # The file disappears behind the app's back while the row still names it.
    os.remove(stored_path)
    assert fetch_profile_photo(workspace.db_path, SHOPPER_EMAIL) == stored

    for page in ('/account/profile', '/account/profile/edit'):
        response = client.get(page)
        assert response.status_code == 200, page
        html = response.get_data(as_text=True)
        assert '/static/uploads/profile_photos/' not in html, page
        assert PROFILE_AVATAR_IMAGE_RE.findall(html) == [], page
        assert _avatar_initials(html) == [SHOPPER_INITIALS], page
