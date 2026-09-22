#!/usr/bin/env python3
"""Installer for the asd-ste100 skill. Local variant of the ep01 kit installer.

    node hooks/run-python.cjs install.py              install or repair
    node hooks/run-python.cjs install.py --dry-run    show the plan, write nothing
    node hooks/run-python.cjs install.py --check      report drift, write nothing
    node hooks/run-python.cjs install.py --uninstall  remove what this script added

THIS REPOSITORY IS THE SOURCE. ~/.claude/skills/asd-ste100 is a copy that this
script writes. Make each change here, then run the script. An edit made in the
copy is lost on the next run, and --check reports it before that happens.

What it wires, for Claude Code:

1. ~/.claude/skills/asd-ste100   a copy of this directory
2. ~/.claude/settings.json        five hook entries

Two install routes exist, and they must never stack. This script is the
SETTINGS route. The other one is the PLUGIN route: a clone of this repository
placed at ~/.claude/skills/asd-ste100 loads as asd-ste100@skills-dir, and
Claude Code reads hooks/hooks.json by itself. Both routes together register
every hook two times. For that reason NO_COPY holds .claude-plugin: the
manifest that makes this directory a plugin never reaches the copy.

The five hooks:

- UserPromptSubmit  ste-inject.py   the rule card, every turn
- PostToolUse       ste-refresh.py  a short card every 12 tool calls, and a
                                    score report after a Write of a prose file
- PreToolUse        ste-pregate.py  lints a commit message and a gh pull
                                    request body before the command runs
- Stop              ste-gate.py     lints the final reply (warn-only trial)
- SubagentStop      ste-gate.py     lints a subagent report, and blocks it

Changes from the kit installer:

- It copies the directory. It does not make a symlink, because os.symlink on
  Windows needs Developer Mode or an admin shell.
- Each hook is one command string. The kit used "command" plus "args".
- The PreToolUse matcher is Bash|PowerShell, so a commit through the
  PowerShell tool meets the pre-send gate.
- It adds SubagentStop. The kit gated the main agent alone, so every report a
  subagent wrote reached the reader unlinted.
- It installs no output style. The rule card and the skill do that job, and a
  custom output style can remove the default coding instructions.

The script is idempotent. A second run repairs the install. An entry that
names one of the four hook scripts is replaced, not duplicated. The previous
settings.json is saved next to it as settings.json.ste-backup before the
first change.
"""
import argparse
import filecmp
import fnmatch
import json
import os
import shutil
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
SETTINGS = os.path.join(CLAUDE, "settings.json")
DEST = os.path.join(CLAUDE, "skills", "asd-ste100")
MARKER_FILE = ".ste-installed"      # proves that DEST is a copy this script made

HOOK_DIR = os.path.join(DEST, "hooks")
RUNNER = os.path.join(HOOK_DIR, "run-python.cjs")
# .claude-plugin makes this directory a plugin. A plugin under ~/.claude/skills
# registers hooks/hooks.json by itself, and the settings entries below register
# the same five hooks again. The copy therefore leaves the manifest behind.
# .git and .gitignore belong to the source and say nothing to the copy.
NO_COPY = ("__pycache__", "*.pyc", ".claude-plugin", ".git", ".gitignore")
COPY_IGNORE = shutil.ignore_patterns(*NO_COPY)


def quoted(path):
    return '"{}"'.format(path.replace("\\", "/"))


def command_hook(script, timeout, status_message=None):
    hook = {
        "type": "command",
        "command": "node {} {}".format(quoted(RUNNER),
                                       quoted(os.path.join(HOOK_DIR, script))),
        "timeout": timeout,
    }
    if status_message:
        hook["statusMessage"] = status_message
    return hook


HOOKS = {
    "UserPromptSubmit": {
        "marker": "ste-inject",
        "entry": {"hooks": [command_hook("ste-inject.py", 10)]},
    },
    "PreToolUse": {
        "marker": "ste-pregate",
        "entry": {"matcher": "Bash|PowerShell",
                  "hooks": [command_hook("ste-pregate.py", 15)]},
    },
    "PostToolUse": {
        "marker": "ste-refresh",
        "entry": {"matcher": "*",
                  "hooks": [command_hook("ste-refresh.py", 15)]},
    },
    "Stop": {
        "marker": "ste-gate",
        "entry": {
            "hooks": [command_hook(
                "ste-gate.py", 30, "Checking ASD-STE100")],
        },
    },
    # A subagent writes a report that a person reads. Stop does not fire for
    # a subagent, so every one of those reports went out unlinted.
    "SubagentStop": {
        "marker": "ste-gate",
        "entry": {
            "hooks": [command_hook(
                "ste-gate.py", 30, "Checking ASD-STE100")],
        },
    },
}
MARKERS = tuple(spec["marker"] for spec in HOOKS.values())


def is_ste_hook(hook):
    if not isinstance(hook, dict):
        return False
    cmd = " ".join([hook.get("command", "")] + (hook.get("args") or []))
    return any(m in cmd for m in MARKERS)


def strip_ste(groups):
    """Remove every ste-* command hook from an event's entry list."""
    kept = []
    removed = 0
    for group in groups or []:
        inner = [h for h in group.get("hooks", []) if not is_ste_hook(h)]
        removed += len(group.get("hooks", [])) - len(inner)
        if inner:
            kept.append({**group, "hooks": inner})
    return kept, removed


