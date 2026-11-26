"""Word PDF export through COM, with a fake win32com (the real one only exists on Windows)."""

import sys
import types

import pytest

from src import resume


class FakeDoc:
    def __init__(self, log):
        self.log = log

    def ExportAsFixedFormat(self, path, fmt):
        self.log.append(("export", path, fmt))
        open(path, "wb").close()

    def Close(self, save):
        self.log.append(("close", save))


class FakeWord:
    def __init__(self, log, fail_open):
        self.log, self.fail_open = log, fail_open
        self.Documents = types.SimpleNamespace(Open=self.open)

    def open(self, path, *args):
        self.log.append(("open", path))
        if self.fail_open:
            raise AttributeError("Open.SaveAs")
        return FakeDoc(self.log)

    def Quit(self, *args):
        self.log.append(("quit",))


@pytest.fixture
def fake_com(monkeypatch):
    log, instances = [], []

    def dispatch_ex(progid):
        w = FakeWord(log, fail_open=not instances)  # the first instance is broken
        instances.append(w)
        return w

    client = types.ModuleType("win32com.client")
    client.DispatchEx = dispatch_ex
    pkg = types.ModuleType("win32com")
    pkg.client = client
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None
    monkeypatch.setitem(sys.modules, "win32com", pkg)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(resume._Word, "app", None)
    return log, instances


def test_word_instance_is_reused_and_retried_once(fake_com, tmp_path):
    log, instances = fake_com
    (tmp_path / "a.docx").write_bytes(b"x")
    (tmp_path / "b.docx").write_bytes(b"x")
    out = resume.docx_to_pdf(tmp_path / "a.docx", tmp_path / "a.pdf")
    assert out == (tmp_path / "a.pdf").resolve()
    assert len(instances) == 2 and ("quit",) in log  # broken instance quit, fresh one used
    resume.docx_to_pdf(tmp_path / "b.docx", tmp_path / "b.pdf")
    assert len(instances) == 2  # same instance for the next file
    assert [e[0] for e in log].count("export") == 2


def test_word_error_is_reported_not_hidden(fake_com, tmp_path, monkeypatch):
    (tmp_path / "a.docx").write_bytes(b"x")
    monkeypatch.setattr(FakeWord, "open", lambda self, *a: (_ for _ in ()).throw(RuntimeError("file locked")))
    with pytest.raises(RuntimeError, match="Word could not convert a.docx to PDF: file locked"):
        resume.docx_to_pdf(tmp_path / "a.docx", tmp_path / "a.pdf")


def test_word_opens_a_copy_in_a_short_temp_folder(fake_com, tmp_path):
    # Xperteez, Nov 26 2026: Word can't open a path of 260+ characters, and a long job title in the
    # folder and file names reached it. Word only ever sees a copy in a fresh temp folder.
    log, _ = fake_com
    folder = tmp_path / " ".join(["Long Job Title"] * 8)
    folder.mkdir()
    (folder / "Letter.docx").write_bytes(b"x")
    out = resume.docx_to_pdf(folder / "Letter.docx", folder / "Letter.pdf")
    assert out.exists() and out.parent == folder.resolve()
    opened = [e[1] for e in log if e[0] == "open"]
    assert opened and all(folder.name not in p and len(p) < len(str(folder)) for p in opened)


def test_locked_docx_says_word_has_it_open(tmp_path):
    target = tmp_path / "Jake Resume.docx"
    (tmp_path / "~$ke Resume.docx").write_text("owner")

    class Locked:
        def save(self, path):
            raise PermissionError(13, "Permission denied", path)

    with pytest.raises(RuntimeError, match="Word has it open"):
        resume._save_docx(Locked(), target)
