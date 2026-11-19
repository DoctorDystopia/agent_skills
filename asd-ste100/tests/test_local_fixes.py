"""Tests for the local changes to the ep01 kit.

Run from the skill directory:

    python -m unittest discover -s tests -p "test_*.py"

The kit files have hyphens in their names, so they load by path, not by import.
"""
import importlib.util
import os
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relative_path):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_ROOT, relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINT = _load("ste_lint", "scripts/ste-lint.py")
PREGATE = _load("ste_pregate", "hooks/ste-pregate.py")
REFRESH = _load("ste_refresh", "hooks/ste-refresh.py")
GATE = _load("ste_gate", "hooks/ste-gate.py")

_WRAPPED_LONG_SENTENCE = (
    "The parser reads the file and then it writes the output to the cache\n"
    "that the server loads at start, and the client reads that same cache\n"
    "on each frame after it connects to the server.\n"
)


class UnwrapTest(unittest.TestCase):

    def test_a_hard_wrapped_sentence_counts_one_time(self):
        report = LINT.lint(_WRAPPED_LONG_SENTENCE)
        self.assertEqual(report["sentences"], 1)
        self.assertEqual(report["violations"]["long_sentence(>20w)"], 1)

    def test_list_items_stay_separate(self):
        report = LINT.lint("- The first item\n- The second item\n")
        self.assertEqual(report["sentences"], 2)

    def test_a_heading_does_not_absorb_the_next_line(self):
        report = LINT.lint("# Title\nThe body starts here.\n")
        self.assertEqual(report["sentences"], 2)

    def test_a_wrapped_paragraph_is_not_a_long_paragraph(self):
        report = LINT.lint(_WRAPPED_LONG_SENTENCE * 2)
        self.assertEqual(report["violations"]["long_paragraph(>6s)"], 0)

    def test_an_indented_continuation_keeps_a_list_run(self):
        items = "".join("- Item {}\n  more text\n".format(i) for i in range(6))
        self.assertEqual(len(LINT.long_lists(items)), 1)

    def test_a_list_run_reports_its_first_line(self):
        items = "Intro line.\n\n" + "".join("- Item {}\n".format(i)
                                            for i in range(6))
        self.assertEqual(LINT.long_lists(items), [3])


class ShapePhraseTest(unittest.TestCase):

    def _shape(self, text):
        return LINT.lint(text)["shape"]

    def test_an_announcement_counts_in_any_sentence(self):
        shape = self._shape("The run is in progress. Here's where things stand:\n")
        self.assertEqual(shape["announcement"], 1)
        self.assertEqual(shape["preamble_opener"], 0)

    def test_an_announcement_without_a_contraction_counts(self):
        self.assertEqual(self._shape("Here is what I found.\n")["announcement"], 1)

    def test_an_offer_with_no_information_is_a_closer(self):
        for text in ("Say the word and I will do it.\n",
                     "Waiting on your go-ahead before I touch a file.\n",
                     "Standing by.\n"):
            with self.subTest(text=text):
                self.assertEqual(self._shape(text)["closer"], 1)

    def test_the_next_step_of_a_run_is_not_a_closer(self):
        for text in ("I continue when the run ends.\n",
                     "I will report when it completes.\n"):
            with self.subTest(text=text):
                self.assertEqual(self._shape(text)["closer"], 0)

    def test_a_result_sentence_has_no_shape_count(self):
        shape = self._shape("All 187 tests pass. The fix is in the parser.\n")
        self.assertEqual(sum(shape.values()), 0)


class PregateCommitMessageTest(unittest.TestCase):

    def test_powershell_single_quoted_here_string(self):
        command = "git commit -m @'\nSubject line\n\nBody text.\n'@"
        self.assertEqual(PREGATE.commit_message(command),
                         "Subject line\n\nBody text.")

    def test_powershell_double_quoted_here_string(self):
        command = 'git commit -m @"\r\nSubject line\r\n"@'
        self.assertEqual(PREGATE.commit_message(command), "Subject line")

    def test_message_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "msg.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("Subject from a file")
            message = PREGATE.commit_message("git commit -F msg.txt", folder)
        self.assertEqual(message, "Subject from a file")

    def test_bash_quoted_message_still_parses(self):
        self.assertEqual(PREGATE.commit_message("git commit -m 'Short'"),
                         "Short")

    def test_a_command_that_is_not_a_commit(self):
        self.assertIsNone(PREGATE.commit_message("git status -m 'x'"))


