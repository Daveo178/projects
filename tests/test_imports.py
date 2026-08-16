"""
Smoke test: every runtime dep listed in `requirements.txt` must import.

Catches the class of error where `requirements.txt` lists a package
but the user's environment doesn't have it installed — without this
test, the bug only surfaces when the user opens a page in the browser
and gets a `ModuleNotFoundError` on the first import (e.g. the
`plotly` outage that brought down `pages/1_Home.py` line 4).

Single source of truth: `requirements.txt`. Add a dep there and the
test automatically extends to cover it — no parallel list to keep in
sync. The parser is intentionally tolerant of the small set of pip
specifier shapes the project actually uses (plain `name`, pinned    `name==x.y.z`. Line continuations (`\` at EOL), env markers
    (`; python_version < "3.10"`), hashes (`--hash=sha256:…`) and
    extras (`name[extra]`) are not used in this project and would
    currently be parsed SILENTLY as a garbled separate package name —
    please upgrade the parser before adding any such specifier).
"""

import importlib
import pathlib
import tempfile
import unittest


# tests/ → project root is one level up.
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_REQUIREMENTS_PATH = _PROJECT_ROOT / "requirements.txt"


def _parse_requirements(path=_REQUIREMENTS_PATH):
    """Yield the top-level package name from each non-blank, non-comment
    line of a pip `requirements.txt` file.

    Handles the two specifier shapes used in this project:

        streamlit
        plotly==6.8.0

    and tolerates trailing whitespace + inline comments (`# …`). Skips
    blank lines, full-line comments, `-r other.txt` includes, and
    `--editable .` style direct-path specifiers (none of which are
    used in this repo today, but the parser doesn't crash on them).

    Per-line parser is deliberately line-local: there is no support
    for line continuations or env markers. If anyone ever needs them
    they'll get a clean `KeyError`-style failure here rather than a
    silent miss downstream.
    """
    OPERATORS = ("==", ">=", "<=", "!=", "~=", "> ", "<", ";", "[")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        # Strip inline comment first so `#` inside a name can't confuse
        # the comment-detection step.
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            # `-r`, `--requirement`, `-e`, `--editable`, etc.
            continue
        for op in OPERATORS:
            if op in line:
                line = line.split(op, 1)[0]
                break
        name = line.strip()
        if name:
            yield name


class TestRequirementsParse(unittest.TestCase):
    """Lock down the requirements.txt parser itself before it powers
    the import check — the import check is only as trustworthy as the
    parser that drives it."""

    def test_requirements_file_exists(self):
        self.assertTrue(
            _REQUIREMENTS_PATH.exists(),
            f"requirements.txt not found at {_REQUIREMENTS_PATH}",
        )

    def test_requirements_has_at_least_one_dep(self):
        deps = list(_parse_requirements())
        self.assertTrue(
            deps,
            "requirements.txt parsed to zero packages — "
            "check the file isn't all comments / blanks",
        )

    def test_parser_strips_pin_operator(self):
        # `plotly==6.8.0` should yield `plotly`, not `plotly==6.8.0`.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp) / "requirements.txt"
            tmp_path.write_text("foo==1.2.3\nbar>=4.5\nbaz\n", encoding="utf-8")
            self.assertEqual(
                list(_parse_requirements(tmp_path)),
                ["foo", "bar", "baz"],
            )

    def test_parser_skips_blank_lines_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp) / "requirements.txt"
            tmp_path.write_text(
                "# header comment\n\n"
                "streamlit\n"
                "  # inline-leading-whitespace comment-as-only-content\n"
                "pandas\n",
                encoding="utf-8",
            )
            self.assertEqual(
                list(_parse_requirements(tmp_path)),
                ["streamlit", "pandas"],
            )

    def test_parser_skips_include_and_editable_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp) / "requirements.txt"
            tmp_path.write_text(
                "-r other.txt\n"
                "--editable .\n"
                "streamlit\n"
                "-e git+https://example.com/foo.git#egg=foo\n",
                encoding="utf-8",
            )
            self.assertEqual(
                list(_parse_requirements(tmp_path)),
                ["streamlit"],
            )


class TestAllRequirementsImport(unittest.TestCase):
    """The headline check: every dep in requirements.txt must import
    cleanly in the current Python environment. One `subTest` per dep so
    a single missing package reports with a clear label rather than
    stopping on the first failure."""

    def test_all_requirements_import(self):
        deps = list(_parse_requirements())
        self.assertTrue(
            deps,
            "requirements.txt parsed to zero packages — "
            "nothing to import-check",
        )
        for dep in deps:
            with self.subTest(dep=dep):
                try:
                    importlib.import_module(dep)
                except ImportError as e:
                    # Re-raise with an actionable fix hint rather than
                    # letting the default ImportError stand. subTest
                    # gives per-dep isolation (one missing dep doesn't
                    # mask the rest); raising inside the subTest block
                    # surfaces the failure to the subTest reporter
                    # rather than swallowing it.
                    raise ImportError(
                        f"Required package '{dep}' is not installed. "
                        f"Run `python -m pip install -r requirements.txt` "
                        f"to fix. Original error: {e}"
                    ) from e

    def test_streamlit_imports(self):
        # Defence-in-depth: the most critical dep (the app's runtime)
        # gets its own named assertion so the failure message is
        # unambiguous in CI logs.
        importlib.import_module("streamlit")

    def test_plotly_imports(self):
        # The specific dep that triggered the original outage
        # (`ModuleNotFoundError: No module named 'plotly'` on
        # pages/1_Home.py line 4). Pinned as its own test so a future
        # regression on this exact dep cannot be hidden inside a
        # sub-loop failure.
        importlib.import_module("plotly")


if __name__ == "__main__":
    unittest.main()
