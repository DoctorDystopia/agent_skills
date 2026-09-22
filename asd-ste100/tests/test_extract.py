"""Tests for ste_extract, the prose reader for a source file.

Run from the skill directory:

    python -m unittest discover -s tests -p "test_*.py"

The rule that every test here defends: the output holds ONE LINE FOR EACH LINE
of the source. A report then names the real line of the real file, and two
prose blocks that sit apart in the file stay apart in the score.
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


EXTRACT = _load("ste_extract", "scripts/ste_extract.py")
LINT = _load("ste_lint", "scripts/ste-lint.py")

_MODULE = '''#!/usr/bin/env python3
"""The module docstring.

It runs over two paragraphs.
"""
import os

CAP = 12            # tool calls between two cards
STEP = 2            # the size of one step


def parse(raw):     # type: ignore
    """Read the raw text.

    The second line of the function docstring.
    """
    # A note that stands on its own line.
    return os.path.basename(raw)
'''


class LineNumberTest(unittest.TestCase):

    def setUp(self):
        self.prose = EXTRACT.extract("m.py", _MODULE)
        self.lines = self.prose.split("\n")
        self.source = _MODULE.split("\n")

    def test_the_line_count_does_not_change(self):
        self.assertEqual(len(self.lines), len(self.source))

    def test_a_docstring_keeps_its_line(self):
        self.assertIn("The module docstring", self.lines[1])

    def test_a_function_docstring_keeps_its_line(self):
        found = [n for n, line in enumerate(self.lines, 1)
                 if "Read the raw text" in line]
        self.assertEqual(found, [13])

    def test_a_standalone_comment_keeps_its_line(self):
        found = [n for n, line in enumerate(self.lines, 1)
                 if "stands on its own line" in line]
        self.assertEqual(found, [17])

    def test_code_lines_are_empty(self):
        self.assertEqual(self.lines[5].strip(), "")      # import os


class WhatCountsAsProseTest(unittest.TestCase):

    def setUp(self):
        self.prose = EXTRACT.extract("m.py", _MODULE)

    def test_the_shebang_is_not_prose(self):
        self.assertNotIn("usr/bin/env", self.prose)

    def test_a_tool_directive_is_not_prose(self):
        self.assertNotIn("type:", self.prose)

    def test_code_is_not_prose(self):
        self.assertNotIn("os.path.basename", self.prose)
        self.assertNotIn("import", self.prose)

    def test_a_quote_mark_is_not_prose(self):
        self.assertNotIn('"""', self.prose)

    def test_a_ruler_comment_is_not_prose(self):
        prose = EXTRACT.extract("m.py", "x = 1\n# ----------------\n")
        self.assertEqual(prose.strip(), "")


class TrailingCommentTest(unittest.TestCase):
    """Three labels on three lines of code are not one paragraph."""

    def test_two_trailing_comments_stay_two_sentences(self):
        prose = EXTRACT.extract("m.py", _MODULE)
        sentences = [s for s in LINT.sentences(prose) if "tool calls" in s
                     or "size of one step" in s]
        self.assertEqual(len(sentences), 2)

    def test_a_run_of_trailing_comments_is_not_a_long_sentence(self):
        source = "".join(
            "VALUE_{} = {}   # the number of tool calls between two cards\n"
            .format(n, n) for n in range(6))
        prose = EXTRACT.extract("m.py", source)
        report = LINT.lint(prose)
        self.assertEqual(report["violations"]["long_sentence(>20w)"], 0)

    def test_a_block_of_standalone_comments_is_one_paragraph(self):
        source = ("# The parser reads the file and then it writes the output\n"
                  "# to the cache that the server loads at start, and the\n"
                  "# client reads that same cache on each frame.\n")
        prose = EXTRACT.extract("m.py", source)
        self.assertEqual(len(LINT.sentences(prose)), 1)


class BrokenFileTest(unittest.TestCase):
    """tokenize reads further than ast does, so comments survive a bad file."""

    def test_a_syntax_error_still_gives_the_comments(self):
        source = "# A real note about the parser.\ndef broken(:\n"
        prose = EXTRACT.extract("m.py", source)
        self.assertIn("A real note about the parser", prose)

    def test_a_syntax_error_raises_nothing(self):
        self.assertIsNotNone(EXTRACT.extract("m.py", "def (((\n"))


class GdScriptTest(unittest.TestCase):

    _GD = ('extends Node\n'
           '## The doc comment for the class.\n'
           'var speed = 1  # the tiles for each second\n'
           'var name = "# not a comment"\n'
           '# A standalone note.\n')

    def test_a_doc_comment_is_prose(self):
        prose = EXTRACT.extract("v.gd", self._GD)
        self.assertIn("The doc comment for the class", prose)

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        prose = EXTRACT.extract("v.gd", self._GD)
        self.assertNotIn("not a comment", prose)

    def test_the_line_count_does_not_change(self):
        prose = EXTRACT.extract("v.gd", self._GD)
        self.assertEqual(len(prose.split("\n")), len(self._GD.split("\n")))

    def test_code_is_not_prose(self):
        prose = EXTRACT.extract("v.gd", self._GD)
        self.assertNotIn("extends Node", prose)


class SuffixTest(unittest.TestCase):

    def test_a_known_suffix(self):
        self.assertEqual(EXTRACT.suffix_kind("a/b/c.py"), "python")
        self.assertEqual(EXTRACT.suffix_kind("a/b/c.GD"), "gdscript")

    def test_an_unknown_suffix_gives_none(self):
        self.assertIsNone(EXTRACT.suffix_kind("readme.md"))
        self.assertIsNone(EXTRACT.extract("readme.md", "# Title\n"))


class ScoreTest(unittest.TestCase):
    """The reason the module exists: code must not dilute the score."""

    def test_code_does_not_enter_the_word_count(self):
        prose = EXTRACT.extract("m.py", _MODULE)
        self.assertLess(LINT.lint(prose)["words"],
                        LINT.lint(_MODULE)["words"])


if __name__ == "__main__":
    unittest.main()