class PregateGhTextTest(unittest.TestCase):
    """A pull request body reaches more readers than a commit message."""

    def test_a_pull_request_title_and_body(self):
        command = ('gh pr create --title "Add the gate" '
                   '--body "The gate lints the body before it goes out."')
        text = PREGATE.gh_text(command)
        self.assertIn("Add the gate", text)
        self.assertIn("The gate lints the body", text)

    def test_a_heredoc_body(self):
        command = ("gh pr create --body \"$(cat <<'EOF'\n"
                   "The body text.\nEOF\n)\"")
        self.assertEqual(PREGATE.gh_text(command), "The body text.")

    def test_a_powershell_here_string_body(self):
        command = "gh pr create --body @'\nThe body text.\n'@"
        self.assertEqual(PREGATE.gh_text(command), "The body text.")

    def test_a_body_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "body.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("The body from a file")
            text = PREGATE.gh_text("gh pr create --body-file body.md", folder)
        self.assertEqual(text, "The body from a file")

    def test_an_issue_comment(self):
        self.assertEqual(PREGATE.gh_text("gh issue comment 5 -b 'The note.'"),
                         "The note.")

    def test_release_notes(self):
        self.assertEqual(PREGATE.gh_text("gh release create v1 --notes 'Ships.'"),
                         "Ships.")

    def test_a_repo_flag_before_the_object(self):
        command = "gh --repo owner/name pr create --body 'The body.'"
        self.assertEqual(PREGATE.gh_text(command), "The body.")

    def test_a_read_only_command_sends_nothing(self):
        self.assertIsNone(PREGATE.gh_text("gh pr view 3 --json body"))

    def test_a_command_that_is_not_gh(self):
        self.assertIsNone(PREGATE.gh_text("git log --oneline -b 'x'"))

    def test_a_word_that_ends_in_gh(self):
        self.assertIsNone(PREGATE.gh_text("echo high pr create --body 'x'"))


class RefreshSkipTest(unittest.TestCase):

    def test_a_windows_memory_path_is_skipped(self):
        path = r"C:\Users\N\.claude\projects\repo\memory\note.md"
        self.assertTrue(REFRESH.is_skipped(path))

    def test_a_windows_scratchpad_path_is_skipped(self):
        path = r"C:\Users\N\AppData\Local\Temp\claude\x\scratchpad\draft.md"
        self.assertTrue(REFRESH.is_skipped(path))

    def test_a_windows_doc_path_is_linted(self):
        self.assertFalse(REFRESH.is_skipped(r"C:\repos\muddev\docs\note.md"))


class RefreshProseFileTest(unittest.TestCase):
    """The file check reads a prose file whole."""

    _SLOP = ("We utilize the seamless parser in order to ensure the cache is "
             "rebuilt by the worker. It is important to note that the results "
             "are being written to the disk, and the client will have "
             "performed a validation of the payload before it reaches out to "
             "the service that was spun up by the operator.\n") * 2

    def _report_for(self, name):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._SLOP)
            return REFRESH.prose_report({"tool_name": "Write",
                                         "tool_input": {"file_path": path}})

    def test_a_markdown_file_is_linted(self):
        self.assertIn("violations per 100 words", self._report_for("note.md"))

    def test_a_text_file_is_linted(self):
        self.assertIn("violations per 100 words", self._report_for("note.txt"))

    def test_a_restructured_text_file_is_linted(self):
        self.assertIn("violations per 100 words", self._report_for("note.rst"))

    def test_an_upper_case_suffix_is_linted(self):
        self.assertIn("violations per 100 words", self._report_for("NOTE.MD"))

    def test_a_file_that_is_neither_prose_nor_source_is_not_linted(self):
        self.assertIsNone(self._report_for("data.csv"))

    def test_a_source_file_goes_through_the_extractor(self):
        """The bare slop is not valid Python, so no line of it is prose."""
        self.assertIsNone(self._report_for("module.py"))


