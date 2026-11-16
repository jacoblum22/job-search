"""Word PDF export through COM, with a fake win32com (the real one only exists on Windows)."""

import sys
import types
from pathlib import Path

import pytest

from src import resume


class FakeDoc:
    def __init__(self, log):
        self.log = log

    def ExportAsFixedFormat(self, path, fmt):
        self.log.append(("export", path, fmt))

    def Close(self, save):
        self.log.append(("close", save))


class FakeWord:
    def __init__(self, log, fail_open):
        self.log, self.fail_open = log, fail_open
        self.Documents = types.SimpleNamespace(Open=self.open)

    def open(self, path, *args):
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
    out = resume.docx_to_pdf(tmp_path / "a.docx", tmp_path / "a.pdf")
    assert out == (tmp_path / "a.pdf").resolve()
    assert len(instances) == 2 and ("quit",) in log  # broken instance quit, fresh one used
    resume.docx_to_pdf(tmp_path / "b.docx", tmp_path / "b.pdf")
    assert len(instances) == 2  # same instance for the next file
    assert [e[0] for e in log].count("export") == 2


def test_word_error_is_reported_not_hidden(fake_com, tmp_path, monkeypatch):
    monkeypatch.setattr(FakeWord, "open", lambda self, *a: (_ for _ in ()).throw(RuntimeError("file locked")))
    with pytest.raises(RuntimeError, match="Word could not convert a.docx to PDF: file locked"):
        resume.docx_to_pdf(tmp_path / "a.docx", tmp_path / "a.pdf")


def test_a_path_too_long_for_word_is_converted_from_a_short_copy(tmp_path, monkeypatch):
    def too_long(path):
        return len(str(path).encode("utf-16-le")) // 2 > 259

    class Doc:
        def __init__(self, path):
            self.path = path

        def ExportAsFixedFormat(self, out, fmt):
            if too_long(out):
                raise RuntimeError("path too long")
            Path(out).write_bytes(Path(self.path).read_bytes())

        def Close(self, save):
            pass

    word = types.SimpleNamespace(Quit=lambda *a: None, Documents=types.SimpleNamespace(
        Open=lambda path, *a: None if too_long(path) else Doc(path)))  # what Word does past MAX_PATH
    monkeypatch.setattr(resume._Word, "app", word)
    monkeypatch.setattr(resume._Word, "quit", classmethod(lambda cls: None))  # the retry gets the same fake
    folder = tmp_path / ("d" * 120) / ("e" * 120)
    folder.mkdir(parents=True)
    (folder / "🌍 letter.docx").write_bytes(b"letter")
    resume._word_to_pdf(folder / "🌍 letter.docx", folder / "🌍 letter.pdf")
    assert (folder / "🌍 letter.pdf").read_bytes() == b"letter"


def test_locked_docx_says_word_has_it_open(tmp_path):
    target = tmp_path / "Jake Resume.docx"
    (tmp_path / "~$ke Resume.docx").write_text("owner")

    class Locked:
        def save(self, path):
            raise PermissionError(13, "Permission denied", path)

    with pytest.raises(RuntimeError, match="Word has it open"):
        resume._save_docx(Locked(), target)