def _ignored(name):
    """True when NO_COPY holds this file or directory name."""
    return any(fnmatch.fnmatch(name, pattern) for pattern in NO_COPY)


def _tracked_files(root):
    """Every file under root that the copy carries, as a relative path."""
    found = set()
    for folder, folders, files in os.walk(root):
        folders[:] = [f for f in folders if not _ignored(f)]
        for name in files:
            if _ignored(name) or name == MARKER_FILE:
                continue
            full = os.path.join(folder, name)
            found.add(os.path.relpath(full, root).replace("\\", "/"))
    return found


def check_drift(actions):
    """Report each file where the copy and the source disagree.

    An edit made in the copy is lost on the next install. This names those
    files before that happens, and it names a file that only one side has.
    """
    if os.path.realpath(SRC) == os.path.realpath(DEST):
        actions.append("ok       source and copy are the same directory")
        return 0
    if not os.path.isdir(DEST):
        actions.append("absent   {} does not exist. Run the install.".format(DEST))
        return 1
    here, there = _tracked_files(SRC), _tracked_files(DEST)
    problems = 0
    for name in sorted(here - there):
        actions.append("missing  {} is in the source, not in the copy".format(name))
        problems += 1
    for name in sorted(there - here):
        actions.append("extra    {} is in the copy, not in the source".format(name))
        problems += 1
    for name in sorted(here & there):
        same = filecmp.cmp(os.path.join(SRC, name), os.path.join(DEST, name),
                           shallow=False)
        if not same:
            actions.append("differs  {}".format(name))
            problems += 1
    if not problems:
        actions.append("ok       the copy matches the source, {} files".format(
            len(here)))
    return problems


def copy_skill(actions, dry):
    """Copy this directory to DEST. Returns False if DEST is in the way."""
    if os.path.realpath(SRC) == os.path.realpath(DEST):
        actions.append("ok       running from {}, nothing to copy".format(DEST))
        return True
    ours = os.path.exists(os.path.join(DEST, MARKER_FILE))
    if os.path.lexists(DEST) and not ours:
        backup = DEST + ".pre-ste-backup"
        if os.path.lexists(backup):
            actions.append("stop     {} is not ours and {} exists. Remove one "
                           "by hand.".format(DEST, backup))
            return False
        actions.append("backup   {} -> {}".format(DEST, backup))
        if not dry:
            os.rename(DEST, backup)
    actions.append("copy     {} -> {}".format(SRC, DEST))
    if not dry:
        shutil.copytree(SRC, DEST, ignore=COPY_IGNORE, dirs_exist_ok=True)
        with open(os.path.join(DEST, MARKER_FILE), "w", encoding="utf-8") as fh:
            fh.write(SRC)
    return True


def drop_skill(actions, dry):
    """Delete the copy at DEST, and never the directory this script runs from.

    Before this guard, --uninstall run from inside DEST deleted DEST. When
    that copy is the only copy, the skill goes with it. The guard is the
    reason the source lives in its own repository.
    """
    if os.path.realpath(SRC) == os.path.realpath(DEST):
        actions.append("keep     {} is the directory this script runs from"
                       .format(DEST))
        return
    if os.path.exists(os.path.join(DEST, MARKER_FILE)):
        actions.append("remove   {}".format(DEST))
        if not dry:
            shutil.rmtree(DEST)


def main():
    parser = argparse.ArgumentParser(description="Install the asd-ste100 skill.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="report drift between the source and the copy")
    args = parser.parse_args()
    dry = args.dry_run
    actions = []

    if args.check:
        problems = check_drift(actions)
        for line in actions:
            print(line)
        return 1 if problems else 0

    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            settings = json.load(fh)
    except FileNotFoundError:
        settings = {}
    except json.JSONDecodeError:
        print("error: {} is not valid JSON. Fix it first.".format(SETTINGS))
        return 1
    hooks = settings.setdefault("hooks", {})

    if args.uninstall:
        for event in HOOKS:
            kept, removed = strip_ste(hooks.get(event))
            if removed:
                actions.append("remove   {} ste hook from {}".format(removed, event))
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)
        if not hooks:
            settings.pop("hooks")
    else:
        if not copy_skill(actions, dry):
            for line in actions:
                print(line)
            return 1
        for event, spec in HOOKS.items():
            kept, removed = strip_ste(hooks.get(event))
            if removed:
                actions.append("replace  {} older ste hook in {}".format(removed, event))
            else:
                actions.append("add      {} hook ({})".format(event, spec["marker"]))
            hooks[event] = kept + [spec["entry"]]

    if not dry:
        os.makedirs(CLAUDE, exist_ok=True)
        backup = SETTINGS + ".ste-backup"
        if os.path.exists(SETTINGS) and not os.path.exists(backup):
            with open(SETTINGS, encoding="utf-8") as fh:
                data = fh.read()
            with open(backup, "w", encoding="utf-8") as fh:
                fh.write(data)
            actions.append("backup   settings.json -> settings.json.ste-backup")
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
            fh.write("\n")
        if args.uninstall:
            drop_skill(actions, dry)
    elif args.uninstall:
        drop_skill(actions, dry)

    for line in actions:
        print(line)
    print("{}{}. Restart the Claude Code session to load the hooks.".format(
        "planned " if dry else "",
        "uninstalled" if args.uninstall else "installed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
