"""pyxpo-storage: the synchronous key-value store (react-native-mmkv shape plus AsyncStorage names)."""
import json
import sqlite3
import threading

import pytest

from pyxpo import App, Button, LocalChannel, Text, View, component, use_state
from pyxpo.renderers.mock import MockRenderer

import pyxpo_storage as ps
from pyxpo_storage import Storage


@pytest.fixture
def s(tmp_path):
    return Storage(id="t", path=str(tmp_path))


def test_types_round_trip_and_survive_reopen(s, tmp_path):
    s.set("str", "héllo")
    s.set("int", 42)
    s.set("float", 1.5)
    s.set("bool", False)
    s.set("buf", b"\x00\xff")
    ps._backends.clear()  # a fresh process: read from disk
    t = Storage(id="t", path=str(tmp_path))
    assert t.get_string("str") == "héllo"
    assert t.get_number("int") == 42 and isinstance(t.get_number("int"), int)
    assert t.get_number("float") == 1.5
    assert t.get_boolean("bool") is False
    assert t.get_buffer("buf") == b"\x00\xff"
    assert sorted(t.get_all_keys()) == ["bool", "buf", "float", "int", "str"]


def test_wrong_type_reads_none_and_bad_values_raise(s):
    s.set("n", 1)
    assert s.get_string("n") is None and s.get_boolean("n") is None and s.get_number("missing") is None
    s.set("b", True)
    assert s.get_number("b") is None  # a bool is not a number here
    with pytest.raises(TypeError, match="delete"):
        s.set("x", None)
    with pytest.raises(TypeError, match="set_object"):
        s.set("x", {"a": 1})
    with pytest.raises(ValueError):
        s.set("x", float("nan"))
    with pytest.raises(TypeError):
        s.set("", "v")


def test_delete_contains_clear_all(s):
    s.set("a", "1")
    s.set("b", "2")
    assert s.contains("a")
    s.delete("a")
    s.delete("a")  # no-op
    assert not s.contains("a") and s.get_all_keys() == ["b"]
    s.clear_all()
    assert s.get_all_keys() == []


def test_instances_share_by_id_and_are_separate_across_ids(tmp_path):
    a, b, c = Storage(id="x", path=str(tmp_path)), Storage({"id": "x", "path": str(tmp_path)}), Storage(id="y", path=str(tmp_path))
    a.set("k", "v")
    assert b.get_string("k") == "v" and c.get_string("k") is None
    assert a.path.endswith("x.sqlite")


def test_bad_config():
    with pytest.raises(ValueError):
        Storage(id="../evil")
    with pytest.raises(ValueError, match="secure-store"):
        Storage({"encryptionKey": "k"})
    with pytest.raises(ValueError, match="unknown"):
        Storage({"mode": 1})


def test_listeners(s):
    seen = []
    sub = s.add_on_value_changed_listener(seen.append)
    s.set("a", "1")
    s.delete("a")
    s.delete("a")  # nothing removed: no event
    s.set("b", "1")
    s.clear_all()
    sub.remove()
    s.set("c", "1")
    assert seen == ["a", "a", "b", "b"]


def test_listener_error_does_not_break_write(s, capsys):
    s.add_on_value_changed_listener(lambda k: 1 / 0)
    s.set("a", "1")
    assert s.get_string("a") == "1" and "ZeroDivisionError" in capsys.readouterr().err


def test_async_storage_names(s):
    s.set_item("a", "1")
    s.setItem("b", "2")
    assert s.get_item("a") == "1" and s.getItem("b") == "2"
    with pytest.raises(TypeError):
        s.set_item("a", 5)
    s.multi_set([["c", "3"], ["d", "4"]])
    assert s.multi_get(["c", "d", "zz"]) == [["c", "3"], ["d", "4"], ["zz", None]]
    s.multi_remove(["c", "d"])
    assert s.getAllKeys() == ["a", "b"]
    s.remove_item("a")
    s.clear()
    assert s.get_all_keys() == []


def test_merge_item_is_deep(s):
    s.set_item("u", json.dumps({"name": "A", "prefs": {"dark": True, "lang": "en"}}))
    s.merge_item("u", json.dumps({"prefs": {"lang": "hi"}, "age": 3}))
    assert s.get_object("u") == {"name": "A", "prefs": {"dark": True, "lang": "hi"}, "age": 3}
    s.multi_merge([["new", '{"a": 1}'], ["new", '{"b": 2}']])
    assert s.get_object("new") == {"a": 1, "b": 2}
    with pytest.raises(ValueError):
        s.merge_item("u", "not json")


