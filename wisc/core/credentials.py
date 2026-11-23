"""Ely.by sessions in native credential storage, with a memory-only fallback.

Only native keyring backends are accepted. Missing dependencies, locked vaults,
and backend errors must never cause tokens to be written to a normal file.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading


_NATIVE_BACKENDS = {
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.libsecret",
    "keyring.backends.kwallet",
}

_SECRET_FIELD = re.compile(
    r'''(?i)((?:--)?(?:access[_-]?token|client[_-]?token|refresh[_-]?token|api[_-]?key|x-api-key|password|totp_code)\b["']?[ \t]*(?:[=:][ \t]*|[ \t]+))(\[REDACTED\]|["'][^"'\r\n]*["']|[^\s,;\]}]+)'''
)


def redact_credentials(text: str, sensitive_values=()) -> str:
    """Remove credentials before displaying, exporting, or writing game logs."""
    for value in sensitive_values:
        if isinstance(value, str) and value:
            text = text.replace(value, "[REDACTED]")
    return _SECRET_FIELD.sub(lambda match: match[1] + "[REDACTED]", text)


def _native_backend():
    try:
        import keyring

        selected = keyring.get_keyring()
        candidates = (
            selected.backends
            if type(selected).__module__ == "keyring.backends.chainer"
            else [selected]
        )
        for backend in candidates:
            if type(backend).__module__ in _NATIVE_BACKENDS and backend.priority > 0:
                return backend
    except Exception:
        # Never log backend exceptions: some include the supplied credentials.
        pass
    return None


def _tokens(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result = {
        name: value[name]
        for name in ("access_token", "client_token")
        if isinstance(value.get(name), str) and value[name]
    }
    return result if result.get("access_token") else {}


class CredentialStore:
    def __init__(self, namespace: str, *, service_prefix: str = "Wisc.Ely.by",
                 legacy_service_prefixes: tuple[str, ...] | None = None,
                 legacy_namespaces: tuple[str, ...] = ()):
        scope = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:24]
        self.service = f"{service_prefix}.{scope}"
        if legacy_service_prefixes is None:
            legacy_service_prefixes = ("Gr8Launcher.Ely.by",) if service_prefix == "Wisc.Ely.by" else ()
        aliases = [f"{prefix}.{scope}" for prefix in legacy_service_prefixes if prefix != service_prefix]
        for legacy_namespace in legacy_namespaces:
            legacy_scope = hashlib.sha256(legacy_namespace.encode("utf-8")).hexdigest()[:24]
            aliases.extend(f"{prefix}.{legacy_scope}" for prefix in (service_prefix, *legacy_service_prefixes))
        self.legacy_services = tuple(service for service in dict.fromkeys(aliases) if service != self.service)
        self._backend = None
        self._backend_checked = False
        self._sessions: dict[str, dict[str, str]] = {}
        self._persistent: set[str] = set()
        self._lock = threading.RLock()

    def _get_backend(self):
        if not self._backend_checked:
            self._backend = _native_backend()
            self._backend_checked = True
        return self._backend

    def get(self, reference: str) -> dict[str, str]:
        with self._lock:
            if reference not in self._sessions:
                tokens = {}
                backend = self._get_backend()
                if backend is not None:
                    for service in (self.service, *self.legacy_services):
                        try:
                            value = backend.get_password(service, reference)
                            tokens = _tokens(json.loads(value)) if value else {}
                        except Exception:
                            continue
                        if tokens:
                            if service != self.service:
                                self._save_native(backend, reference, tokens)
                            break
                self._sessions[reference] = tokens
                if tokens:
                    self._persistent.add(reference)
            return self._sessions[reference].copy()

    def _save_native(self, backend, reference: str, tokens: dict[str, str]) -> bool:
        try:
            payload = json.dumps(tokens)
            backend.set_password(self.service, reference, payload)
            if _tokens(json.loads(backend.get_password(self.service, reference))) != tokens:
                return False
        except Exception:
            return False
        for service in self.legacy_services:
            try:
                # Keep existing aliases usable if an update is rolled back.
                # Fresh installs create only Wisc entries; sign-out deletes both.
                if backend.get_password(service, reference):
                    backend.set_password(service, reference, payload)
            except Exception:
                pass
        return True

    def put(self, reference: str, tokens: dict[str, str]) -> bool:
        with self._lock:
            clean = _tokens(tokens)
            self._sessions[reference] = clean
            self._persistent.discard(reference)
            if not clean:
                return False
            backend = self._get_backend()
            if backend is not None and self._save_native(backend, reference, clean):
                self._persistent.add(reference)
                return True
            return False

    def delete(self, reference: str) -> None:
        with self._lock:
            # A failed vault deletion must never reload the session in this run.
            self._sessions[reference] = {}
            self._persistent.discard(reference)
            backend = self._get_backend()
            if backend is not None:
                for service in (self.service, *self.legacy_services):
                    try:
                        backend.delete_password(service, reference)
                    except Exception:
                        pass

    def status(self, reference: str) -> str:
        with self._lock:
            if reference in self._persistent:
                return "saved"
            if reference in self._sessions:
                return "session" if self._sessions[reference] else "missing"
            return "unknown"
