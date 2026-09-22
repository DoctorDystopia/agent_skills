import re, sys, json, glob, os, bisect

# Score v2: adds complex_tense (perfect tenses, modal stacks), exempts
# adjectival/stative participles from the passive count, moves "provide" to the
# banned list, adds a noun-train marker and a --strict mode. The episode's
# published numbers were measured with score v1 (this file's git history at the
# episode date); v1 and v2 totals are close but not directly comparable.
SCORE_VERSION = 2

# Shape v1: the Layer 2 checks (skill 2.0). These count the ORDER of a reply to
# a person, not the words. They are reported apart from the score and never
# enter `total`, so `total_per100w` keeps one meaning across skill versions.
SHAPE_VERSION = 1

MARKETING = ["seamless","seamlessly","robust","powerful","cutting-edge","effortless","effortlessly",
    "world-class","next-generation","revolutionary","blazing","lightning-fast","elegant","delightful",
    "turnkey","best-in-class","state-of-the-art","game-changing","first-class","battle-tested",
    "enterprise-grade","supercharge","unlock","unleash","empower","empowers"]
BANNED = ["begin","begins","commence","commences","initiate","initiates","originate",
    "utilize","utilizes","utilizing","leverage","leverages","leveraging","facilitate","facilitates",
    "ensure","ensures","ensuring","prior to","subsequent to","obtain","obtains","acquire","acquires",
    "demonstrate","demonstrates","additionally","furthermore","moreover","comprehensive","comprehensively",
    "utilization","aforementioned","henceforth","therein","whilst","amongst","numerous","myriad","plethora",
    "provide","provides","provided",
    "in order to","a variety of","in the event that","due to the fact that","it is important to note"]
# STE's own recurring-errors list (see ste-recurring-errors.md). Counted only
# with --strict: these are correct STE but would flag normal prose in docs.
STRICT_BANNED = ["however","since","should","shall","using","follow","follows","followed"]
PHRASAL = ["spin up","spin down","reach out","dive into","dives into","diving into","kick off","kicks off",
    "roll out","rolls out","tear down","ramp up","circle back","drill down","spun up","reaching out"]
MODAL_HEDGE = ["it is important to note","it should be noted","it is worth noting","please note that",
    "as mentioned","as noted above"]
BE = r"(?:am|is|are|was|were|be|been|being)"
PP_IRREG = r"(?:done|made|sent|read|built|kept|held|set|put|run|written|shown|given|taken|found|got|gotten|seen|known|thrown|drawn)"
# Rule 3.3: a past participle used as an adjective is not passive. These
# stative participles only count as passive when a by-agent follows.
STATIVE = r"(?:closed|opened?|damaged|completed?|installed|connected|required|expected|configured|enabled|disabled|deprecated|supported)"
FUNC_WORDS = set("""a an the this that these those of for to in on at by with from as and or but if
when then than not no is are was were be been being am do does did has have had will would can could
may might must should shall it its their your our his her they we you i""".split())

# --- Layer 2 (shape) word lists -------------------------------------------
# An opener is counted in the first sentence only. Everything else is counted
# over the whole text.
OPENERS = ["great question","good question","let me","i'll","i will","sure","certainly",
    "absolutely","looking at your","to answer your question","happy to help",
    "i'd be happy to","that's a great","first,","alright","okay so","let's"]
CLOSERS = ["let me know if","hope this helps","hope that helps","happy to clarify",
    "feel free to ask","feel free to reach","anything else","if you have any questions",
    "if you have any other questions","i'm here to help","do not hesitate","don't hesitate"]
RECAP = ["to summarize","in summary","to recap","as a recap","in conclusion","to sum up",
    "i have now","i've now","overall,"]
# Only hedges that carry no fact. A qualifier that bounds a claim is not here.
HEDGE = ["perhaps","arguably","presumably","conceivably","ostensibly","somewhat",
    "kind of","sort of","more or less","it seems that","it appears that","fairly straightforward"]
