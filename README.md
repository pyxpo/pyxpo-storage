# pyxpo-storage

Fast, synchronous key-value storage for [pyxpo](https://github.com/pyxpo/pyxpo) apps written in Python. The API follows
[react-native-mmkv](https://github.com/mrousavy/react-native-mmkv), and the AsyncStorage method names (`set_item`,
`get_item`, `multi_get`, `merge_item`) work too, without `await`. Reads come from memory, and every write is on disk
when `set` returns. It is plain Python on top of SQLite, so there is no native code to link.

<p align="center">
  <img src="https://raw.githubusercontent.com/pyxpo/pyxpo-storage/main/docs/images/hero.png" width="820" alt="Stored values read back on Android and iOS: a string, a launch counter and an object">
</p>

```python
from pyxpo_storage import storage

storage.set("user.name", "Asha")
storage.get_string("user.name")        # "Asha"
```

## Features

- **Synchronous:** no `await`. `storage.set(...)` and `storage.get_string(...)` just work.
- **Typed values:** str, int, float, bool and bytes, plus JSON objects through `set_object`.
- **Durable:** every write is committed before the call returns. Uses a SQLite file with WAL.
- **React hooks:** `use_storage_string`, `use_storage_number`, `use_storage_boolean`, `use_storage_buffer`,
  `use_storage_object` re-render when the key changes anywhere, and `use_storage_listener` hears every change.
- **Several stores:** `Storage(id="user-42")` is a separate file, handy per user.
- **AsyncStorage names:** `set_item`, `get_item`, `remove_item`, `merge_item`, `multi_get`, `multi_set`, `multi_remove`, `multi_merge`, `clear`.
- **Recovers from damage:** an unreadable file is moved aside as `.corrupt` and the app starts empty.
- **Typed:** ships `py.typed`. camelCase names (`getString`, `setObject`) also work.

> Nothing is encrypted. Keep tokens and passwords in `pyxpo-secure-store`.

## Contents

| If you are... | Start here |
| --- | --- |
| Saving a setting | [Quick start](#quick-start) |
| Binding a value to the UI | [Hooks](#hooks) |
| Storing a dict or list | [Objects](#objects) |
| Coming from AsyncStorage | [AsyncStorage names](#asyncstorage-names) |
| One store per user | [Several stores](#several-stores) |
| Exact signatures | [API reference](#api-reference) · [Errors](#errors) |
| Seeing it in a real app | [Recipe: settings screen](#recipe-settings-screen) |
| Stuck | [Testing](#testing) · [Troubleshooting](#troubleshooting) · [FAQ](#faq) |

## Platform support

| Target | What works |
| --- | --- |
| Android, API 24+ | Everything. File in `files/pyxpo-storage`. |
| iOS 15+ | Everything. File in `Library/Application Support/pyxpo-storage`. |
| Desktop window and tests | Everything. File in `.pyxpo-data/storage` in the working folder. |
| Web page | The same Python code runs on the page's own file system. Not verified to survive a reload, so keep important data on a server too. |

Requires Python 3.9+ and `pyxpo>=0.1.0a1`. Set `PYXPO_STORAGE_DIR` to move the files (useful in tests).

## Install

```sh
pip install pyxpo-storage
```

```toml
[tool.pyxpo]
modules = ["storage"]
```

Rebuild the app. There are no plugin options, no permissions and no native code.

## Quick start

```python
from pyxpo import Button, Text, View, component
from pyxpo_storage import storage, use_storage_number, use_storage_string


@component
def Home():
    name, set_name = use_storage_string("user.name")
    launches, set_launches = use_storage_number("launches")

    return View(
        Text("Hello, %s" % (name or "stranger")),
        Text("Opened %d times" % (launches or 0)),
        Button("Set name", lambda: set_name("Asha")),
        Button("Count", lambda: set_launches(lambda old: (old or 0) + 1)),
        Button("Forget me", lambda: storage.clear_all()),
    )
```

> **Tip:** The hooks re-render the component when the key changes from anywhere, including other screens and
> `storage.set(...)` calls. `set_value(None)` deletes the key, and `set_value(lambda old: ...)` updates from the current value.

<p align="center">
  <img src="https://raw.githubusercontent.com/pyxpo/pyxpo-storage/main/docs/images/values.png" width="720" alt="The stored name, launch count and object, with Set name, Launches +1 and Delete name buttons, on Android and iOS">
</p>

## Values

```python
storage.set("name", "Asha")           # str
storage.set("launches", 3)            # int stays an int
storage.set("ratio", 0.5)             # float (finite only)
storage.set("dark", True)             # bool
storage.set("blob", b"\x00\x01")      # bytes

storage.get_string("name")            # None when missing or another type
storage.get_number("launches")
storage.get_boolean("dark")
storage.get_buffer("blob")
storage.contains("name")
storage.delete("name")                # a missing key is fine
storage.get_all_keys()
storage.clear_all()
```

A getter returns `None` when the key is missing or holds another type. `set(key, None)` raises `TypeError`: use
`delete(key)`. NaN and infinity raise `ValueError`.

## Objects

```python
storage.set_object("prefs", {"dark": True, "font": 16})
storage.get_object("prefs")           # {"dark": True, "font": 16}
```

Objects are stored as JSON strings. `get_object` returns `None` when the key is missing or not valid JSON.

## Hooks

| Hook | Value type |
| --- | --- |
| `use_storage_string(key)` | `str` or `None` |
| `use_storage_number(key)` | `int`, `float` or `None` |
| `use_storage_boolean(key)` | `bool` or `None` |
| `use_storage_buffer(key)` | `bytes` or `None` |
| `use_storage_object(key)` | any JSON value, or `None` |
| `use_storage_listener(fn)` | calls `fn(key)` for every change while mounted |

All take an optional `instance` (another `Storage`). Each returns `(value, set_value)`. A setter of the wrong type raises
`TypeError`.

## AsyncStorage names

```python
storage.set_item("token", "abc")          # strings only
storage.get_item("token")
storage.merge_item("prefs", '{"font": 18}')   # merges JSON objects, nested too
storage.multi_get(["a", "b"])             # [["a", "1"], ["b", None]]
storage.multi_set([["a", "1"], ["b", "2"]])  # one transaction
storage.multi_remove(["a", "b"])
storage.clear()
```

## Several stores

```python
from pyxpo_storage import Storage

user = Storage(id="user-42")              # its own file
user.set("theme", "dark")
```

`id` is 1 to 120 letters, digits, `.`, `_` or `-`. Objects with the same `id` and folder share data and listeners. Pass
`path="/some/folder"` to put the file elsewhere. `Storage({"id": "user-42"})` also works, and
`encryptionKey` raises `ValueError`, because there is no encryption.

## Listeners and size

```python
sub = storage.add_on_value_changed_listener(lambda key: print("changed", key))
sub.remove()
storage.size       # bytes on disk
storage.trim()     # give the space of removed values back
```

## Errors

| Error | When | What to do |
| --- | --- | --- |
| `TypeError` | A key is not a non-empty string, a value is `None`, a dict or other unsupported type, `set_item` gets a non-string, or a hook setter gets the wrong type. | Use `set_object` for dicts and lists, `delete` for removal. |
| `ValueError` | NaN or infinity, a bad store `id`, an unknown option, or an `encryptionKey`. | Fix the argument. |
| A damaged file | The SQLite file cannot be read. | Nothing: it is moved to `<id>.sqlite.corrupt`, and the store starts empty. A message goes to stderr. |
| A listener that raises | Your callback has a bug. | The error is printed to stderr. Other listeners and the write still succeed. |

## Config

Set `PYXPO_STORAGE_DIR` to override where the files live. `default_directory()` returns the folder in use.

## Web and desktop

The desktop window and tests use `.pyxpo-data/storage` in the working folder. The web page runs the same Python code
against the page's own file system, so treat it as a convenience cache rather than permanent storage until you have
checked it for your host.

## Recipe: settings screen

```python
from pyxpo import Button, Switch, Text, View, component
from pyxpo_storage import use_storage_boolean, use_storage_object


@component
def Settings():
    dark, set_dark = use_storage_boolean("settings.dark")
    prof, set_prof = use_storage_object("profile")
    prof = prof or {"name": "", "font": 16}

    return View(
        Text("Dark mode"),
        Switch(value=bool(dark), on_value_change=set_dark),
        Text("Font size %d" % prof["font"]),
        Button("Bigger", lambda: set_prof(dict(prof, font=prof["font"] + 1))),
        Button("Reset", lambda: set_prof(None)),
    )
```

## Production checklist

- [ ] Secrets are in `pyxpo-secure-store`, not here.
- [ ] Per-user data uses `Storage(id=...)` and is cleared on sign-out (`clear_all()`).
- [ ] You keep values small. Large data belongs in `pyxpo-sqlite` or files.
- [ ] You do not rely on web persistence.
- [ ] Your tests set `PYXPO_STORAGE_DIR` to a temp folder.
- [ ] You handle `None` from every getter.

## Testing

Point the storage at a temp folder and use real storage, which is fast:

```python
import pytest

from pyxpo_storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(id="test", path=str(tmp_path))


def test_roundtrip(store):
    store.set("n", 3)
    store.set_object("o", {"a": [1, 2]})
    assert store.get_number("n") == 3
    assert store.get_object("o") == {"a": [1, 2]}
    assert store.get_string("n") is None


def test_listener(store):
    seen = []
    sub = store.add_on_value_changed_listener(seen.append)
    store.set("k", "v")
    store.delete("k")
    sub.remove()
    store.set("k", "w")
    assert seen == ["k", "k"]


def test_merge(store):
    store.set_item("p", '{"a": {"x": 1}}')
    store.merge_item("p", '{"a": {"y": 2}}')
    assert store.get_object("p") == {"a": {"x": 1, "y": 2}}
```

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `get_string` returns `None` for a number | Getters return `None` for another type. Use `get_number`. |
| `TypeError: storage keeps str, int, float, bool or bytes` | Use `set_object` for dicts and lists. |
| Tests share data | Set `PYXPO_STORAGE_DIR` or use `Storage(path=tmp_path)`. |
| `ValueError: ... does not encrypt` | Remove `encryptionKey`. Use `pyxpo-secure-store` for secrets. |
| A `.corrupt` file appeared | The store was unreadable. The app started empty and kept the old file for you. |
| A value changed but the screen did not | Use a hook (`use_storage_string`) instead of reading in render. |

## FAQ

**Is it async?** No. Reads and writes are synchronous and fast.

**Is it safe from several threads?** Yes, every access holds a lock.

**Can I store a list?** Yes, `set_object("items", [1, 2, 3])`.

**Does it survive an app update?** Yes. It is removed on uninstall, and backed up with the app.

**Is it encrypted?** No.

## API reference

### `Storage(config=None, *, id="default", path=None)` and `storage`

| Method | Notes |
| --- | --- |
| `set(key, value)` | str, int, float, bool or bytes. |
| `get_string`, `get_number`, `get_boolean`, `get_buffer` `(key)` | Value or `None`. |
| `set_object(key, value)` / `get_object(key)` | JSON values. |
| `contains(key)`, `delete(key)` (`remove`), `get_all_keys()`, `clear_all()` | |
| `size`, `trim()`, `path` | Disk size, compaction, file path. |
| `add_on_value_changed_listener(fn)` | Returns an object with `remove()`. |
| `get_item`, `set_item`, `remove_item`, `merge_item`, `multi_get`, `multi_set`, `multi_remove`, `multi_merge`, `clear` | AsyncStorage names. |

### Hooks and helpers

`use_storage_string`, `use_storage_number`, `use_storage_boolean`, `use_storage_buffer`, `use_storage_object`
`(key, instance=None)` return `(value, set_value)`. `use_storage_listener(fn, instance=None)` returns nothing.
`default_directory()` returns the folder in use. camelCase aliases exist for all of them.

## License

MIT
