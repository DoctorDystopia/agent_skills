"""Apply exact old/new text pairs to one file, all or nothing.

Usage: python apply_pairs.py TARGET PAIRS_FILE [PAIRS_FILE ...]

A pairs file holds blocks of this form, one after another:

    @@@OLD
    exact old text
    @@@NEW
    new text
    @@@END

Each old text must occur exactly one time in the target at the moment its
pair applies. If any pair fails, the script writes nothing and names the
failed pair. The target keeps its line endings.
"""
import sys

OLD_MARK = "@@@OLD\n"
NEW_MARK = "\n@@@NEW\n"
END_MARK = "\n@@@END"


def read_pairs(path):
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    pairs = []
    for chunk in text.split(OLD_MARK)[1:]:
        old, rest = chunk.split(NEW_MARK, 1)
        new = rest.split(END_MARK, 1)[0]
        pairs.append((old, new))
    return pairs


def main():
    target = sys.argv[1]
    with open(target, encoding="utf-8", newline="") as fh:
        raw = fh.read()
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    applied = 0
    for pairs_path in sys.argv[2:]:
        for index, (old, new) in enumerate(read_pairs(pairs_path), 1):
            count = text.count(old)
            if count != 1:
                first_line = old.split("\n", 1)[0][:70]
                print("FAIL {} pair {}: old text found {} times: {}".format(
                    pairs_path, index, count, first_line))
                print("Nothing written.")
                return 1
            text = text.replace(old, new)
            applied += 1
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print("Applied {} pairs to {}.".format(applied, target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