VAGUE = ["some work","a bit of work","a while","shortly","fairly soon","a few moments",
    "not too long","some time","in no time","quite quick","pretty quick"]
SOFTENER = ["uh oh","oh no","there seems to be a problem","there seems to be an issue",
    "unfortunately","i apologize","apologies","my apologies","sorry about that"]

def strip_code(t):
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`[^`]*`", " ", t)
    return t


def _blank(match):
    """The matched text, with every character but a newline turned to a space."""
    return re.sub(r"[^\n]", " ", match.group(0))


def blank_code(t):
    """strip_code, but each removed character becomes a space.

    strip_code makes the text shorter, so an offset into its result no longer
    names a position in the file. The locator needs both things at one time:
    the same text that lint() scores, and a valid offset for every match. A
    blank of equal length gives both. A newline stays a newline, so the line
    number of each match stays correct.
    """
    t = re.sub(r"```.*?```", _blank, t, flags=re.S)
    t = re.sub(r"`[^`]*`", _blank, t)
    return t


def paragraphs(raw):
    """Split into paragraphs AFTER the fenced blocks are gone.

    A code block that holds a blank line used to be split first, which left two
    fragments with one fence each. strip_code matches a PAIR, so it removed
    neither, and every line of code then counted as a sentence. A config block
    with 9 blank lines scored 9 long paragraphs against 50 words of prose.
    A fence becomes a paragraph break, so the real paragraphs stay apart.
    """
    t = re.sub(r"```.*?```", "\n\n", raw, flags=re.S)
    t = re.sub(r"^[ \t]*```.*$", "\n", t, flags=re.M)   # a fence with no partner
    t = re.sub(r"`[^`]*`", " ", t)
    return [p for p in re.split(r"\n\s*\n", t) if p.strip()]

# A line that starts a new block: a heading, a list item, a table row, a quote.
BLOCK_START = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\||>)")


def unwrap(text):
    """Join hard-wrapped lines back into logical lines.

    Markdown wrapped at 80 columns puts one sentence on two or three lines.
    sentences() used to split on every newline, so a 40-word sentence counted
    as three short ones and a six-line paragraph counted as six sentences. A
    hard-wrapped doc then scored long_sentence near zero and long_paragraph
    high - both wrong. A line joins the line above it unless either one is
    blank, or the line starts a new block, or the line above is a heading or
    a table row.
    """
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        above = out[-1].strip() if out else ""
        joinable = (stripped and above and not BLOCK_START.match(line)
                    and not above.startswith(("#", "|")))
        if joinable:
            out[-1] = out[-1].rstrip() + " " + stripped
        else:
            out.append(line)
    return out


def sentences(text):
    out = []
    for line in unwrap(text):
        s = line.strip()
        if not s: continue
        s = re.sub(r"^\s*#{1,6}\s*", "", s)
        s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", s)
        if not s: continue
        parts = re.split(r"(?<=[.!?:])\s+(?=[A-Z0-9\"'\-])", s)
        for p in parts:
            p = p.strip()
            if p: out.append(p)
    return out

def wc(s):
    return len([w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-/]*", s)])

def count_ci(text, phrases):
    n = 0; hits = []
    low = text.lower()
    for ph in phrases:
        for m in re.finditer(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])", low):
            n += 1; hits.append(ph)
    return n, hits

def noun_trains(text):
    """Runs of 4+ consecutive non-function lowercase words (Rule 2.1 proxy).
    Heuristic marker only - proper nouns break a run, the leading word of each
    sentence is skipped, and the count stays out of the total."""
    hits = []
    for s in sentences(text):
        words = re.findall(r"[A-Za-z][A-Za-z'\-]*", s)[1:]
        run = []
        for w in words + [""]:
            if w and w.lower() not in FUNC_WORDS and not w[0].isupper():
                run.append(w)
            else:
                if len(run) >= 4: hits.append(" ".join(run))
                run = []
    return hits

