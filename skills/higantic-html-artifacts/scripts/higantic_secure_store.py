#!/usr/bin/env python3
"""Cross-platform secret storage for the HiGantic CLI."""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional


SERVICE_NAME = "higantic-cli"
MAX_PROTECTED_FILE_BYTES = 64 * 1024


class SecureStoreError(RuntimeError):
    pass


def config_directory() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HiGantic" / "cli"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        if not appdata:
            raise SecureStoreError("APPDATA is required to locate the HiGantic CLI configuration.")
        return Path(appdata) / "HiGantic" / "cli"
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".config") / "higantic"


def config_path() -> Path:
    return config_directory() / "config.json"


def protected_file_path() -> Path:
    return config_directory() / "credentials.json"


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SecureStoreError(f"Refusing unsafe credential directory: {path}")
        if os.name != "nt":
            if info.st_uid != os.getuid():
                raise SecureStoreError("Credential directory is not owned by the current user.")
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise SecureStoreError("Credential directory must have mode 0700.")
        return
    path.mkdir(parents=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path, 0o700)


def validate_private_file(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    _ensure_private_directory(path.parent)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SecureStoreError("Refusing a symlink or non-file credential store.")
    if os.name != "nt":
        if info.st_uid != os.getuid():
            raise SecureStoreError("Credential file is not owned by the current user.")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise SecureStoreError("Credential file must have mode 0600.")


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    _ensure_private_directory(path.parent)
    validate_private_file(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(str(temporary_path), str(path))
        if os.name != "nt":
            os.chmod(path, mode)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


class SecretStore:
    kind = "native"

    def preflight(self) -> None:
        probe = f"__preflight_{secrets.token_hex(8)}"
        value = secrets.token_urlsafe(24)
        self.put(probe, value)
        try:
            if self.get(probe) != value:
                raise SecureStoreError("Secure storage preflight could not read its probe credential.")
        finally:
            self.delete(probe)

    def get(self, profile: str) -> Optional[str]:
        raise NotImplementedError

    def put(self, profile: str, secret: str) -> None:
        raise NotImplementedError

    def delete(self, profile: str) -> None:
        raise NotImplementedError


class LinuxSecretServiceStore(SecretStore):
    def __init__(self) -> None:
        candidate = shutil.which("secret-tool")
        if not candidate:
            raise SecureStoreError("Linux Secret Service is unavailable: install a trusted secret-tool executable.")
        executable = Path(candidate)
        try:
            real = executable.resolve(strict=True)
            info = real.stat()
            original = executable.lstat()
        except OSError as error:
            raise SecureStoreError(f"Could not validate secret-tool: {error}") from None
        if stat.S_ISLNK(original.st_mode) or not stat.S_ISREG(info.st_mode) or not os.access(str(real), os.X_OK):
            raise SecureStoreError("secret-tool must be a regular executable, not a symlink.")
        if info.st_uid not in (0, os.getuid()) or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise SecureStoreError("secret-tool has unsafe ownership or write permissions.")
        self.executable = str(real)

    def _run(self, arguments, input_text: Optional[str] = None, allow_missing: bool = False) -> subprocess.CompletedProcess:
        environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())}
        for name in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "LANG"):
            if name in os.environ:
                environment[name] = os.environ[name]
        result = subprocess.run(
            [self.executable, *arguments],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=environment,
        )
        if result.returncode != 0 and not (allow_missing and result.returncode == 1):
            raise SecureStoreError("Linux Secret Service operation failed; unlock or configure your session keyring.")
        return result

    def get(self, profile: str) -> Optional[str]:
        result = self._run(["lookup", "service", SERVICE_NAME, "profile", profile], allow_missing=True)
        return result.stdout.rstrip("\n") if result.returncode == 0 else None

    def put(self, profile: str, secret: str) -> None:
        self._run(["store", "--label", f"HiGantic CLI ({profile})", "service", SERVICE_NAME, "profile", profile], input_text=secret)

    def delete(self, profile: str) -> None:
        self._run(["clear", "service", SERVICE_NAME, "profile", profile], allow_missing=True)


class MacOSKeychainStore(SecretStore):
    def __init__(self) -> None:
        library_path = ctypes.util.find_library("Security")
        if not library_path:
            raise SecureStoreError("macOS Keychain Security framework is unavailable.")
        self.security = ctypes.CDLL(library_path)
        self.security.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        self.security.SecKeychainAddGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.security.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        self.security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        self.security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        core_foundation_path = ctypes.util.find_library("CoreFoundation")
        if not core_foundation_path:
            raise SecureStoreError("macOS CoreFoundation framework is unavailable.")
        self.core_foundation = ctypes.CDLL(core_foundation_path)
        self.core_foundation.CFRelease.argtypes = [ctypes.c_void_p]

    def _release_item(self, item) -> None:
        if item:
            self.core_foundation.CFRelease(item)

    @staticmethod
    def _bytes(value: str):
        encoded = value.encode("utf-8")
        return encoded, ctypes.c_char_p(encoded)

    def _find(self, profile: str):
        service_bytes, service = self._bytes(SERVICE_NAME)
        account_bytes, account = self._bytes(profile)
        length = ctypes.c_uint32()
        data = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = self.security.SecKeychainFindGenericPassword(None, len(service_bytes), service, len(account_bytes), account, ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
        return status, length, data, item

    def get(self, profile: str) -> Optional[str]:
        status, length, data, item = self._find(profile)
        if status == -25300:
            return None
        if status != 0:
            raise SecureStoreError("macOS Keychain lookup failed.")
        try:
            return ctypes.string_at(data, length.value).decode("utf-8")
        finally:
            self.security.SecKeychainItemFreeContent(None, data)
            self._release_item(item)

    def put(self, profile: str, secret: str) -> None:
        status, _length, data, item = self._find(profile)
        if status == 0:
            try:
                self.security.SecKeychainItemFreeContent(None, data)
                secret_bytes, secret_pointer = self._bytes(secret)
                if self.security.SecKeychainItemModifyAttributesAndData(item, None, len(secret_bytes), secret_pointer) != 0:
                    raise SecureStoreError("macOS Keychain update failed.")
            finally:
                self._release_item(item)
            return
        if status != -25300:
            raise SecureStoreError("macOS Keychain lookup failed.")
        service_bytes, service = self._bytes(SERVICE_NAME)
        account_bytes, account = self._bytes(profile)
        secret_bytes, secret_pointer = self._bytes(secret)
        result = self.security.SecKeychainAddGenericPassword(None, len(service_bytes), service, len(account_bytes), account, len(secret_bytes), secret_pointer, None)
        if result != 0:
            raise SecureStoreError("macOS Keychain storage failed.")

    def delete(self, profile: str) -> None:
        status, _length, data, item = self._find(profile)
        if status == -25300:
            return
        if status != 0:
            raise SecureStoreError("macOS Keychain lookup failed.")
        try:
            self.security.SecKeychainItemFreeContent(None, data)
            if self.security.SecKeychainItemDelete(item) != 0:
                raise SecureStoreError("macOS Keychain deletion failed.")
        finally:
            self._release_item(item)


if os.name == "nt":
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]


