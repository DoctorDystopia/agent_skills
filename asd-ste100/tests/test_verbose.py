"""Tests for --verbose, the locator behind it.

Run from the skill directory:

    python -m unittest discover -s tests -p "test_*.py"

The guard that matters is CountAgreementTest. lint() counts. locate() finds
the position of each count. The two read the same blanked text and the same
word lists, but they hold two copies of each pattern. A change to one copy
alone makes --verbose lie about a file, and the summary and the rows then
disagree. These tests fail on that.
"""
import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relative_path):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_ROOT, relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINT = _load("ste_lint", "scripts/ste-lint.py")

# One text that fires a hit in every Layer 1 category, and a second that fires
# the Layer 2 categories. A corpus of real prose follows, from the skill's own
# files, so the agreement test also meets hard wraps, tables and fences.
_LAYER1 = """# Title

Let me utilize the seamless parser; it is important to note that the cache
has been rebuilt by the worker and the results are being written to the disk
before the client performs a validation of the payload and reaches out.

The team is required to spin up the service. The file is closed by the hook.

- one
- two
- three
- four
- five
- six
"""

_LAYER2 = """Great question. Here's what I found. The parser is slow.

I have now fixed it, and it will take a while. Perhaps the cache helps.
Unfortunately the first run failed. Let me know if you need anything else.
Say the word and I will do it.
"""

_CORPUS = ["README.md", "SKILL.md", "output-style.md",
           "references/ste-recurring-errors.md"]

# lint() reports these two next to the violations, not inside them.
_MARKERS = {"em_dash(slop-marker)": "em_dash(slop-marker)",
            "noun_train(>=4w,marker)": "noun_train(>=4w,marker)"}


def _by_category(rows):
    counts = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    return counts


class CountAgreementTest(unittest.TestCase):
    """Every count in lint() has the same number of rows in locate()."""

    def _compare(self, name, raw, strict):
        report = LINT.lint(raw, strict=strict)
        found = _by_category(LINT.locate(raw, strict=strict))
        expected = dict(report["violations"])
        expected.update(report["shape"])
        for key, marker in _MARKERS.items():
            if strict and marker == "em_dash(slop-marker)":
                continue          # strict counts it as em_dash, inside the total
            expected[marker] = report[key]
        for category, count in expected.items():
            with self.subTest(file=name, strict=strict, category=category):
                self.assertEqual(found.get(category, 0), count)

    def test_layer_1_fixture(self):
        self._compare("layer1", _LAYER1, strict=False)

    def test_layer_1_fixture_strict(self):
        self._compare("layer1", _LAYER1, strict=True)

    def test_layer_2_fixture(self):
        self._compare("layer2", _LAYER2, strict=False)

    def test_the_skill_corpus(self):
        for relative in _CORPUS:
            path = os.path.join(_ROOT, relative)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            self._compare(relative, raw, strict=False)
            self._compare(relative, raw, strict=True)

    def test_the_locator_finds_no_category_lint_does_not_count(self):
        known = set(LINT.lint(_LAYER1)["violations"])
        known |= set(LINT.lint(_LAYER1, strict=True)["violations"])
        known |= set(LINT.lint(_LAYER1)["shape"]) | set(_MARKERS)
        for row in LINT.locate(_LAYER1, strict=True):
            self.assertIn(row["category"], known)


class BlankCodeTest(unittest.TestCase):

    def test_the_length_does_not_change(self):
        raw = "Text `inline` more\n\n```\nfenced\nblock\n```\n\ntail\n"
        self.assertEqual(len(LINT.blank_code(raw)), len(raw))

    def test_each_newline_stays(self):
        raw = "a\n\n```\nb\nc\n```\n"
        self.assertEqual(LINT.blank_code(raw).count("\n"), raw.count("\n"))

    def test_the_sentence_list_matches_strip_code(self):
        """The two splits give the same sentences. Only the run of blanks
        between two words differs, and no check counts a blank."""
        raw = "Use `foo` now.\n\n```\ncode line\n```\n\nThen stop.\n"
        def flat(text):
            return [" ".join(s.split()) for s in LINT.sentences(text)]
        self.assertEqual(flat(LINT.blank_code(raw)),
                         flat(LINT.strip_code(raw)))


class LineNumberTest(unittest.TestCase):

    def _line_for(self, raw, category):
        for row in LINT.locate(raw):
            if row["category"] == category:
                return row["line"]
        return None

    def test_a_hit_reports_its_own_line(self):
        raw = "First line.\n\nSecond line.\n\nWe utilize the parser.\n"
        self.assertEqual(self._line_for(raw, "banned_word"), 5)

    def test_a_fenced_block_does_not_move_the_lines_after_it(self):
        raw = ("Intro.\n\n```\none\ntwo\nthree\n```\n\n"
               "We utilize the parser.\n")
        self.assertEqual(self._line_for(raw, "banned_word"), 9)

    def test_a_hard_wrapped_sentence_reports_its_first_line(self):
        raw = ("Intro.\n\n"
               "The parser reads the file and then it writes the output to\n"
               "the cache that the server loads at start, and the client\n"
               "reads that same cache on each frame.\n")
        self.assertEqual(self._line_for(raw, "long_sentence(>20w)"), 3)

    def test_a_hit_inside_a_code_span_is_not_reported(self):
        raw = "The flag `--utilize` names the option.\n"
        self.assertIsNone(self._line_for(raw, "banned_word"))


class RowShapeTest(unittest.TestCase):

    def test_a_short_match_carries_its_line_text(self):
        raw = "The cache is deleted by the worker every night at midnight.\n"
        rows = [r for r in LINT.locate(raw) if r["category"] == "passive_voice"]
        self.assertTrue(rows)
        self.assertIn("|", rows[0]["text"])
        self.assertTrue(rows[0]["text"].startswith("is deleted"))

    def test_every_category_has_a_help_line(self):
        rows = LINT.locate(_LAYER1, strict=True) + LINT.locate(_LAYER2)
        for row in rows:
            with self.subTest(category=row["category"]):
                self.assertTrue(LINT.RULE_HELP.get(row["category"]))

    def test_the_rows_come_out_in_line_order(self):
        rows = LINT.locate(_LAYER1)
        lines = [r["line"] or 0 for r in rows]
        self.assertEqual(lines, sorted(lines))

    def test_format_rows_names_each_rule_that_fired(self):
        rows = LINT.locate(_LAYER1)
        text = LINT.format_rows(rows)
        self.assertIn("rules that fired", text)
        for category in {r["category"] for r in rows}:
            self.assertIn(category, text)


if __name__ == "__main__":
    unittest.main()