def count_in(fragment, phrases):
    """Presence count over one fragment - each phrase counts at most one time."""
    low = fragment.lower().replace("’", "'")
    n = 0; hits = []
    for ph in phrases:
        if re.search(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])", low):
            n += 1; hits.append(ph)
    return n, hits


def long_lists(raw):
    """Runs of more than five consecutive list items (Layer 2 cap). A table row
    starts with a pipe, so a reference table never counts.

    Returns the START LINE of each over-long run. The caller counts them with
    len(), and the locator reads the line number. Give it blanked text, not
    stripped text, or a fenced block moves every line number after it.
    """
    starts = []
    run = 0
    first = 0
    for number, line in enumerate(raw.split("\n"), 1):
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            if not run: first = number
            run += 1
        elif not line.strip():
            continue
        elif run and line[:1].isspace():
            continue          # an indented continuation of the item above
        else:
            if run > 5: starts.append(first)
            run = 0
    if run > 5: starts.append(first)
    return starts


def shape(raw):
    """Layer 2 counts. Applies to a reply to a person, not to a reference doc."""
    text = strip_code(raw).replace("’", "'")
    sents = sentences(text)
    s = {}
    s["preamble_opener"] = count_in(sents[0], OPENERS)[0] if sents else 0
    s["closer"], ch = count_ci(text, CLOSERS)
    s["recap_marker"], rh = count_ci(text, RECAP)
    s["hedge"], hh = count_ci(text, HEDGE)
    s["vague_estimate"], vh = count_ci(text, VAGUE)
    s["error_softener"], sh = count_ci(text, SOFTENER)
    s["action_list(>5)"] = len(long_lists(blank_code(raw)))
    return s, list(dict.fromkeys(ch + rh + hh + vh + sh))[:6]


def lint(text, strict=False):
    raw = text
    text = strip_code(text)
    sents = sentences(text)
    words = sum(wc(s) for s in sents) or 1
    v = {}
    longs = [(wc(s), s) for s in sents if wc(s) > 20]
    v["long_sentence(>20w)"] = len(longs)
    v["semicolon"] = text.count(";")
    v["contraction"] = len(re.findall(r"\b\w+['’](?:t|re|ve|ll|d|s|m)\b", text))
    passive_parts = re.findall(rf"\b{BE}\s+(\w+ed|{PP_IRREG})\b", text, re.I)
    v["passive_voice"] = sum(1 for p in passive_parts if not re.fullmatch(STATIVE, p, re.I)) \
        + len(re.findall(rf"\b{BE}\s+{STATIVE}\s+by\b", text, re.I))
    v["complex_tense"] = len(re.findall(
        rf"\b(?:(?:may|might|could|would|should|must|will|shall|can)\s+)?(?:have|has|had)\s+(?:been\s+)?(?:\w+ed|{PP_IRREG})\b",
        text, re.I))
    v["ing_main_verb"] = len(re.findall(rf"\b{BE}\s+\w+ing\b", text, re.I))
    v["nominalization"] = len(re.findall(r"\b(?:perform(?:s|ed)?|conduct(?:s|ed)?|carry out|carries out|make use of|makes use of)\b", text, re.I)) + len(re.findall(r"\b\w{4,}(?:tion|ment|ance|ence)\s+of\b", text, re.I))
    v["phrasal_verb"], _ = count_ci(text, PHRASAL)
    v["banned_word"], bh = count_ci(text, BANNED)
    v["marketing_adjective"], mh = count_ci(text, MARKETING)
    v["modal_hedge"], _ = count_ci(text, MODAL_HEDGE)
    v["long_paragraph(>6s)"] = sum(1 for p in paragraphs(raw) if len(sentences(p)) > 6)
    em = raw.count("—") + raw.count("–")
    trains = noun_trains(text)
    if strict:
        n_strict, sh = count_ci(text, STRICT_BANNED)
        # "may" is matched case-sensitively so the month "May" stays clean
        n_strict += len(re.findall(r"(?<![A-Za-z])may(?![a-z])", text))
        v["strict_banned_word"] = n_strict
        v["em_dash"] = em
    total = sum(v.values())
    sh, sh_samples = shape(raw)
    return {
        "score_version": SCORE_VERSION,
        "shape_version": SHAPE_VERSION,
        "mode": "strict" if strict else "flavored",
        "words": words, "sentences": len(sents),
        "violations": v, "total": total,
        "total_per100w": round(total*100.0/words, 2),
        "shape": sh, "shape_total": sum(sh.values()),
        "sample_shape": sh_samples,
        "em_dash(slop-marker)": em,
        "noun_train(>=4w,marker)": len(trains),
        "longest_sentence_words": (max(longs)[0] if longs else max((wc(s) for s in sents), default=0)),
        "sample_marketing": list(dict.fromkeys(mh))[:6],
        "sample_banned": list(dict.fromkeys(bh))[:6],
        "sample_noun_train": trains[:3],
        "sample_long_sentence": ["{}w: {}".format(n, s[:70]) for n, s in
                                 sorted(longs, key=lambda x: -x[0])[:2]],
    }