class WindowsCredentialStore(SecretStore):
    def __init__(self) -> None:
        if os.name != "nt":
            raise SecureStoreError("Windows Credential Manager is unavailable on this platform.")
        self.advapi = ctypes.WinDLL("Advapi32", use_last_error=True)
        self.advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), ctypes.c_uint32]
        self.advapi.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        self.advapi.CredFree.argtypes = [ctypes.c_void_p]
        self.advapi.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]

    @staticmethod
    def _target(profile: str) -> str:
        return f"HiGantic CLI/{profile}"

    def get(self, profile: str) -> Optional[str]:
        pointer = ctypes.POINTER(CREDENTIALW)()
        if not self.advapi.CredReadW(self._target(profile), 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise SecureStoreError("Windows Credential Manager lookup failed.")
        try:
            credential = pointer.contents
            data = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return data.decode("utf-16-le")
        finally:
            self.advapi.CredFree(pointer)

    def put(self, profile: str, secret: str) -> None:
        encoded = secret.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = CREDENTIALW()
        credential.Type = 1
        credential.TargetName = self._target(profile)
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = 2
        credential.UserName = profile
        try:
            if not self.advapi.CredWriteW(ctypes.byref(credential), 0):
                raise SecureStoreError("Windows Credential Manager storage failed.")
        finally:
            ctypes.memset(ctypes.addressof(buffer), 0, len(encoded))

    def delete(self, profile: str) -> None:
        if not self.advapi.CredDeleteW(self._target(profile), 1, 0) and ctypes.get_last_error() != 1168:
            raise SecureStoreError("Windows Credential Manager deletion failed.")


def _windows_dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        return data
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = DATA_BLOB(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = DATA_BLOB()
    crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = function(ctypes.byref(source), "HiGantic CLI", None, None, None, 0x1, ctypes.byref(target))
    else:
        ok = function(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target))
    if not ok:
        raise SecureStoreError("Windows DPAPI operation failed.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.memset(ctypes.addressof(source_buffer), 0, len(data))
        kernel32.LocalFree(target.pbData)


class ProtectedFileStore(SecretStore):
    kind = "file"

    def __init__(self, allow: bool) -> None:
        if not allow:
            raise SecureStoreError("Protected-file storage requires both --storage file and --allow-protected-file.")
        self.path = protected_file_path()
        _ensure_private_directory(self.path.parent)
        validate_private_file(self.path)

    def preflight(self) -> None:
        _ensure_private_directory(self.path.parent)
        validate_private_file(self.path)

    def _load(self) -> Dict[str, str]:
        validate_private_file(self.path)
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_bytes()
            if len(raw) > MAX_PROTECTED_FILE_BYTES:
                raise ValueError("file exceeds 64 KiB")
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise SecureStoreError(f"Could not read protected credential file: {error}") from None
        if not isinstance(payload, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in payload.items()):
            raise SecureStoreError("Protected credential file has an invalid format.")
        return payload

    def _save(self, payload: Dict[str, str]) -> None:
        atomic_write(self.path, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def get(self, profile: str) -> Optional[str]:
        value = self._load().get(profile)
        if value is None:
            return None
        if os.name == "nt":
            try:
                return _windows_dpapi(base64.b64decode(value), protect=False).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as error:
                raise SecureStoreError(f"Could not decrypt protected credential: {error}") from None
        return value

    def put(self, profile: str, secret: str) -> None:
        payload = self._load()
        payload[profile] = base64.b64encode(_windows_dpapi(secret.encode("utf-8"), protect=True)).decode("ascii") if os.name == "nt" else secret
        self._save(payload)

    def delete(self, profile: str) -> None:
        payload = self._load()
        if profile not in payload:
            return
        del payload[profile]
        self._save(payload)


def native_store() -> SecretStore:
    if sys.platform == "darwin":
        return MacOSKeychainStore()
    if os.name == "nt":
        return WindowsCredentialStore()
    return LinuxSecretServiceStore()


def open_store(kind: str, allow_protected_file: bool = False) -> SecretStore:
    if kind == "file":
        return ProtectedFileStore(allow_protected_file)
    if kind != "native":
        raise SecureStoreError(f"Unknown secure storage type: {kind}")
    return native_store()
