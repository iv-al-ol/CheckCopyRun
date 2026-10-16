"""Обёртка над DPAPI (CryptProtectData / CryptUnprotectData).

Шифрование привязано к текущему пользователю Windows. Файл
settings.dat нельзя расшифровать на другой учётке или машине.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from utils.logger import get_logger

logger = get_logger(__name__)

_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
_crypt32.CryptProtectData.restype = wintypes.BOOL

_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL

_kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
_kernel32.LocalFree.restype = wintypes.HLOCAL


class DpapiError(RuntimeError):
    pass


def _to_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(
        cbData=len(data),
        pbData=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)),
    )
    return blob, buf  # buf держим живым


def _from_blob(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _kernel32.LocalFree(blob.pbData)


def protect(data: bytes, description: str = "CheckCopyRun") -> bytes:
    in_blob, _keep = _to_blob(data)
    out_blob = DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        err = ctypes.get_last_error()
        raise DpapiError(f"CryptProtectData failed (WinError {err})")
    return _from_blob(out_blob)


def unprotect(data: bytes) -> bytes:
    in_blob, _keep = _to_blob(data)
    out_blob = DATA_BLOB()
    desc_ptr = wintypes.LPWSTR()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        ctypes.byref(desc_ptr),
        None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        err = ctypes.get_last_error()
        raise DpapiError(f"CryptUnprotectData failed (WinError {err})")
    if desc_ptr:
        _kernel32.LocalFree(desc_ptr)
    return _from_blob(out_blob)
