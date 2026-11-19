"""Validation and storage helpers for shopper profile photos.

Profile photos are stored in their own subfolder of the static tree, with a
generated file name, so nothing a client sends can influence the stored path.
"""

import os
import uuid
from typing import Optional

from PIL import Image, ImageOps
from werkzeug.datastructures import FileStorage

# Folder (relative to the application working directory) holding profile photos.
PROFILE_PHOTO_DIR = 'static/uploads/profile_photos'

# 'Up to 2 MB' is inclusive: a file of exactly PHOTO_MAX_BYTES is accepted.
PHOTO_MAX_BYTES = 2 * 1024 * 1024

# PIL Image.format value -> extension used for the stored file.
PHOTO_ALLOWED_FORMATS = {
    'JPEG': 'jpg',
    'PNG': 'png',
    'WEBP': 'webp',
}

# Used only as a pre-check on the client supplied name; the PIL format decides.
PHOTO_ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

# One message for wrong type, oversized, zero-byte and corrupt files.
PHOTO_ERROR_MESSAGE = 'Please choose a JPEG, PNG or WebP image no larger than 2 MB.'

_EXT_TO_FORMAT = {extension: image_format for image_format, extension in PHOTO_ALLOWED_FORMATS.items()}


class PhotoValidationError(Exception):
    """Raised when an uploaded profile photo cannot be accepted."""

    def __init__(self, message: Optional[str] = None) -> None:
        self.message = message or PHOTO_ERROR_MESSAGE
        super().__init__(self.message)


def _client_extension(filename: Optional[str]) -> str:
    """Return the lowercased extension of a client supplied name, or ''."""
    if not filename or '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def _stream_size(file_storage: FileStorage) -> int:
    """Return the number of bytes in the upload, leaving the stream rewound."""
    stream = file_storage.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def _safe_basename(filename: Optional[str]) -> Optional[str]:
    """Return filename when it is a plain file name, otherwise None."""
    if not filename:
        return None
    if filename in ('.', '..'):
        return None
    if '/' in filename or '\\' in filename:
        return None
    if os.path.basename(filename) != filename:
        return None
    return filename


def validate_photo(file_storage: FileStorage) -> str:
    """Validate an upload and return 'jpg', 'png' or 'webp'.

    The check is content first: the Pillow detected format decides the stored
    extension, so an uppercase '.JPG' name or a PNG named '.jpg' is accepted,
    while a text file renamed '.jpg' is refused. Raises PhotoValidationError
    (always carrying PHOTO_ERROR_MESSAGE) for anything unacceptable.
    """
    if file_storage is None:
        raise PhotoValidationError()

    extension_hint = _client_extension(getattr(file_storage, 'filename', None))
    if extension_hint and extension_hint not in PHOTO_ALLOWED_EXTENSIONS:
        raise PhotoValidationError()

    try:
        size = _stream_size(file_storage)
    except Exception:
        raise PhotoValidationError()

    # Size is checked before decoding so an oversized upload is never decoded.
    if size <= 0 or size > PHOTO_MAX_BYTES:
        raise PhotoValidationError()

    stream = file_storage.stream
    image_format = ''
    try:
        stream.seek(0)
        with Image.open(stream) as image:
            image_format = (image.format or '').upper()
            image.verify()
    except Exception:
        raise PhotoValidationError()
    finally:
        stream.seek(0)

    if image_format not in PHOTO_ALLOWED_FORMATS:
        raise PhotoValidationError()

    return PHOTO_ALLOWED_FORMATS[image_format]


def save_photo(file_storage: FileStorage, user_id: int, previous_filename: Optional[str]) -> str:
    """Store an uploaded photo and return the generated file name.

    The image is re-encoded (after applying its EXIF orientation) so a phone
    photo lands upright and any payload appended to the upload is dropped. The
    previous file of the same shopper is deleted, so one shopper keeps at most
    one photo.
    """
    extension = validate_photo(file_storage)
    os.makedirs(PROFILE_PHOTO_DIR, exist_ok=True)

    stored_filename = 'user_{0}_{1}.{2}'.format(user_id, uuid.uuid4().hex, extension)
    stored_path = os.path.join(PROFILE_PHOTO_DIR, stored_filename)
    stream = file_storage.stream

    try:
        stream.seek(0)
        with Image.open(stream) as image:
            oriented = ImageOps.exif_transpose(image)
            # Drop any EXIF (including an orientation tag) from the re-encode.
            oriented.info.pop('exif', None)
            if extension == 'jpg' and oriented.mode not in ('RGB', 'L', 'CMYK'):
                oriented = oriented.convert('RGB')
            oriented.save(stored_path, format=_EXT_TO_FORMAT[extension])
    except Exception:
        if os.path.isfile(stored_path):
            try:
                os.remove(stored_path)
            except OSError:
                pass
        raise PhotoValidationError()
    finally:
        try:
            stream.seek(0)
        except Exception:
            pass

    delete_photo_file(previous_filename)
    return stored_filename


def delete_photo_file(filename: Optional[str]) -> None:
    """Delete a stored photo, ignoring None, missing files and unsafe names."""
    name = _safe_basename(filename)
    if not name:
        return
    path = os.path.join(PROFILE_PHOTO_DIR, name)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def photo_public_path(filename: Optional[str]) -> Optional[str]:
    """Return the static-relative path of an existing photo, else None."""
    name = _safe_basename(filename)
    if not name:
        return None
    if not os.path.isfile(os.path.join(PROFILE_PHOTO_DIR, name)):
        return None
    return 'uploads/profile_photos/{0}'.format(name)


def initials(first_name: Optional[str], last_name: Optional[str]) -> str:
    """Return the initials avatar text, e.g. 'LV' for Lovnish Verma."""
    letters = []
    for value in (first_name, last_name):
        if value:
            stripped = str(value).strip()
            if stripped:
                letters.append(stripped[0].upper())
    if not letters:
        return '?'
    return ''.join(letters)
