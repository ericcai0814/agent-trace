from pathlib import Path

from agent_trace.adapters.claude_code import _parse_frontmatter, load_skill_whitelist


def test_parse_frontmatter_basic():
    text = (
        "---\n"
        "name: foo\n"
        "description: hello\n"
        "disable-model-invocation: true\n"
        "---\n"
        "body content\n"
    )
    fm = _parse_frontmatter(text)
    assert fm["name"] == "foo"
    assert fm["description"] == "hello"
    assert fm["disable-model-invocation"] == "true"


def test_parse_frontmatter_handles_missing():
    assert _parse_frontmatter("no frontmatter here") == {}
    assert _parse_frontmatter("---\nname: foo\n# no closing fence\n") == {}


def test_load_skill_whitelist_from_tmp_roots(tmp_path: Path):
    root = tmp_path / "skills"
    (root / "alpha").mkdir(parents=True)
    (root / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: x\n---\nbody\n"
    )
    (root / "beta-slash").mkdir()
    (root / "beta-slash" / "SKILL.md").write_text(
        "---\nname: beta-slash\ndisable-model-invocation: true\n---\nbody\n"
    )
    # A directory without SKILL.md is skipped silently.
    (root / "gamma").mkdir()

    whitelist = load_skill_whitelist(extra_roots=[root])
    assert "alpha" in whitelist
    assert whitelist["alpha"]["disable_model_invocation"] is False
    assert whitelist["beta-slash"]["disable_model_invocation"] is True
    assert "gamma" not in whitelist