# --- the locator -----------------------------------------------------------
# A summary says "passive_voice 7". It does not say where, and it does not say
# what to do. An agent that must fix a file therefore reads THIS file to learn
# what each category matches, then greps the regexes by hand. --verbose ends
# that: one row for each hit, with its line, and one help line for each
# category that fired.

RULE_HELP = {
    "long_sentence(>20w)": "Split it. An instruction gets 20 words. Any other sentence gets 25.",
    "semicolon": "Make two sentences. STE has no semicolon.",
    "contraction": "Write the two words in full: do not, it is, you are.",
    "passive_voice": 'Name the actor. Write "the hook reads the flag", not "the flag is read".',
    "complex_tense": "Use a simple tense. Write \"the run failed\", not \"the run has failed\".",
    "ing_main_verb": 'Use a simple tense. Write "the gate lints it", not "the gate is linting it".',
    "nominalization": 'Use the verb. Write "analyze the log", not "perform an analysis".',
    "phrasal_verb": 'Use one verb: start, stop, remove, increase, read, ask.',
    "banned_word": "Use the short common word. STE approves one word for one meaning.",
    "marketing_adjective": "Delete it, or give the number it stands for.",
    "modal_hedge": "Delete the hedge. State the fact.",
    "long_paragraph(>6s)": "Break the paragraph. Six sentences is the cap.",
    "strict_banned_word": "Strict mode. Replace it with the STE word for that meaning.",
    "em_dash": "Use a comma, a colon, or a full stop.",
    "em_dash(slop-marker)": "Marker only. Use a comma, a colon, or a full stop.",
    "noun_train(>=4w,marker)": "Marker only. A noun cluster gets three words at most.",
    "preamble_opener": "Delete the opener. Start with the action, the command, or the path.",
    "closer": "Delete the closer. Stop when the answer is done.",
    "recap_marker": "Delete the recap. The reader read it one screen above.",
    "hedge": "Cut a hedge that carries no fact. Keep a qualifier that bounds a claim.",
    "vague_estimate": "Give minutes, hours, or days.",
    "error_softener": "Report the error flat: the cause, then the fix.",
    "action_list(>5)": "Cap an action list at five items. A reference table has no cap.",
}

_SHORT_SAMPLE = 30      # widen a sample this short with its whole line
_SAMPLE_CHARS = 110


def _line_map(text):
    """The start offset of each line, for a binary search by offset."""
    starts = [0]
    for m in re.finditer(r"\n", text):
        starts.append(m.end())
    return starts


def _line_at(starts, offset):
    return bisect.bisect_right(starts, offset)


def _fragment_line(text, starts, fragment, words=6):
    """The line where a sentence or a paragraph starts, or None.

    A hard wrap and a bold label both put characters between two words that
    the sentence splitter already removed. The needle therefore joins the
    first few words with a tolerant separator.
    """
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-/]*", fragment)[:words]
    floor = min(2, len(tokens))       # one common word matches anywhere
    while len(tokens) >= floor and tokens:
        needle = r"[^A-Za-z0-9]{0,8}".join(re.escape(t) for t in tokens)
        m = re.search(needle, text)
        if m:
            return _line_at(starts, m.start())
        tokens = tokens[:-1]          # a separator the needle cannot cross
    return None


