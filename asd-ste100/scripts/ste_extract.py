"""Extract the prose from a source file, and keep every line number.

The linter reads a whole file, so the code around a docstring enters the
count. `def _parse(self, raw):` scores as prose. A gate on that number fires
on clean code and stays silent on bad prose. This module takes the prose out
first.

The output holds ONE LINE FOR EACH LINE of the source. A line that carries
prose keeps its text, at its own column. Every other line becomes empty. Two
things follow, and both matter:

1. A line number in the report names the real line in the source file.
2. A blank line separates two prose blocks that sit apart in the file, so the
   linter never joins a docstring to a comment 40 lines below it.

The second point is the reason this does not simply concatenate the strings.
The linter joins hard-wrapped lines into one sentence, which is correct inside
one docstring and wrong between two.

What counts as prose:

- Python  a module, class, or function docstring, and a `#` comment
- GDScript  a `##` doc comment and a `#` comment

What does not:

- A shebang line
- A tool directive, such as `# type: ignore` or `# noqa`
- Anything the parser cannot read. A file with a syntax error gives back the
  comments alone, because tokenize reads further than ast does.
"""
import ast
import io
import os
import re
import tokenize

# The file types this module reads. A suffix that is absent gives back None,
# and the caller then treats the file as prose or skips it.
SOURCE_SUFFIXES = {
    ".py": "python",
    ".pyi": "python",
    ".gd": "gdscript",
}

# A comment that carries an instruction to a tool, not a sentence to a person.
DIRECTIVE = re.compile(
    r"^\s*(?:type:|noqa|pylint:|pragma:|fmt:|isort:|mypy:|ruff:|flake8:|"
    r"coding[:=]|-\*-|!)", re.I)
# A docstring line starts and ends with quotes, and may carry a string prefix.
_OPEN_QUOTE = re.compile(r'^(\s*)[rubfRUBF]{0,2}("""|\'\'\'|"|\')')
_CLOSE_QUOTE = re.compile(r'("""|\'\'\'|"|\')\s*$')
_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def suffix_kind(path):
    """The language of this path, or None when the module does not read it."""
    return SOURCE_SUFFIXES.get(os.path.splitext(path)[1].lower())


def _comment_body(token_text):
    """The sentence inside a `#` comment, or None for a directive."""
    body = token_text.lstrip("#").lstrip("!")
    if DIRECTIVE.match(token_text.lstrip("#")):
        return None
    stripped = body.strip()
    if not stripped:
        return None
    # A ruler such as "# ----- main -----" is a divider, not a sentence.
    if not re.search(r"[A-Za-z]{3}", stripped):
        return None
    return body


def _isolate(body, code_before):
    """One comment, marked so the linter cannot join it to its neighbour.

    A trailing comment is a label on one line of code:

        EVERY = 12          # tool calls between two cards
        TARGET = 2.5        # flavored target for a written prose file
        MIN_WORDS = 40      # skip a stub file

    Three labels are not a paragraph. The linter joins hard-wrapped lines, so
    it read those three as one 22-word sentence and reported a long sentence
    that nobody wrote. A leading pipe stops the join on both sides, because
    the linter treats a table row as its own block. It costs no word, because
    a pipe is not a word.

    A comment that stands on its own line keeps no mark. A block of those IS a
    paragraph, and the join is correct there.
    """
    return "| " + body if code_before else body


def _strip_quotes(line):
    """One docstring line, with its opening and closing quotes removed."""
    without_open = _OPEN_QUOTE.sub(r"\1", line)
    return _CLOSE_QUOTE.sub("", without_open)


def _python_comments(text, out):
    """Write each comment into out. Reads a file that ast cannot parse."""
    try:
        reader = io.StringIO(text).readline
        for token in tokenize.generate_tokens(reader):
            if token.type != tokenize.COMMENT:
                continue
            row, column = token.start
            if row == 1 and token.string.startswith("#!"):
                continue
            body = _comment_body(token.string)
            if body and row <= len(out):
                code_before = bool(token.line[:column].strip())
                out[row - 1] = " " * column + _isolate(body.strip(), code_before)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        pass


def _python_docstrings(text, lines, out):
    """Write each docstring into out, one source line for each source line."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        start = value.lineno
        end = getattr(value, "end_lineno", start) or start
        for row in range(start, min(end, len(lines)) + 1):
            out[row - 1] = _strip_quotes(lines[row - 1])


def _python(text):
    lines = text.split("\n")
    out = [""] * len(lines)
    _python_comments(text, out)
    _python_docstrings(text, lines, out)
    return "\n".join(out)


def _hash_comments(text):
    """Every `#` and `##` line of a GDScript file, at its own line number.

    GDScript has no docstring. A `##` comment above a declaration is its
    documentation, and a `#` comment is an ordinary note. Both are prose.
    A `#` inside a string literal is not, so a line whose comment mark sits
    inside quotes is skipped.
    """
    out = []
    for line in text.split("\n"):
        mark = _comment_column(line)
        if mark is None:
            out.append("")
            continue
        body = _comment_body(line[mark:])
        if not body:
            out.append("")
            continue
        code_before = bool(line[:mark].strip())
        out.append(" " * mark + _isolate(body.strip(), code_before))
    return "\n".join(out)


def _comment_column(line):
    """The column of the comment mark, or None when the line has no comment."""
    quote = None
    for column, character in enumerate(line):
        if quote:
            if character == quote:
                quote = None
            continue
        if character in "\"'":
            quote = character
        elif character == "#":
            return column
    return None


def extract(path, text):
    """The prose of one source file, or None when the type is not supported.

    The result holds the same number of lines as the source.
    """
    kind = suffix_kind(path)
    if kind == "python":
        return _python(text)
    if kind == "gdscript":
        return _hash_comments(text)
    return None
