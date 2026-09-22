"""List ASD-STE100 lint hits in a markdown file, one row for each sentence.

Usage: python ste_locate.py LINT_PATH FILE [SECTION_SUBSTRING]

The linter reports counts for a whole file. A review table needs the
sentence and its line. This script walks the file block by block, splits
each block into sentences, and runs the linter checks on each sentence.

Word count follows rule 8.6: an inline code span counts as one word. The
cap is 20 words for a sentence that starts with a command verb, 25 for any
other sentence (rules 5.1 and 6.3). Tables and fenced blocks are skipped.
A possessive "'s" is not a contraction (GR-8), but "it's" and its kind are.

Version 2: a sentence break after a bold label ("**Label.** Next") now
splits, and an "-ing" word as the first word of a sentence is reported
(rule 3.5). The linter misses both.
"""
import importlib.util
import re
import sys

IMPERATIVE_CAP = 20
DESCRIPTIVE_CAP = 25
PARAGRAPH_CAP = 6
MIN_ING_SUBJECT_LENGTH = 5
COMMAND_VERBS = {"always", "never", "do", "use", "run", "read", "check",
                 "write", "add", "put", "keep", "pass", "inherit", "assert",
                 "wrap", "inject", "declare", "lint", "change", "apply",
                 "make", "treat", "exclude"}
ING_NOT_VERBS = {"during", "nothing", "something", "everything", "anything",
                 "string", "thing", "things", "morning", "king"}
SKIP_CATEGORIES = {"long_sentence(>20w)", "long_paragraph(>6s)",
                   "ing_main_verb"}
SPLIT = re.compile(r"(?:(?<=[.!?])|(?<=[.!?]\*\*)|(?<=[.!?]\*))\s+"
                   r"(?=[\"'(*`A-Z0-9])")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
PRONOUN_CONTRACTION = re.compile(
    r"\b(?:it|that|there|what|here|who|let|he|she)['’]s\b", re.I)


def load_lint(path):
    spec = importlib.util.spec_from_file_location("ste_lint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blocks(lines):
    """Yield (section, first_line, is_list_item, text) for each prose block."""
    section = ""
    in_fence = False
    buffer = []
    start = 0
    is_item = False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            if buffer:
                yield section, start, is_item, " ".join(buffer)
            buffer = []
            continue
        if in_fence:
            continue
        ends_block = (not stripped or stripped.startswith(("#", "|", ">"))
                      or LIST_ITEM.match(line))
        if ends_block and buffer:
            yield section, start, is_item, " ".join(buffer)
            buffer = []
        if stripped.startswith("#"):
            section = stripped.lstrip("# ")
            continue
        if not stripped or stripped.startswith("|"):
            continue
        if not buffer:
            start = number
            is_item = bool(LIST_ITEM.match(line))
        buffer.append(LIST_ITEM.sub("", stripped) if not buffer else stripped)
    if buffer:
        yield section, start, is_item, " ".join(buffer)


def sentence_hits(lint, sentence):
    counted = re.sub(r"`[^`]*`", "CODE", sentence)
    words = lint.wc(counted)
    first = re.sub(r"^[*_\s]+", "", counted).split(" ", 1)[0].lower()
    first = first.strip(",:;.")
    cap = IMPERATIVE_CAP if first in COMMAND_VERBS else DESCRIPTIVE_CAP
    hits = []
    if words > cap:
        hits.append("length {}>{}".format(words, cap))
    if (first.endswith("ing") and len(first) >= MIN_ING_SUBJECT_LENGTH
            and first not in ING_NOT_VERBS):
        hits.append("ing_subject")
    report = lint.lint(sentence)
    for category, count in report["violations"].items():
        if count and category not in SKIP_CATEGORIES:
            hits.append(category)
    prose = lint.strip_code(sentence)
    possessives = (len(re.findall(r"\b\w+['’]s\b", prose))
                   - len(PRONOUN_CONTRACTION.findall(prose)))
    if "contraction" in hits and report["violations"]["contraction"] <= possessives:
        hits.remove("contraction")
    if "—" in sentence:
        hits.append("em_dash")
    return hits


def main():
    lint = load_lint(sys.argv[1])
    lines = open(sys.argv[2], encoding="utf-8").read().split("\n")
    only = sys.argv[3] if len(sys.argv) > 3 else None
    per_section = {}
    for section, start, is_item, text in blocks(lines):
        if only and only not in section:
            continue
        sentences = [s for s in SPLIT.split(text) if s.strip()]
        if not is_item and len(sentences) > PARAGRAPH_CAP:
            print("L{}\t[{}]\tparagraph {} sentences".format(
                start, section, len(sentences)))
        for sentence in sentences:
            hits = sentence_hits(lint, sentence)
            if hits:
                per_section[section] = per_section.get(section, 0) + 1
                print("L{}\t[{}]\t{}\t{}".format(
                    start, section, ", ".join(hits), sentence))
    print("\n== flagged sentences by section")
    for section, count in per_section.items():
        print("{:4d}  {}".format(count, section))


if __name__ == "__main__":
    main()
