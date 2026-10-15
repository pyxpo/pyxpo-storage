# pyxpo-storage

Fast synchronous key-value storage for pyxpo apps. The API follows react-native-mmkv, and the
AsyncStorage method names work too (without `await`).

This is an optional [pyxpo](https://github.com/ivishalchaubey/pyxpo) module. It is pure Python: it adds
no Swift or Kotlin code and no permissions.

## Install

```bash
pip install pyxpo-storage
```

Then link it into your app in `pyproject.toml`:

```toml
[tool.pyxpo]
modules = ["storage"]
```

## Use

```python
from pyxpo_storage import Storage, storage, use_storage_string

storage.set("user.name", "Asha")
storage.get_string("user.name")        # "Asha"
storage.set("launches", 3)
storage.get_number("launches")         # 3
storage.set_object("prefs", {"dark": True})
storage.contains("user.name")          # True
storage.delete("user.name")

# AsyncStorage names, synchronous
storage.set_item("token", "abc")
storage.get_item("token")              # "abc"
storage.multi_set([["a", "1"], ["b", "2"]])

# Separate stores
cache = Storage(id="cache")

# Hooks re-render the component when the value changes
name, set_name = use_storage_string("user.name")
```

camelCase names (`getString`, `setItem`, `useStorageString`, ...) are available for people coming from
React Native.

Values are strings, numbers, booleans or bytes. They live in a SQLite file in the app's private data
folder and in memory, so reads never touch the disk and every write is on disk when `set` returns.

Nothing is encrypted. Keep tokens and passwords in `pyxpo-secure-store`.

## What is in the package

- `pyxpo_storage/__init__.py`: the Python API.
- `pyxpo_storage/pyxpo-module.json`: autolink metadata.
