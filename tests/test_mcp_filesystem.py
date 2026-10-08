import os

import pytest

import server


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "todo.md").write_text("buy milk\nCall Alice about the budget\n")
    (tmp_path / "README.md").write_text("# Shared folder\nHello\n")
    (tmp_path / "image.bin").write_bytes(b"\x00\xff\x00budget")
    monkeypatch.setattr(server, "ROOT", tmp_path.resolve())
    return tmp_path


def test_list_dir_top(root):
    assert server.list_dir(".").splitlines() == [
        "dir  notes/",
        "file notes/todo.md (37 bytes)",
        "file image.bin (9 bytes)",
        "file README.md (22 bytes)",
    ]


def test_list_dir_depth_1(root):
    assert server.list_dir(".", depth=1).splitlines()[0:2] == ["dir  notes/", "file image.bin (9 bytes)"]


def test_list_dir_sub(root):
    assert "file notes/todo.md" in server.list_dir("notes")


def test_read_file(root):
    assert server.read_file("notes/todo.md").startswith("buy milk")


def test_read_file_cut_off(root, monkeypatch):
    monkeypatch.setattr(server, "MAX_READ_CHARS", 5)
    assert server.read_file("README.md").startswith("# Sha\n\n[... cut off")


def test_search_by_content_and_name(root):
    assert server.search_files("BUDGET") == "notes/todo.md:2: Call Alice about the budget"
    assert server.search_files("readme") == "README.md: name"
    assert server.search_files("nothing-here") == "no matches"


@pytest.mark.parametrize("path", ["..", "../etc/passwd", "notes/../../x", "/../../etc"])
def test_paths_cannot_escape_root(root, path):
    with pytest.raises(ValueError, match="outside"):
        server.resolve(path)


def test_absolute_path_is_inside_root(root):
    assert server.resolve("/notes") == root.resolve() / "notes"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need admin rights on Windows")
def test_symlink_out_of_root_is_blocked(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_text("secret")
    (root / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        server.read_file("link/secret.txt")
    assert "secret" not in server.search_files("secret")


def test_read_file_finds_unique_name_without_extension(root):
    out = server.read_file("readme")
    assert out.startswith("[readme not found; read README.md instead]\n# Shared folder")


def test_read_file_ambiguous_name_suggests(root):
    (root / "notes" / "README.txt").write_text("other")
    with pytest.raises(ValueError, match="Did you mean: README.md, notes/README.txt"):
        server.read_file("readme")
