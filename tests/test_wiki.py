import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import wiki_lint  # noqa: E402


def test_project_wiki_passes_lint():
    assert wiki_lint.lint() == []


def test_lint_finds_broken_link_missing_source_and_unlisted_page(tmp_path):
    (tmp_path / "index.md").write_text("# 목차\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "---\ntitle: A\nsources: [no/such/file.py]\nupdated: 2026-10-07\n---\n[b](b.md)\n", encoding="utf-8")
    problems = wiki_lint.lint(tmp_path, tmp_path)
    assert any("no/such/file.py" in p for p in problems)
    assert any("깨진 링크 'b.md'" in p for p in problems)
    assert any("index.md에 링크가 없음" in p for p in problems)


def test_lint_flags_secret_looking_strings(tmp_path):
    (tmp_path / "index.md").write_text("[a](a.md)\n", encoding="utf-8")
    (tmp_path / "a.md").write_text(
        "---\ntitle: A\nsources: [index.md]\nupdated: 2026-10-07\n---\nkey sk-abcdefghijklmnopqrstuvwxyz\n",
        encoding="utf-8")
    assert any("비밀 값" in p for p in wiki_lint.lint(tmp_path, tmp_path))
