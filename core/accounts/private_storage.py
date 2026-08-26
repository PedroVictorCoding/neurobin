import base64
import io
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import Storage
from django.core.exceptions import ImproperlyConfigured
from django.utils.deconstruct import deconstructible


MAGIC = b'NBCLIN1'


def _keyring():
    raw = getattr(settings, 'CLINICAL_DOCUMENT_KEYS', '')
    keys = {}
    for item in filter(None, (part.strip() for part in raw.split(','))):
        version, encoded = item.split(':', 1)
        key = base64.urlsafe_b64decode(encoded)
        if len(key) != 32:
            raise ImproperlyConfigured('Clinical document AES keys must decode to 32 bytes.')
        keys[version] = key
    return keys


def active_key_version():
    version = getattr(settings, 'CLINICAL_DOCUMENT_ACTIVE_KEY', '')
    if version not in _keyring():
        raise ImproperlyConfigured('Active clinical document encryption key is unavailable.')
    return version


def encrypt_blob(plaintext, *, associated_data=b'neurobin-source-snapshot'):
    version = active_key_version()
    nonce = os.urandom(12)
    return version, nonce + AESGCM(_keyring()[version]).encrypt(nonce, plaintext, associated_data)


def decrypt_blob(payload, version, *, associated_data=b'neurobin-source-snapshot'):
    key = _keyring().get(version)
    if key is None:
        raise ImproperlyConfigured(f'Encryption key {version!r} is unavailable.')
    return AESGCM(key).decrypt(payload[:12], payload[12:], associated_data)


@deconstructible
class EncryptedPrivateStorage(Storage):
    """AES-GCM storage rooted outside MEDIA_ROOT; names are never public URLs."""
    def _root(self):
        root = Path(settings.CLINICAL_DOCUMENT_ROOT).resolve()
        media = Path(settings.MEDIA_ROOT).resolve()
        if root == media or media in root.parents:
            raise ImproperlyConfigured('CLINICAL_DOCUMENT_ROOT must be outside MEDIA_ROOT.')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        return root

    def path(self, name):
        candidate = (self._root() / name).resolve()
        if self._root() not in candidate.parents:
            raise ValueError('Invalid private document path.')
        return str(candidate)

    def _save(self, name, content):
        version = active_key_version()
        key = _keyring()[version]
        nonce = os.urandom(12)
        plaintext = content.read()
        version_bytes = version.encode('ascii')
        encrypted = MAGIC + bytes([len(version_bytes)]) + version_bytes + nonce + AESGCM(key).encrypt(nonce, plaintext, name.encode())
        path = Path(self.path(name))
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        with open(path, 'xb') as handle:
            handle.write(encrypted)
        os.chmod(path, 0o600)
        return name

    def _open(self, name, mode='rb'):
        payload = Path(self.path(name)).read_bytes()
        if not payload.startswith(MAGIC):
            raise ValueError('Invalid encrypted clinical document.')
        version_len = payload[len(MAGIC)]
        start = len(MAGIC) + 1
        version = payload[start:start + version_len].decode('ascii')
        nonce = payload[start + version_len:start + version_len + 12]
        ciphertext = payload[start + version_len + 12:]
        key = _keyring().get(version)
        if key is None:
            raise ImproperlyConfigured(f'Clinical document key {version!r} is unavailable.')
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, name.encode())
        return File(io.BytesIO(plaintext), name=name)

    def exists(self, name):
        return Path(self.path(name)).exists()

    def delete(self, name):
        path = Path(self.path(name))
        if path.exists():
            path.unlink()

    def size(self, name):
        with self.open(name, 'rb') as handle:
            return len(handle.read())

    def url(self, name):
        raise ValueError('Private clinical documents do not have direct URLs.')


clinical_document_storage = EncryptedPrivateStorage()