def _phrase_hits(text, phrases):
    """(offset, matched text) for each phrase, with count_ci's word bounds."""
    for ph in phrases:
        for m in re.finditer(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])",
                             text, re.I):
            yield m.start(), m.group(0)


def locate(raw, strict=False):
    """One row for each violation: its line, its category, and its text.

    lint() owns the counts. This owns the POSITION, which a total cannot give.
    Both read the same blanked text, so a category here counts the same hits
    as the same category there. tests/test_verbose.py asserts that.
    """
    text = blank_code(raw)
    shape_text = text.replace("’", "'")     # same length, so offsets hold
    starts = _line_map(text)
    raw_lines = raw.split("\n")
    rows = []

    def add(line, category, sample, layer=1):
        """A row keeps the matched words. A short match also gets its line.

        "is allowed" on its own does not say which sentence to rewrite. The
        line on its own does not say which words fired. A short match shows
        both, with the match first.
        """
        sample = " ".join(sample.split())
        if len(sample) < _SHORT_SAMPLE and line and line <= len(raw_lines):
            context = " ".join(raw_lines[line - 1].split())
            if context:
                sample = "{}  |  {}".format(sample, context)
        rows.append({"line": line, "category": category,
                     "text": sample[:_SAMPLE_CHARS], "layer": layer})

    def add_at(offset, category, sample, layer=1):
        add(_line_at(starts, offset), category, sample, layer)

    # Layer 1, by sentence and by paragraph.
    for s in sentences(text):
        n = wc(s)
        if n > 20:
            add(_fragment_line(text, starts, s), "long_sentence(>20w)",
                "{}w: {}".format(n, s))
    for p in paragraphs(raw):
        inner = sentences(p)
        if len(inner) > 6:
            add(_fragment_line(text, starts, p), "long_paragraph(>6s)",
                "{} sentences: {}".format(len(inner), inner[0]))

    # Layer 1, by pattern. The patterns mirror lint(), one for one.
    patterns = [
        ("semicolon", r";", 0),
        ("contraction", r"\b\w+['’](?:t|re|ve|ll|d|s|m)\b", 0),
        ("complex_tense",
         r"\b(?:(?:may|might|could|would|should|must|will|shall|can)\s+)?"
         r"(?:have|has|had)\s+(?:been\s+)?(?:\w+ed|" + PP_IRREG + r")\b", re.I),
        ("ing_main_verb", r"\b" + BE + r"\s+\w+ing\b", re.I),
        ("nominalization",
         r"\b(?:perform(?:s|ed)?|conduct(?:s|ed)?|carry out|carries out|"
         r"make use of|makes use of)\b", re.I),
        ("nominalization", r"\b\w{4,}(?:tion|ment|ance|ence)\s+of\b", re.I),
    ]
    for category, pattern, flags in patterns:
        for m in re.finditer(pattern, text, flags):
            add_at(m.start(), category, m.group(0))

    for m in re.finditer(r"\b" + BE + r"\s+(\w+ed|" + PP_IRREG + r")\b",
                         text, re.I):
        if not re.fullmatch(STATIVE, m.group(1), re.I):
            add_at(m.start(), "passive_voice", m.group(0))
    for m in re.finditer(r"\b" + BE + r"\s+" + STATIVE + r"\s+by\b", text, re.I):
        add_at(m.start(), "passive_voice", m.group(0))

    for category, phrases in (("phrasal_verb", PHRASAL),
                              ("banned_word", BANNED),
                              ("marketing_adjective", MARKETING),
                              ("modal_hedge", MODAL_HEDGE)):
        for offset, hit in _phrase_hits(text, phrases):
            add_at(offset, category, hit)

    if strict:
        for offset, hit in _phrase_hits(text, STRICT_BANNED):
            add_at(offset, "strict_banned_word", hit)
        for m in re.finditer(r"(?<![A-Za-z])may(?![a-z])", text):
            add_at(m.start(), "strict_banned_word", m.group(0))
        for m in re.finditer(r"[—–]", raw):
            add_at(m.start(), "em_dash", m.group(0))
    else:
        for m in re.finditer(r"[—–]", raw):
            add_at(m.start(), "em_dash(slop-marker)", m.group(0))

    for train in noun_trains(text):
        add(_fragment_line(text, starts, train, words=4),
            "noun_train(>=4w,marker)", train)

    # Layer 2, the reply shape.
    first = sentences(shape_text)[:1]
    if first:
        for ph in OPENERS:
            m = re.search(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])",
                          first[0], re.I)
            if m:
                add(_fragment_line(text, starts, first[0]),
                    "preamble_opener", m.group(0), layer=2)
    for category, phrases in (("closer", CLOSERS), ("recap_marker", RECAP),
                              ("hedge", HEDGE), ("vague_estimate", VAGUE),
                              ("error_softener", SOFTENER)):
        for offset, hit in _phrase_hits(shape_text, phrases):
            add_at(offset, category, hit, layer=2)
    for line in long_lists(text):
        add(line, "action_list(>5)", "a list of more than five items", layer=2)

    # A row with no line goes last. The reader cannot act on it as quickly.
    rows.sort(key=lambda r: (r["line"] is None, r["line"] or 0, r["layer"],
                             r["category"]))
    return rows


