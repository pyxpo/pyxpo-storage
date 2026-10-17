"""Fast synchronous key-value storage: the react-native-mmkv shape, plus the AsyncStorage method names.

    from pyxpo_storage import storage

    storage.set("user.name", "Asha")
    storage.get_string("user.name")       # "Asha"
    storage.set_item("token", "abc")      # AsyncStorage names work too, without `await`

Values are strings, numbers, booleans or bytes. They live in a SQLite file in the app's private data
folder and in memory, so reads never touch the disk and every write is on disk when `set` returns.
Nothing is encrypted: keep tokens and passwords in `pyxpo-secure-store`.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

__version__ = "0.1.0a1"

__all__ = [
    "Storage", "storage", "default_directory",
    "use_storage_string", "use_storage_number", "use_storage_boolean", "use_storage_buffer", "use_storage_object",
    "use_storage_listener",
    "useStorageString", "useStorageNumber", "useStorageBoolean", "useStorageBuffer", "useStorageObject",
    "useStorageListener",
]

Value = Union[str, int, float, bool, bytes]

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_STRING, _NUMBER, _BOOL, _BYTES = "s", "n", "b", "x"


def _ios_container() -> bool:
    """iOS, or the iOS shell built for Mac (Catalyst Python reports sys.platform "darwin"): HOME is laid out
    like an iOS app container."""
    return sys.platform == "ios" or os.environ.get("PYXPO_TARGET") == "ios"


def default_directory() -> Path:
    """Where storage files live: the app's private data folder (backed up with the app, removed on uninstall).

    iOS: `Library/Application Support/pyxpo-storage`; Android: `files/pyxpo-storage`. On the desktop (tests,
    console preview) it is `.pyxpo-data/storage` in the working folder. `PYXPO_STORAGE_DIR` overrides all three."""
    env = os.environ.get("PYXPO_STORAGE_DIR")
    if env:
        return Path(env)
    home = Path(os.path.expanduser("~"))
    if _ios_container():
        return home / "Library" / "Application Support" / "pyxpo-storage"
    if sys.platform == "android":
        return home / "pyxpo-storage"
    return Path.cwd() / ".pyxpo-data" / "storage"


def _kind(value: Any) -> Tuple[str, Any]:
    if isinstance(value, bool):
        return _BOOL, value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("storage cannot keep %r; store numbers that are finite" % value)
        return _NUMBER, value
    if isinstance(value, str):
        return _STRING, value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _BYTES, bytes(value)
    if value is None:
        raise TypeError("storage.set got None; use delete(key) to remove a value")
    raise TypeError("storage keeps str, int, float, bool or bytes, got %s; use set_object for dicts and lists"
                    % type(value).__name__)


def _key(key: Any) -> str:
    if not isinstance(key, str) or not key:
        raise TypeError("storage keys must be non-empty strings, got %r" % (key,))
    return key


def _decode(kind: str, value: Any) -> Any:
    if kind == _BOOL:
        return bool(value)
    if kind == _BYTES:
        return bytes(value)
    return value


def _merge(old: Any, new: Any) -> Any:
    """AsyncStorage.mergeItem: objects merge key by key, nested objects too; anything else is replaced."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(old)
        for k, v in new.items():
            out[k] = _merge(out.get(k), v)
        return out
    return new