def test_objects(s):
    s.set_object("o", {"a": [1, "२"]})
    assert s.get_object("o") == {"a": [1, "२"]} and s.get_string("o") == '{"a":[1,"२"]}'
    s.set("bad", "{")
    assert s.get_object("bad") is None


def test_corrupt_file_is_moved_aside(tmp_path, capsys):
    (tmp_path / "c.sqlite").write_bytes(b"this is not a database" * 100)
    s = Storage(id="c", path=str(tmp_path))
    s.set("a", "1")
    assert s.get_string("a") == "1"
    assert (tmp_path / "c.sqlite.corrupt").exists() and "unreadable" in capsys.readouterr().err


def test_threads_do_not_lose_writes(s):
    def work(n):
        for i in range(50):
            s.set("t%d-%d" % (n, i), i)
    ts = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(s.get_all_keys()) == 200
    rows = sqlite3.connect(s.path).execute("SELECT count(*) FROM kv").fetchone()[0]
    assert rows == 200


def test_size_and_trim(s):
    for i in range(100):
        s.set("k%d" % i, "x" * 1000)
    s.clear_all()
    s.trim()
    assert s.size > 0


def test_default_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("PYXPO_STORAGE_DIR", str(tmp_path))
    assert ps.default_directory() == tmp_path
    monkeypatch.delenv("PYXPO_STORAGE_DIR")
    monkeypatch.setattr(ps.sys, "platform", "ios")
    monkeypatch.setenv("HOME", "/h")
    assert str(ps.default_directory()) == "/h/Library/Application Support/pyxpo-storage"
    monkeypatch.setattr(ps.sys, "platform", "android")
    assert str(ps.default_directory()) == "/h/pyxpo-storage"
    # The Mac Catalyst app: Python reports "darwin", the iOS runtime sets PYXPO_TARGET.
    monkeypatch.setattr(ps.sys, "platform", "darwin")
    monkeypatch.setenv("PYXPO_TARGET", "ios")
    assert str(ps.default_directory()) == "/h/Library/Application Support/pyxpo-storage"


def _mount(root):
    ch = LocalChannel()
    r = MockRenderer(ch)
    App(root, ch, None).start()
    return r


def test_hooks_rerender_on_change_from_anywhere(s):
    @component
    def C():
        name, set_name = ps.use_storage_string("name", s)
        n, set_n = ps.useStorageNumber("n", s)
        o, _ = ps.use_storage_object("o", s)
        return View(Text("name=%s n=%s o=%s" % (name, n, o)),
                    Button(title="inc", on_press=lambda: set_n(lambda old: (old or 0) + 1)),
                    Button(title="clear", on_press=lambda: set_name(None)))

    r = _mount(C)
    assert r.texts()[0] == "name=None n=None o=None"
    s.set("name", "A")
    s.set_object("o", {"x": 1})
    assert r.texts()[0] == "name=A n=None o={'x': 1}"
    r.press(r.find_text("inc"))
    r.press(r.find_text("inc"))
    assert r.texts()[0].startswith("name=A n=2") and s.get_number("n") == 2
    r.press(r.find_text("clear"))
    assert not s.contains("name") and r.texts()[0].startswith("name=None")


def test_hook_setter_type_checked_and_unsubscribes(s):
    holder = {}

    @component
    def Reader():
        v, set_v = ps.use_storage_boolean("flag", s)
        holder["set"] = set_v
        return Text("flag=%s" % v)

    @component
    def Root():
        show, set_show = use_state(True)
        return View(Reader() if show else None, Button(title="hide", on_press=lambda: set_show(False)))

    r = _mount(Root)
    holder["set"](True)
    assert r.texts()[0] == "flag=True"
    with pytest.raises(TypeError):
        holder["set"]("yes")
    r.press(r.find_text("hide"))
    assert s._backend.listeners == []


def test_listener_hook(s):
    seen = []

    @component
    def C():
        ps.use_storage_listener(seen.append, s)
        return Text("x")

    _mount(C)
    s.set("a", 1)
    assert seen == ["a"]
