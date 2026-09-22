#!/usr/bin/env python3
"""PostToolUse hook for the asd-ste100 skill. Two jobs:

1. The distance problem. The turn-start card injects the rule, but a long
   working turn puts dozens of tool calls between that card and the final
   reply. By the time the model writes the reply, the card sits far back in
   context. This hook counts the tool calls in the turn and re-injects a short
   card every EVERY calls, so the rule is always near the reply.

2. The file problem. The Stop gate lints the chat reply only. Prose written to
   a file never meets it. After a Write or an Edit of a prose file, this hook
   lints the file and reports the score into context, so the model fixes the
   file in the same turn. PROSE_SUFFIXES names the file types.

Both jobs inject context. Neither blocks. The turn counter is reset by
ste-inject.py on each user prompt.

Local change to the ep01 kit copy: SKIP holds forward-slash fragments, and a
Windows file_path uses backslashes, so no skip ever matched there. Memory
notes and scratchpad drafts got a lint report after every write. is_skipped
compares against the path with its separators turned to forward slashes.

Canonical copy: the ep01 kit, asd-ste100/hooks/ste-refresh.py
"""
import hashlib
import json
import os
import subprocess
import sys

def find_lint():
    """The linter ships next to this skill. Look there first, then at the
    installed path, so the plugin cache, a skills-CLI copy, and the
    settings-route install all resolve."""
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    for path in (os.path.join(root, "scripts", "ste-lint.py"),
                 os.path.expanduser("~/.claude/skills/asd-ste100/scripts/ste-lint.py")):
        if os.path.exists(path):
            return path
    return None


LINT = find_lint()
RUNNER = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                      "run-python.cjs")
STATE = os.path.expanduser("~/.claude/ste-gate")

EVERY = 12          # tool calls between two cards
TARGET = 2.5        # flavored target for a written prose file
MIN_WORDS = 40      # skip a stub file - the score is noise below this
MAX_BYTES = 200_000
# A file that holds prose and nothing else.
PROSE_SUFFIXES = (".md", ".markdown", ".txt", ".rst")

# A source file holds prose inside code. ste_extract takes the docstrings and
# the comments out and keeps every line number. Two rules keep this quiet:
#
# 1. An Edit scores the LINES THIS EDIT WROTE, never the file around them.
#    Measured over 317 files of the Blackout game, 80% of the source files
#    score over the 2.5 target, and the median is 3.8. Those docstrings came
#    before the standard. A hook that reports the whole file on each edit
#    reports the past, every time, and a reader learns to ignore it.
# 2. The span must carry SOURCE_MIN_WORDS of prose. A one-line fix says
#    nothing about writing, so the hook says nothing back.
SOURCE_MIN_WORDS = 30

# Paths where the advisory stays silent. Blog posts and episode pages have a
# voice. The experiment files are published data. The skill files quote
# violations on purpose. A scratchpad draft is linted by the model itself.
# Plans and memory notes are working files, not published prose.
SKIP = ["/blog/", "(episode)", "/experiment/", "/asd-ste100/",
        "/scratchpad/", "/memory/", "/ste-gate/", "/output-styles/",
        "/.claude/plans/"]

CARD = (
    "ste check-in, mid-turn: the standing rule still governs the reply you "
    "write at the end of this turn. Layer 1: active voice, simple tenses, "
    "max 20 words for an instruction, no contractions, no semicolons, keep "
    "the articles. Layer 2: the next action first, numbered steps, no "
    "preamble, no recap, no closer. If the reply runs over 60 words, lint "
    "the draft first: node \"{}\" \"{}\" --fail-over 2.5 FILE"
).format(RUNNER, LINT or "scripts/ste-lint.py")


def is_skipped(path):
    """True when the advisory stays silent for this path, on any OS."""
    normalized = path.replace("\\", "/")
    return any(fragment in normalized for fragment in SKIP)


def count_path(session):
    os.makedirs(STATE, exist_ok=True)
    key = hashlib.sha1((session or "none").encode()).hexdigest()[:16]
    return os.path.join(STATE, "{}.count".format(key))


def bump(session):
    path = count_path(session)
    try:
        with open(path, encoding="utf-8") as fh:
            n = int(fh.read().strip() or 0)
    except Exception:
        n = 0
    n += 1
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(n))
    except Exception:
        pass
    return n


def load_extractor():
    """ste_extract, from the same directory that gave the linter."""
    if not LINT:
        return None
    path = os.path.join(os.path.dirname(LINT), "ste_extract.py")
    if not os.path.exists(path):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ste_extract", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


EXTRACT = load_extractor()


def _edited_span(text, tool_input):
    """The first and last line that this edit wrote, or None for all of it.

    `new_string` is the text the Edit put into the file. Its position gives
    the span to score. A Write replaces the whole file, so every line of it
    is new. A `new_string` that the file no longer holds gives None, and the
    caller then scores nothing rather than the wrong lines.
    """
    new_text = tool_input.get("new_string")
    if not new_text:
        return 1, text.count("\n") + 1          # a Write, or a full rewrite
    index = text.find(new_text)
    if index < 0:
        return None
    first = text.count("\n", 0, index) + 1
    return first, first + new_text.count("\n")


def _only_span(prose, span):
    """The prose, with every line outside the span made empty."""
    first, last = span
    lines = prose.split("\n")
    kept = [line if first <= number <= last else ""
            for number, line in enumerate(lines, 1)]
    return "\n".join(kept)


def _score(text):
    """The linter's report for one text, or None when the run fails."""
    try:
        proc = subprocess.run([sys.executable, LINT], input=text,
                              capture_output=True, text=True, timeout=15)
        return json.loads(proc.stdout)
    except Exception:
        return None


def prose_report(payload):
    """The score of the prose that this tool call wrote, or None.

    A prose file scores whole. A source file scores the docstrings and the
    comments that THIS edit wrote. See the SOURCE_MIN_WORDS comment above.
    """
    if payload.get("tool_name") not in ("Write", "Edit"):
        return None
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if not path or is_skipped(path):
        return None
    is_prose_file = path.lower().endswith(PROSE_SUFFIXES)
    is_source = bool(EXTRACT) and bool(EXTRACT.suffix_kind(path))
    if not is_prose_file and not is_source:
        return None
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None

    floor = MIN_WORDS
    what = os.path.basename(path)
    if is_source:
        prose = EXTRACT.extract(path, text)
        if prose is None:
            return None
        span = _edited_span(text, tool_input)
        if span is None:
            return None
        text = _only_span(prose, span)
        floor = SOURCE_MIN_WORDS
        what = "{} (the prose you just wrote)".format(what)

    report = _score(text)
    if not report or report.get("words", 0) < floor:
        return None
    score = report.get("total_per100w", 0)
    if score <= TARGET:
        return None
    hits = {k: v for k, v in (report.get("violations") or {}).items() if v}
    top = sorted(hits.items(), key=lambda kv: -kv[1])[:3]
    longs = report.get("sample_long_sentence") or []
    return (
        "ste: {} scored {} violations per 100 words. The target is {}. "
        "Worst: {}.{} Fix it before you finish this task."
    ).format(what, score, TARGET,
             ", ".join("{} {}".format(k, v) for k, v in top),
             " Longest: {}.".format(" | ".join(longs)) if longs else "")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not LINT:
        return 0
    notes = []
    if bump(payload.get("session_id") or "") % EVERY == 0:
        notes.append(CARD)
    report = prose_report(payload)
    if report:
        notes.append(report)
    if notes:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n\n".join(notes),
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
