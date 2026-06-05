#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from wiki_link_strength import resolve_page, write_outputs


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_resolve_page_disambiguates_basenames() -> None:
    all_paths = {
        "concepts/type-1-diabetes-screening-autoantibodies.md",
        "claims/type-1-diabetes-screening-autoantibodies.md",
        "concepts/diabetes-bone-health-osteoporosis.md",
    }
    assert_equal(resolve_page(all_paths, "diabetes-bone-health-osteoporosis"), "concepts/diabetes-bone-health-osteoporosis.md", "single basename match")
    assert_equal(resolve_page(all_paths, "type-1-diabetes-screening-autoantibodies"), None, "ambiguous basename match")
    assert_equal(
        resolve_page(all_paths, "claims/type-1-diabetes-screening-autoantibodies"),
        "claims/type-1-diabetes-screening-autoantibodies.md",
        "exact path match wins",
    )
    assert_equal(
        resolve_page(all_paths, "claims/type-1-diabetes-screening-autoantibodies.md"),
        "claims/type-1-diabetes-screening-autoantibodies.md",
        "exact markdown path match wins",
    )


def test_write_outputs_marks_empty_weak_nodes() -> None:
    payload = {
        "node_count": 1,
        "edge_count": 0,
        "negative_edges": [],
        "top_nodes": [{"path": "concepts/example.md", "score": 10.0, "signals": {}}],
        "weak_nodes": [],
        "recommendations": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _, report_path = write_outputs(root, payload)
        report = report_path.read_text(encoding="utf-8")
    expected = "## Weak Or Underconnected Pages\n\n- None\n"
    if expected not in report:
        raise AssertionError("empty weak_nodes section should render '- None'")


def test_write_outputs_preserves_nonempty_weak_nodes() -> None:
    payload = {
        "node_count": 1,
        "edge_count": 0,
        "negative_edges": [],
        "top_nodes": [{"path": "concepts/example.md", "score": 10.0, "signals": {}}],
        "weak_nodes": [{"path": "concepts/weak.md", "score": 3.0, "aliases": 0, "wikilinks": 1}],
        "recommendations": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _, report_path = write_outputs(root, payload)
        report = report_path.read_text(encoding="utf-8")
    if "- `concepts/weak.md`: score 3.0; aliases 0; wikilinks 1" not in report:
        raise AssertionError("non-empty weak_nodes section should render weak page rows")
    weak_section = report.split("## Weak Or Underconnected Pages", 1)[1].split("## Negative Edges", 1)[0]
    if "- None" in weak_section:
        raise AssertionError("non-empty weak_nodes section should not render '- None'")


def main() -> int:
    test_resolve_page_disambiguates_basenames()
    test_write_outputs_marks_empty_weak_nodes()
    test_write_outputs_preserves_nonempty_weak_nodes()
    print("PASS wiki_link_strength_unit_tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
