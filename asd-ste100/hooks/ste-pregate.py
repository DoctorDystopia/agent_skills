#!/usr/bin/env python3
"""PreToolUse hook for the asd-ste100 skill. The pre-send gate.

The Stop gate has a structural cost: it runs after the reply is on the
reader's screen, so a block puts a second copy there. This gate has no such
cost. It runs BEFORE the tool call, so a deny reaches the model only. The
model corrects the text and makes the same call again, and the reader sees
one clean result. This makes commit messages and board text deterministic in
a way the reply itself can never be.

Gated text:

- Bash, PowerShell   the commit message, from -m arguments, a bash heredoc
                     body, a PowerShell here-string, or the file that -F names
- Bash, PowerShell   the title and body of a gh pull request, issue, comment
                     or release, from --title, --body, --notes, a heredoc, a
                     here-string, or the file that --body-file names
- Elliptic           title, description, and body fields on create and update

Everything fails open. A parse miss, a broken linter, or a short text lets
the call through. The deny fires only over the same ceiling the Stop gate
uses, so the two gates agree on what is bad enough to stop.

Local changes to the ep01 kit copy:

- The kit matched Bash only. On Windows the agent also commits through the
  PowerShell tool, with the message in an @'...'@ here-string, so the gate
  never saw those commits.
- The kit gated the commit message alone. A pull request body reaches more
  readers than a commit message does, and it goes out through the same two
  shell tools. gh_text() gates it.

Canonical copy: the ep01 kit, asd-ste100/hooks/ste-pregate.py
"""
import json
import os
import re
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

BLOCK_AT = 4.0        # same ceiling as the Stop gate
SHAPE_BLOCK_AT = 4
MIN_WORDS = 30        # a short message scores as noise - let it through
MAX_FILE_BYTES = 100_000

SHELL_TOOLS = ("Bash", "PowerShell")
TEXT_FIELDS = ("title", "description", "body", "content")


def _flag_file(command, cwd, flags):
    """The text of the file that one of `flags` names, or None."""
    pattern = r"(?:{})(?:\s+|=)(['\"]?)([^'\"\s]+)\1".format("|".join(flags))
    m = re.search(pattern, command)
    if not m or m.group(2) == "-":
        return None
    path = m.group(2)
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _message_file(command, cwd):
    """The text of the file that -F or --file names, or None."""
    return _flag_file(command, cwd, ("-F", "--file"))


def _heredoc_bodies(command):
    """Each bash heredoc body and each PowerShell here-string body."""
    parts = []
    for m in re.finditer(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?\n(.*?)\n\1\b",
                         command, re.S):
        parts.append(m.group(2))
    # A PowerShell here-string closes with its quote and @ at the start of a
    # line. The opening @ keeps the plain -m patterns from matching it.
    for m in re.finditer(r"@(['\"])\r?\n(.*?)\r?\n\1@", command, re.S):
        parts.append(m.group(2))
    return parts


def _dedupe(parts):
    """Drop a wrapper part, then an exact repeat.

    `--body "$(cat <<'EOF' ... EOF)"` gives the same prose two times: one time
    as the heredoc body, one time inside the quoted value that wraps it. The
    doubled text then scores against itself. A part that holds another part
    is the wrapper, so the inner part wins.
    """
    kept = []
    for index, part in enumerate(parts):
        stripped = part.strip()
        if not stripped:
            continue
        wraps = any(other.strip() and other.strip() != stripped
                    and other.strip() in part
                    for position, other in enumerate(parts) if position != index)
        if not wraps and stripped not in [k.strip() for k in kept]:
            kept.append(part)
    return kept


def _quoted_values(command, flags):
    """Each quoted value that one of `flags` carries."""
    parts = []
    names = "|".join(flags)
    for quote in ("'", '"'):
        pattern = r"(?:{})(?:\s+|=){}([^{}]*){}".format(names, quote, quote, quote)
        parts += [m.group(1) for m in re.finditer(pattern, command, re.S)]
    return parts