class _Backend:
    """One storage file, shared by every `Storage` object opened on it. All access holds `lock`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.db: Optional[sqlite3.Connection] = None
        self.data: Dict[str, Tuple[str, Any]] = {}
        self.listeners: List[Callable[[str], Any]] = []

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL, value) WITHOUT ROWID")
        self.data = {k: (kind, _decode(kind, v)) for k, kind, v in db.execute("SELECT key, kind, value FROM kv")}
        return db

    def open(self) -> sqlite3.Connection:
        if self.db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.db = self._connect()
            except sqlite3.DatabaseError as e:
                # A damaged file must not stop the app from starting: keep it aside for inspection and start empty.
                aside = self.path.with_name(self.path.name + ".corrupt")
                for suffix in ("", "-wal", "-shm"):
                    f = Path(str(self.path) + suffix)
                    if f.exists():
                        os.replace(str(f), str(aside) + suffix)
                print("pyxpo-storage: %s was unreadable (%s); moved it to %s and started empty" % (self.path, e, aside),
                      file=sys.stderr)
                self.db = self._connect()
        return self.db

    def write(self, sets: Sequence[Tuple[str, str, Any]], deletes: Sequence[str]) -> List[str]:
        """Applies the changes in one transaction and returns the keys that changed."""
        with self.lock:
            db = self.open()
            deletes = [k for k in dict.fromkeys(deletes) if k in self.data]
            if not sets and not deletes:
                return []
            db.execute("BEGIN")
            try:
                db.executemany("INSERT OR REPLACE INTO kv (key, kind, value) VALUES (?, ?, ?)", sets)
                db.executemany("DELETE FROM kv WHERE key = ?", [(k,) for k in deletes])
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            for k, kind, v in sets:
                self.data[k] = (kind, v)
            for k in deletes:
                self.data.pop(k, None)
            changed = list(dict.fromkeys([k for k, _, _ in sets] + deletes))
            listeners = list(self.listeners)
        for k in changed:
            for fn in listeners:
                try:
                    fn(k)
                except Exception as e:  # noqa: BLE001 - one bad listener must not break the others or the write
                    print("pyxpo-storage: value-changed listener failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return changed

    def get(self, key: str) -> Optional[Tuple[str, Any]]:
        with self.lock:
            self.open()
            return self.data.get(key)


_backends: Dict[str, _Backend] = {}
_backends_lock = threading.Lock()


def _backend_for(path: Path) -> _Backend:
    key = os.path.realpath(str(path))
    with _backends_lock:
        b = _backends.get(key)
        if b is None:
            b = _backends[key] = _Backend(Path(key))
        return b


class _Listener:
    def __init__(self, backend: _Backend, fn: Callable[[str], Any]) -> None:
        self._backend, self._fn = backend, fn

    def remove(self) -> None:
        with self._backend.lock:
            if self._fn in self._backend.listeners:
                self._backend.listeners.remove(self._fn)


class Storage:
    """A key-value store, like `new MMKV()`. `Storage()` is the app's default store; `Storage(id="user-42")`
    is a separate one (its own file), and `path=` puts the file in another folder. Objects with the same
    `id` and folder share their data and listeners. A config dict also works: `Storage({"id": "user-42"})`.

    Reads come from memory; writes are synchronous and on disk when the call returns."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, *, id: str = "default", path: Optional[str] = None) -> None:
        if config is not None:
            if not isinstance(config, dict):
                raise TypeError("Storage(config) takes a dict such as {'id': 'user-42'}, got %r" % (config,))
            if config.get("encryptionKey") or config.get("encryption_key"):
                raise ValueError("pyxpo-storage does not encrypt; keep secrets in pyxpo-secure-store")
            unknown = set(config) - {"id", "path", "encryptionKey", "encryption_key"}
            if unknown:
                raise ValueError("unknown Storage option(s): %s (use id and path)" % ", ".join(sorted(unknown)))
            id, path = config.get("id", id), config.get("path", path)
        if not isinstance(id, str) or not _ID_RE.match(id):
            raise ValueError("storage id must be 1-120 letters, digits, '.', '_' or '-', got %r" % (id,))
        self.id = id
        self._dir = Path(path) if path else None
        self._b: Optional[_Backend] = None

    @property
    def _backend(self) -> _Backend:
        if self._b is None:
            self._b = _backend_for((self._dir or default_directory()) / (self.id + ".sqlite"))
        return self._b

    @property
    def path(self) -> str:
        """The storage file."""
        return str(self._backend.path)

    def __repr__(self) -> str:
        return "Storage(id=%r)" % self.id

    # react-native-mmkv

    def set(self, key: str, value: Value) -> None:
        """Stores a str, int, float, bool or bytes value under `key`, replacing what was there."""
        kind, v = _kind(value)
        self._backend.write([(_key(key), kind, v)], [])

    def _typed(self, key: str, kind: str) -> Any:
        hit = self._backend.get(_key(key))
        return hit[1] if hit is not None and hit[0] == kind else None

    def get_string(self, key: str) -> Optional[str]:
        """The string under `key`, or None when there is none (or the value is not a string)."""
        return self._typed(key, _STRING)

    def get_number(self, key: str) -> Optional[Union[int, float]]:
        """The number under `key` (an int stays an int), or None."""
        return self._typed(key, _NUMBER)

    def get_boolean(self, key: str) -> Optional[bool]:
        return self._typed(key, _BOOL)

    def get_buffer(self, key: str) -> Optional[bytes]:
        return self._typed(key, _BYTES)

    def contains(self, key: str) -> bool:
        return self._backend.get(_key(key)) is not None

    def delete(self, key: str) -> None:
        """Removes `key`. Removing a key that is not there does nothing."""
        self._backend.write([], [_key(key)])

    remove = delete

    def get_all_keys(self) -> List[str]:
        b = self._backend
        with b.lock:
            b.open()
            return list(b.data)

    def clear_all(self) -> None:
        """Removes every key of this store. Listeners hear about each removed key."""
        b = self._backend
        with b.lock:
            b.open()
            keys = list(b.data)
        b.write([], keys)

    @property
    def size(self) -> int:
        """Bytes the store takes on disk."""
        b = self._backend
        with b.lock:
            b.open()
            return sum(os.path.getsize(str(b.path) + s) for s in ("", "-wal") if os.path.exists(str(b.path) + s))

    def trim(self) -> None:
        """Gives disk space of removed values back to the system."""
        b = self._backend
        with b.lock:
            db = b.open()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("VACUUM")

    def add_on_value_changed_listener(self, fn: Callable[[str], Any]) -> _Listener:
        """Calls `fn(key)` after a key is set or removed, from any `Storage` object on this store.
        Returns a subscription; call its `remove()` to stop listening."""
        if not callable(fn):
            raise TypeError("listener must be callable")
        b = self._backend
        with b.lock:
            b.listeners.append(fn)
        return _Listener(b, fn)

    # JSON values (what useMMKVObject stores)

    def set_object(self, key: str, value: Any) -> None:
        """Stores a JSON-compatible value (dict, list, ...) as a JSON string."""
        self.set(key, json.dumps(value, separators=(",", ":"), ensure_ascii=False))

    def get_object(self, key: str) -> Any:
        """The JSON value under `key`, or None when there is none or it is not valid JSON."""
        raw = self.get_string(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    # AsyncStorage / localStorage names (synchronous: no await)

    def get_item(self, key: str) -> Optional[str]:
        return self.get_string(key)

    def set_item(self, key: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("set_item stores strings (as AsyncStorage does); use set() for numbers, booleans and bytes "
                            "or set_object() for dicts and lists")
        self.set(key, value)

    def remove_item(self, key: str) -> None:
        self.delete(key)

    def merge_item(self, key: str, value: str) -> None:
        """Merges a JSON object string into the JSON object stored under `key` (nested objects merge too)."""
        self.multi_merge([(key, value)])

    def multi_get(self, keys: Iterable[str]) -> List[List[Optional[str]]]:
        """`[[key, value or None], ...]` in the order asked."""
        return [[k, self.get_string(k)] for k in keys]

    def multi_set(self, pairs: Iterable[Sequence[str]]) -> None:
        """Sets `[[key, value], ...]` in one transaction."""
        rows = []
        for k, v in pairs:
            if not isinstance(v, str):
                raise TypeError("multi_set stores strings, got %s for %r" % (type(v).__name__, k))
            rows.append((_key(k), _STRING, v))
        self._backend.write(rows, [])

    def multi_remove(self, keys: Iterable[str]) -> None:
        self._backend.write([], [_key(k) for k in keys])

    def multi_merge(self, pairs: Iterable[Sequence[str]]) -> None:
        b = self._backend
        with b.lock:  # read and write under one lock so a concurrent write cannot be lost
            pending: Dict[str, Any] = {}
            for k, v in pairs:
                if not isinstance(v, str):
                    raise TypeError("merge_item takes a JSON string, got %s for %r" % (type(v).__name__, k))
                old = pending[k] if k in pending else self.get_object(k)
                pending[_key(k)] = _merge(old, json.loads(v))
            b.write([(k, _STRING, json.dumps(v, separators=(",", ":"), ensure_ascii=False)) for k, v in pending.items()], [])

    def clear(self) -> None:
        self.clear_all()


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w[:1].upper() + w[1:] for w in rest)


for _name, _val in list(vars(Storage).items()):
    if not _name.startswith("_") and "_" in _name and (callable(_val) or isinstance(_val, property)):
        setattr(Storage, _camel(_name), _val)

storage = Storage()
"""The app's default store, like `new MMKV()` at module level. Opens its file on first use."""


# hooks (react-native-mmkv's useMMKVString and friends)

def _hook(key: str, instance: Optional[Storage], read: Callable[[Storage, str], Any],
          write: Callable[[Storage, str, Any], None]):
    from pyxpo import use_callback, use_sync_external_store

    s = instance if instance is not None else storage
    b = s._backend

    def subscribe(on_change: Callable[[], None]) -> Callable[[], None]:
        sub = s.add_on_value_changed_listener(lambda k: on_change() if k == key else None)
        return sub.remove

    value = use_sync_external_store(use_callback(subscribe, [b, key]), lambda: read(s, key))

    def set_value(new: Any) -> None:
        if callable(new):
            new = new(read(s, key))
        if new is None:
            s.delete(key)
        else:
            write(s, key, new)

    return value, use_callback(set_value, [b, key])


def _checked(kind: type, label: str) -> Callable[[Storage, str, Any], None]:
    def write(s: Storage, key: str, v: Any) -> None:
        if not isinstance(v, kind) or (kind is not bool and isinstance(v, bool)):
            raise TypeError("%s setter takes %s or None, got %s" % (label, kind.__name__ if isinstance(kind, type)
                                                                    else "a number", type(v).__name__))
        s.set(key, v)
    return write


def use_storage_string(key: str, instance: Optional[Storage] = None):
    """`(value, set_value)` for a string key; re-renders when the key changes anywhere. `set_value(None)` deletes it,
    `set_value(lambda old: ...)` updates from the current value."""
    return _hook(key, instance, Storage.get_string, _checked(str, "use_storage_string"))


def use_storage_number(key: str, instance: Optional[Storage] = None):
    return _hook(key, instance, Storage.get_number, _checked((int, float), "use_storage_number"))  # type: ignore[arg-type]


def use_storage_boolean(key: str, instance: Optional[Storage] = None):
    return _hook(key, instance, Storage.get_boolean, _checked(bool, "use_storage_boolean"))


def use_storage_buffer(key: str, instance: Optional[Storage] = None):
    return _hook(key, instance, Storage.get_buffer, _checked(bytes, "use_storage_buffer"))


def use_storage_object(key: str, instance: Optional[Storage] = None):
    """`(value, set_value)` for a JSON value stored with `set_object`."""
    return _hook(key, instance, Storage.get_object, Storage.set_object)


def use_storage_listener(fn: Callable[[str], Any], instance: Optional[Storage] = None) -> None:
    """Calls `fn(key)` for every change while the component is mounted (useMMKVListener)."""
    from pyxpo import use_effect, use_ref

    s = instance if instance is not None else storage
    latest = use_ref(fn)
    latest.current = fn

    def setup() -> Callable[[], None]:
        return s.add_on_value_changed_listener(lambda k: latest.current(k)).remove

    use_effect(setup, [s._backend])


useStorageString = use_storage_string
useStorageNumber = use_storage_number
useStorageBoolean = use_storage_boolean
useStorageBuffer = use_storage_buffer
useStorageObject = use_storage_object
useStorageListener = use_storage_listener
