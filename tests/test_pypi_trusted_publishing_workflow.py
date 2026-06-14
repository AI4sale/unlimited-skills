"""Guard the v0.6 PyPI Trusted Publishing workflow."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-pypi.yml"
DOC = ROOT / "docs" / "releases" / "v0.6.0-alpha-pypi-publishing.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_publish_workflow_is_manual_and_oidc_only() -> None:
    text = read(WORKFLOW)
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "id-token: write" in text
    assert "environment:" in text
    assert "name: pypi" in text
    assert "pypa/gh-action-pypi-publish@release/v1" in text
    assert "PYPI_TOKEN" not in text
    assert "TWINE_PASSWORD" not in text
    assert "password:" not in text


def test_publish_workflow_requires_exact_v060_confirmation() -> None:
    text = read(WORKFLOW)
    assert "version" in text
    assert "expected_sha" in text
    assert "confirm_pypi_publish" in text
    assert 'test "${{ github.event.inputs.version }}" = "0.6.0"' in text
    assert (
        'test "${{ github.event.inputs.confirm_pypi_publish }}" = "publish unlimited-skills 0.6.0 to PyPI"'
        in text
    )
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.inputs.expected_sha }}"' in text


def test_pypi_publisher_values_are_documented() -> None:
    text = read(DOC)
    for required in (
        "Project/package name | `unlimited-skills`",
        "Owner | `AI4sale`",
        "Repository | `unlimited-skills`",
        "Workflow filename | `publish-pypi.yml`",
        "Environment | `pypi`",
        "No `PYPI_TOKEN`, `TWINE_PASSWORD`, `TWINE_USERNAME`, or local `.pypirc`",
    ):
        assert required in text