def commit_message(command, cwd=None):
    """The message text of a git commit command, or None.

    Covers -m arguments (single or double quoted), a bash heredoc body, a
    PowerShell here-string (@'...'@ or @"..."@), and a -F message file. An
    amend, fixup, or squash with no new message passes untouched.
    """
    # "git", then at most four arguments, then "commit". The lookbehind
    # stops a match inside ".git", so prose like "--exclude .git ... then
    # commit and push" cannot turn a non-commit command into a gated one.
    # The bounded chain still covers "git -c key=value commit".
    if not re.search(r"(?<![\w./-])git\s+(?:[^\s|;&]+\s+){0,4}commit\b", command):
        return None
    if re.search(r"--(?:no-edit|fixup|squash)\b", command):
        return None
    parts = _heredoc_bodies(command) + _quoted_values(command, ("-m",))
    from_file = _message_file(command, cwd)
    if from_file:
        parts.append(from_file)
    text = "\n\n".join(_dedupe(parts))
    return text or None


# "gh", then the object, then a subcommand that sends text. The lookbehind
# stops a match inside a path such as ./gh, and inside "high".
GH_COMMAND = re.compile(
    r"(?<![\w./-])gh\s+(?:[^\s|;&]+\s+){0,3}?"
    r"(?:pr|issue|release)\s+(?:create|edit|comment)\b")
GH_TEXT_FLAGS = ("--body", "-b", "--title", "-t", "--notes", "--message")
GH_FILE_FLAGS = ("--body-file", "-F", "--notes-file")


def gh_text(command, cwd=None):
    """The title and body of a gh pull request, issue, comment, or release.

    A pull request body reaches every reviewer and stays on the record. It
    goes out through the same shell tool as a commit message, so it meets the
    same gate. An edit that sends no new text passes untouched.
    """
    if not GH_COMMAND.search(command):
        return None
    parts = (_heredoc_bodies(command)
             + _quoted_values(command, GH_TEXT_FLAGS))
    from_file = _flag_file(command, cwd, GH_FILE_FLAGS)
    if from_file:
        parts.append(from_file)
    text = "\n\n".join(_dedupe(parts))
    return text or None


def elliptic_text(tool_input):
    parts = [v for k, v in (tool_input or {}).items()
             if k in TEXT_FIELDS and isinstance(v, str) and v.strip()]
    return "\n\n".join(parts) or None


def strip_noise(text):
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.M)
    text = re.sub(r"https?://\S+", " ", text)
    return text


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not LINT:
        return 0
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    if tool in SHELL_TOOLS:
        command = tool_input.get("command") or ""
        cwd = payload.get("cwd")
        text = commit_message(command, cwd)
        what = "commit message"
        retry = "run the same command again with the corrected message"
        if not text:
            text = gh_text(command, cwd)
            what = "pull request or issue text"
    elif tool.startswith("mcp__elliptic__"):
        text = elliptic_text(tool_input)
        what = "task text"
        retry = "make the same call again with the corrected text"
    else:
        return 0
    if not text:
        return 0

    prose = strip_noise(text)
    if len(prose.split()) < MIN_WORDS:
        return 0
    try:
        proc = subprocess.run([sys.executable, LINT], input=prose,
                              capture_output=True, text=True, timeout=15)
        report = json.loads(proc.stdout)
    except Exception:
        return 0                      # never block on a broken linter

    score = report.get("total_per100w", 0)
    shape_total = report.get("shape_total", 0)
    if score <= BLOCK_AT and shape_total <= SHAPE_BLOCK_AT:
        return 0

    hits = {k: v for k, v in (report.get("violations") or {}).items() if v}
    shape = {k: v for k, v in (report.get("shape") or {}).items() if v}
    longs = report.get("sample_long_sentence") or []
    reason = (
        "ASD-STE100 pre-send gate. The {} scored {:.2f} violations per 100 "
        "words. The ceiling is {}. Counts: {}. Shape counts: {}.{} "
        "Nothing was sent - this gate runs before the call. Rewrite the text "
        "in STE. Fix the listed categories. Keep every fact and every "
        "identifier. Then {}."
    ).format(what, score, BLOCK_AT, hits, shape,
             " Longest: {}.".format(" | ".join(longs)) if longs else "",
             retry)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