class RefreshSourceFileTest(unittest.TestCase):
    """A source file scores the prose THIS edit wrote, never the file.

    80% of the source files in the Blackout game score over the target, and
    those docstrings came before the standard. A hook that reports the whole
    file on each edit reports the past every time, and a reader learns to
    ignore it.
    """

    _SLOP = ('"""We utilize the seamless parser in order to ensure the cache\n'
             'is rebuilt by the worker. It is important to note that the\n'
             'results are being written to the disk, and the client will have\n'
             'performed a validation of the payload before it reaches out.\n'
             '"""\n')
    # The same prose as a function docstring. A string that follows a
    # statement is not a docstring, so ast gives nothing back for one.
    _DOC = ('    """We utilize the seamless parser in order to ensure the\n'
            '    cache is rebuilt by the worker. It is important to note that\n'
            '    the results are being written to the disk, and the client\n'
            '    will have performed a validation before it reaches out.\n'
            '    """\n')
    _CODE = "    return raw.strip()\n"
    _FUNC = "def parse(raw):\n" + _DOC + _CODE

    def _report(self, name, body, tool="Write", new_string=None):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            tool_input = {"file_path": path}
            if new_string is not None:
                tool_input["new_string"] = new_string
            return REFRESH.prose_report({"tool_name": tool,
                                         "tool_input": tool_input})

    def test_a_written_python_file_with_bad_prose_reports(self):
        report = self._report("module.py", self._SLOP)
        self.assertIsNotNone(report)
        self.assertIn("violations per 100 words", report)

    def test_the_report_names_the_prose_not_the_file(self):
        self.assertIn("the prose you just wrote",
                      self._report("module.py", self._SLOP))

    def test_a_small_code_edit_beside_legacy_slop_stays_silent(self):
        self.assertIsNone(self._report("module.py", self._FUNC, tool="Edit",
                                       new_string=self._CODE))

    def test_an_edit_that_writes_bad_prose_reports(self):
        self.assertIsNotNone(self._report("module.py", self._FUNC,
                                          tool="Edit", new_string=self._DOC))

    def test_a_new_string_the_file_lost_reports_nothing(self):
        self.assertIsNone(self._report("module.py", self._SLOP, tool="Edit",
                                       new_string="text that is not there"))

    def test_code_alone_reports_nothing(self):
        body = "".join("def f{}(x):\n    return x + {}\n".format(n, n)
                       for n in range(40))
        self.assertIsNone(self._report("module.py", body))

    def test_a_gdscript_file_is_read(self):
        body = "".join("## {}\n".format(line) for line in
                       self._SLOP.replace('"""', "").split("\n") if line)
        self.assertIsNotNone(self._report("view.gd", body))


class RefreshSpanTest(unittest.TestCase):

    def test_the_span_of_an_edit(self):
        text = "one\ntwo\nthree\nfour\n"
        self.assertEqual(REFRESH._edited_span(text, {"new_string": "three"}),
                         (3, 3))

    def test_a_multi_line_span(self):
        text = "one\ntwo\nthree\nfour\n"
        self.assertEqual(REFRESH._edited_span(text, {"new_string": "two\nthree"}),
                         (2, 3))

    def test_a_write_covers_every_line(self):
        self.assertEqual(REFRESH._edited_span("one\ntwo\nthree\n", {}), (1, 4))

    def test_text_the_file_lost_gives_none(self):
        self.assertIsNone(REFRESH._edited_span("one\n", {"new_string": "gone"}))

    def test_only_span_empties_every_other_line(self):
        self.assertEqual(REFRESH._only_span("a\nb\nc\nd", (2, 3)), "\nb\nc\n")


class GateLockTest(unittest.TestCase):
    """A subagent block and a parent block keep separate locks.

    One lock for both would let a subagent block consume the parent's one
    block for that turn, or the reverse.
    """

    def setUp(self):
        self.session = "ste-test-{}".format(os.getpid())

    def tearDown(self):
        for suffix in ("lock", "sub.lock"):
            try:
                os.remove(GATE.state_path(self.session, suffix))
            except OSError:
                pass

    def test_the_two_locks_are_two_files(self):
        self.assertNotEqual(GATE.state_path(self.session, "lock"),
                            GATE.state_path(self.session, "sub.lock"))

    def test_each_lock_keeps_its_own_turn(self):
        GATE.mark_blocked(self.session, 3, "lock")
        GATE.mark_blocked(self.session, 7, "sub.lock")
        self.assertEqual(GATE.blocked_turn(self.session, "lock"), 3)
        self.assertEqual(GATE.blocked_turn(self.session, "sub.lock"), 7)

    def test_an_unused_lock_reports_no_turn(self):
        self.assertEqual(GATE.blocked_turn(self.session, "sub.lock"), -1)


if __name__ == "__main__":
    unittest.main()