def format_rows(rows, indent="  ", note=None, legend_rows=None):
    """The verbose block: one row for each hit, then the rules that fired.

    legend_rows names the rules. It holds every row even when --max-rows cut
    the printed list, so a capped report still tells the reader what to fix.
    """
    out = []
    for r in rows:
        where = "L{}".format(r["line"]) if r["line"] else "L?"
        out.append("{}{:>6}  {:<24} {}".format(indent, where, r["category"],
                                               r["text"]))
    if note:
        out.append("{}{}".format(indent, note))
    fired = list(dict.fromkeys(r["category"] for r in
                               (rows if legend_rows is None else legend_rows)))
    if fired:
        out.append("{}rules that fired".format(indent))
        for category in fired:
            out.append("{}  {:<24} {}".format(
                indent, category, RULE_HELP.get(category, "")))
    return "\n".join(out)


# --- source files ----------------------------------------------------------
# A .py or a .gd file is code with prose inside it. ste_extract takes the
# prose out and keeps every line number, so the score reads the docstrings and
# the comments alone. Without it, `def _parse(self, raw):` scores as prose.

def _load_extractor():
    """ste_extract, or None when it does not sit beside this file."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "ste_extract.py")
    if not os.path.exists(path):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("ste_extract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXTRACT = _load_extractor()


def read_prose(path, text):
    """The text to score, and True when it came out of a source file."""
    if EXTRACT is None:
        return text, False
    prose = EXTRACT.extract(path, text)
    if prose is None:
        return text, False
    return prose, True


USAGE = """ste-lint.py - ASD-STE100 violations per 100 words.

  ste-lint.py FILE...            flavored mode. The target is 2.5 per 100 words
  ste-lint.py --strict FILE      strict mode, for a procedure or an error message
  ste-lint.py --verbose FILE     add one row for each hit: line, rule, text
  ste-lint.py --shape FILE       add the Layer 2 reply-shape total
  ste-lint.py --json FILE        machine-readable. --verbose adds a "hits" list
  ste-lint.py --fail-over 2.5 F  exit 1 over the threshold, for a gate
  ste-lint.py --fail-shape 2 F   exit 1 over the Layer 2 total
  ste-lint.py --max-rows 200 F   cap the verbose rows for one file
  ste-lint.py module.py          a .py or .gd file: the docstrings and comments
  ste-lint.py --raw module.py    score the whole file instead, code included
  cat draft.md | ste-lint.py     read one text from stdin

