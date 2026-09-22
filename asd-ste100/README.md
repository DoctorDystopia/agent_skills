# asd-ste100

[![skills.sh](https://skills.sh/b/woosal1337/blog)](https://www.skills.sh/woosal1337/blog/asd-ste100)

Listed at [skills.sh/woosal1337/blog/asd-ste100](https://www.skills.sh/woosal1337/blog/asd-ste100).

An agent skill that removes AI slop with a writing system, not a banned-word
list. Layer 1 rewrites the words into ASD-STE100 Simplified Technical English,
the controlled language built in the 1980s so an aircraft mechanic could never
misread a repair manual. Layer 2 shapes the reply for a reader with ADHD: the
next action first, numbered steps, real time estimates, no preamble and no
closer.

The claim behind it was tested: six engineering writing tasks, four
conditions, two model families, scored as violations per 100 words.

| Condition | Claude sonnet | gpt-5.5 |
|---|---|---|
| baseline | 4.36 | 3.54 |
| banned-words list | 4.21 (-3%) | 2.14 (-40%) |
| Orwell's six rules | 2.48 (-43%) | 1.69 (-52%) |
| **this skill** | **1.12 (-74%)** | **1.76 (-50%)** |

The full experiment, the data, and the 17-minute episode:
[chele.bi/videos/the-cure-for-ai-slop](https://chele.bi/videos/the-cure-for-ai-slop)

## This repository is the source

`~/.claude/skills/asd-ste100` is a COPY that `install.py` writes. Make each
change here, then run the script. An edit made in the copy is lost on the next
run:

```
python install.py --check      # name each file where the two disagree
python install.py              # copy, then arm the hooks
```

## Install

Pick one route. Do not stack them: two routes register every hook two times.

**Route 1, the plugin.** Clone this repository into your skills directory.
Claude Code reads `.claude-plugin/plugin.json`, loads it as
`asd-ste100@skills-dir`, and registers `hooks/hooks.json` itself. It edits no
settings file:

```
git clone <this repo> "$HOME/.claude/skills/asd-ste100"
```

Start a new session. `claude plugin list` names it. `claude plugin validate .`
checks the manifest. Use this route on a machine that holds no copy yet.

**Route 2, the settings file.** `install.py` copies the skill and writes five
hook entries into `~/.claude/settings.json`. The copy carries no
`.claude-plugin`, so the plugin route stays off and the two cannot stack:

```
python install.py
```

Use this route when the source lives outside the skills directory, as it does
on the machine that this repository was built on.

**Route 3, no tooling.** Paste `SKILL.md` into the system prompt. The skill
works without the linter. The linter closes the loop.

## Layout

The folder follows the [Agent Skills spec](https://agentskills.io) and the
Claude Code plugin format at the same time:

```
SKILL.md                     the skill - name, description, the two layers
scripts/ste-lint.py          executable code, per the spec convention
references/ste-recurring-errors.md   docs loaded on demand
hooks/hooks.json             the plugin's hook declarations
hooks/run-python.cjs         cross-platform Python 3 launcher
hooks/ste-*.py               the four hook programs
tests/                        the unit tests - run them before you change a pattern
.claude-plugin/plugin.json   the plugin manifest. install.py never copies it
install.py, output-style.md  the settings route, for non-plugin installs
```

Run the tests before you change a pattern or a word list. They take under one
second:

```
python -m unittest discover -s tests -p "test_*.py"
```

## What the enforcement stack adds

A skill is advisory. The model can forget it on a long turn. `install.py`
therefore arms every deterministic layer Claude Code offers. It copies the
skill, adds five hook entries to `~/.claude/settings.json`, and backs the old
file up first. A second run repairs the install. `--uninstall` removes exactly
what it added.

The hook commands use `hooks/run-python.cjs`. On Windows, it first tries the
Python launcher and `python`. On macOS and Linux, it first tries `python3`.

| Layer | File | When it fires | What it guarantees |
|---|---|---|---|
| style | `output-style.md` | every request | the rule sits in the system prompt |
| card | `hooks/ste-inject.py` | every user turn | the rule enters context, with the last score |
| refresh | `hooks/ste-refresh.py` | every 12 tool calls | the rule stays near the reply on a long turn |
| pre-send | `hooks/ste-pregate.py` | before a commit or a `gh` command runs | a sloppy commit message or pull request body never lands |
| file check | `hooks/ste-refresh.py` | after a Write of a prose file | a written doc gets its score in the same turn |
| source check | `hooks/ste-refresh.py` | after a Write or Edit of a `.py` or `.gd` file | a docstring the edit wrote gets its score |
| gate | `hooks/ste-gate.py` | when the reply ends | every finished reply is linted |
| subagent gate | `hooks/ste-gate.py` | when a subagent ends | a report to the parent agent is linted too |

The gate keeps three bands. A clean reply passes in silence. A reply over the
target gets its score shown on the next turn. Only a reply over a hard
ceiling forces one rewrite, one time per turn.

A subagent gets the block instead of the warning. The three bands exist only
because a block costs a second copy of the reply on the reader's screen. A
subagent writes to its parent agent, so that cost does not exist there.

`install.py` arms every row but the style. A custom output style replaces the
default coding instructions, so the installer leaves that choice to you. The
rule card and the skill carry the same words into context without that cost.

## The linter

```
node hooks/run-python.cjs scripts/ste-lint.py draft.md            # flavored: general prose, target under 2.5
node hooks/run-python.cjs scripts/ste-lint.py --strict draft.md   # strict: procedures and error messages
node hooks/run-python.cjs scripts/ste-lint.py --shape draft.md    # add the Layer 2 reply-shape counts
node hooks/run-python.cjs scripts/ste-lint.py --verbose draft.md  # one row for each hit: line, rule, text
node hooks/run-python.cjs scripts/ste-lint.py --help              # every flag
```

The score is violations per 100 words. `--json` gives machine-readable
output. `--fail-over N` exits 1 over the threshold, for CI gates and hooks.
The linter uses only the Python 3 standard library. The launcher has no Node
package dependencies.

### --verbose

A count is not an instruction. `passive_voice 7` does not say which sentence
to rewrite, and a category name does not say what the category matches. An
agent that gets only a summary opens `ste-lint.py` and reads the regexes,
which costs a long detour for a short fix.

`--verbose` gives the line of each hit, the words that fired it, and one line
for each rule on how to fix it:

```
style.md                         words= 971 total= 25 per100w=  2.57 em_dash= 0
      L7  passive_voice            be followed  |  These guidelines must be followed from the outset.
     L49  banned_word              comprehensive
     L67  semicolon                ;  |  Do not butt parameters up against a keyword; leave a space.
  rules that fired
    passive_voice            Name the actor. Write "the hook reads the flag", not "the flag is read".
    banned_word              Use the short common word. STE approves one word for one meaning.
    semicolon                Make two sentences. STE has no semicolon.
```

A match under 30 characters also shows its line, because the words alone do
not say which sentence they came from. `--max-rows N` caps the rows for one
file, and the rule list stays complete under the cap. `--verbose --json` puts
the same rows under `hits` and the help text under `rule_help`. A row with no
line prints `L?` and sorts last.

`lint()` counts. `locate()` finds the position of each count. The two hold two
copies of each pattern, so `tests/test_verbose.py` asserts that every category
reports the same number both ways, over a fixture and over this folder's own
prose. A change to one copy alone fails that test.

### Source files

A `.py`, `.pyi` or `.gd` file gives its docstrings and its comments, and
nothing else:

```
python scripts/ste-lint.py --verbose hooks/ste-refresh.py
python scripts/ste-lint.py --raw hooks/ste-refresh.py     # the whole file
```

`scripts/ste_extract.py` does this. It gives back one line for each line of
the source. A line that carries prose keeps its text, and every other line
becomes empty. Two things follow:

1. A line number in the report names the real line in the real file.
2. A blank line separates two prose blocks that sit apart in the file, so the
   linter never joins a docstring to a comment 40 lines below it.

The same file measured both ways shows why the extractor exists:

```
ste-refresh.py (prose)   words= 352  total= 8  per100w= 2.27
ste-refresh.py           words= 851  total=18  per100w= 2.12
```

The code more than doubles the word count. It dilutes the score, so bad prose
hides behind clean code.

A shebang, a tool directive such as `# type: ignore`, and a ruler such as
`# ---- main ----` are not prose. A trailing comment gets a leading pipe, so
the linter cannot join three labels on three lines of code into one sentence.

**The file check scores only the lines the edit wrote.** Measured over 317
source files of one game, 80% score over the 2.5 target and the median is 3.8,
because those docstrings came before the standard. A hook that reports the
whole file on each edit reports the past every time, and a reader learns to
ignore it. `_edited_span` finds the `new_string` of the Edit and blanks every
line outside it.

## Scope

Layer 1 governs every word a human reads: docs, commit messages, PR text,
comments, error messages. Layer 2 governs a reply to a person. Neither layer
touches code, identifiers, or command syntax. Writing that needs a voice — a
blog post, an essay, marketing copy — is out of scope on purpose. STE is
deliberately flat.

The hooks and the installer are Claude Code only. The skill file itself works
with every agent the skills CLI supports.

## License

MIT, see [LICENSE](LICENSE). This project is unofficial and not affiliated
with ASD. ASD-STE100 is a registered EU trademark (No. 017966390). The
specification is free from [asd-ste100.org](https://asd-ste100.org).

## Provenance

Built for the episode "The cure for AI slop is a 1986 aircraft manual". This
folder lives in the blog repo at `videos/ep01-the-cure-for-ai-slop/asd-ste100/`
and is the canonical source. The skills CLI installs it straight from there —
no mirror, no second repo.
