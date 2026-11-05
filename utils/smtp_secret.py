"""Protect newly entered SMTP credentials with the current Windows user's DPAPI key."""
import base64
import ctypes
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [("size",wintypes.DWORD),("data",ctypes.POINTER(ctypes.c_char))]


def _crypt(raw, decrypt):
    source = ctypes.create_string_buffer(raw)
    blob = Blob(len(raw),ctypes.cast(source,ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    api = ctypes.windll.crypt32
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    if not fn(ctypes.byref(blob),None,None,None,None,1,ctypes.byref(out)):
        raise OSError("smtp_setup")
    try:
        return ctypes.string_at(out.data,out.size)
    finally:
        ctypes.windll.kernel32.LocalFree(out.data)


def protect(password):
    return base64.b64encode(_crypt(password.encode("utf8"),False)).decode("ascii")


def store_password(password):
    import uuid
    from PySide6.QtCore import QSettings
    store=QSettings("ThesisWMS","Mail")
    key=uuid.uuid4().hex
    store.setValue(key,protect(password))
    store.sync()
    if store.status()!=QSettings.NoError:
        raise OSError("smtp_setup")
    return key


def load_password(key):
    from PySide6.QtCore import QSettings
    ciphertext=QSettings("ThesisWMS","Mail").value(key)
    return reveal(ciphertext) if ciphertext else None


def reveal(ciphertext):
    return _crypt(base64.b64decode(ciphertext,validate=True),True).decode("utf8")