A .py, .pyi or .gd file gives its prose only, and each line number still names
the real line. Read --verbose before you read this file. It names each rule
that fired and gives one line on how to fix it."""

FLAGS = ("--strict", "--json", "--shape", "--verbose", "-v", "--help", "-h",
         "--raw")
DEFAULT_MAX_ROWS = 200


def _report(name, r, rows, show_shape, verbose, max_rows):
    """Print one file's summary line, then its rows when verbose is on."""
    tail = " shape={:2d}".format(r["shape_total"]) if show_shape else ""
    print("{:32} words={:4d} total={:3d} per100w={:6.2f} em_dash={:2d}{}".format(
        name[:32], r["words"], r["total"], r["total_per100w"],
        r["em_dash(slop-marker)"], tail))
    if not verbose:
        return
    if not rows:
        print("  no hits\n")
        return
    shown = rows[:max_rows]
    note = None
    if len(rows) > len(shown):
        note = "... {} more rows. Raise --max-rows to see them.".format(
            len(rows) - len(shown))
    print(format_rows(shown, note=note, legend_rows=rows))
    print("")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(USAGE)
        sys.exit(0)
    strict = "--strict" in args
    as_json = "--json" in args
    show_shape = "--shape" in args
    verbose = "--verbose" in args or "-v" in args
    raw_mode = "--raw" in args
    fail_over = None
    fail_shape = None
    max_rows = DEFAULT_MAX_ROWS
    for flag in ("--fail-over", "--fail-shape", "--max-rows"):
        if flag in args:
            i = args.index(flag)
            value = float(args[i + 1])
            if flag == "--fail-over": fail_over = value
            elif flag == "--fail-shape": fail_shape = value
            else: max_rows = int(value)
            del args[i:i + 2]
    files = [a for a in args if a not in FLAGS]
    worst = 0.0
    worst_shape = 0

    def run(name, raw):
        """Lint one text. Returns its report, so the caller tracks the worst."""
        r = lint(raw, strict=strict)
        rows = locate(raw, strict=strict) if verbose else []
        if as_json:
            payload = {"file": name, **r}
            if verbose:
                payload["hits"] = rows
                payload["rule_help"] = {c: RULE_HELP.get(c, "") for c in
                                        dict.fromkeys(x["category"] for x in rows)}
            print(json.dumps(payload, indent=2))
        else:
            _report(name, r, rows, show_shape, verbose, max_rows)
        return r

    if not files:
        sys.stdin.reconfigure(encoding="utf-8")
        raw = sys.stdin.read()
        if as_json or not verbose:
            # stdin with no --verbose keeps the old contract: the whole report
            # as JSON. Every hook reads that shape.
            r = lint(raw, strict=strict)
            payload = dict(r)
            if verbose:
                rows = locate(raw, strict=strict)
                payload["hits"] = rows
                payload["rule_help"] = {c: RULE_HELP.get(c, "") for c in
                                        dict.fromkeys(x["category"] for x in rows)}
            print(json.dumps(payload, indent=2))
        else:
            r = lint(raw, strict=strict)
            _report("<stdin>", r, locate(raw, strict=strict), show_shape,
                    verbose, max_rows)
        worst = r["total_per100w"]
        worst_shape = r["shape_total"]
    else:
        exp = []
        for f in files: exp += sorted(glob.glob(f)) if any(c in f for c in "*?[") else [f]
        for f in exp:
            with open(f, encoding="utf-8", errors="replace") as fh: raw = fh.read()
            label = f if as_json else os.path.basename(f)
            if not raw_mode:
                raw, from_source = read_prose(f, raw)
                if from_source:
                    label = "{} (prose)".format(label)
            r = run(label, raw)
            worst = max(worst, r["total_per100w"])
            worst_shape = max(worst_shape, r["shape_total"])
    if fail_over is not None and worst > fail_over:
        sys.exit(1)
    if fail_shape is not None and worst_shape > fail_shape:
        sys.exit(1)
