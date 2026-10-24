"""Check every apex.* name used in the skill's prose and templates really exists.

Cross-checks SKILL.md, references/ and assets/ against the generated index in
api/. Exits non-zero if anything is unverifiable, so it can gate a change.

    python tools/validate_references.py

The package root is derived from this file's location.
"""
import re, os, glob, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)

funcs, enums, classes, methods, qualified = set(), {}, set(), set(), set()
for line in open("api/functions-index.md", encoding="utf-8"):
    m = re.match(r"- `([\w.]+)`", line)
    if m:
        funcs.add(m.group(1))
# Long enums are wrapped onto indented lines that repeat the enum name.
for line in open("api/enums.md", encoding="utf-8"):
    m = re.match(r"\s*- `([\w.]+)`(?:: (.+))?", line)
    if m:
        enums.setdefault(m.group(1), set()).update(re.findall(r"`(\w+)`", m.group(2) or ""))
for line in open("api/classes.md", encoding="utf-8"):
    m = re.match(r"- `([\w.]+)`", line)
    if m:
        classes.add(m.group(1))
for line in open("api/methods-index.md", encoding="utf-8"):
    m = re.match(r"- `([\w.]+)\.(\w+)`", line)
    if m:
        qualified.add(m.group(1) + "." + m.group(2))
        methods.add(m.group(2))

modules = {os.path.basename(f)[:-3] for f in glob.glob("api/modules/*.md")}
names = funcs | classes | set(enums) | modules

# Every runtime override must still name a call in the reference.
bad = []
ov = json.load(open("tools/runtime_overrides.json", encoding="utf-8"))
for o in ov["overrides"]:
    if o["name"] not in funcs and o["name"] not in qualified:
        bad.append(("tools/runtime_overrides.json", "OVERRIDE", o["name"]))

srcs = []
for pat in ("*.md", "references/*.md", "assets/**/*.py", "assets/**/*.md"):
    for f in glob.glob(pat, recursive=True):
        n = f.replace(os.sep, "/")
        if n not in srcs:
            srcs.append(n)

print("FILES CHECKED (%d):" % len(srcs))
for s in srcs:
    print("   ", s)

for p in srcs:
    s = open(p, encoding="utf-8").read()
    for m in re.finditer(r"\bapex(?:\.\w+)+(?=\()", s):
        n = m.group(0)
        if n in funcs or n.split(".")[-1] in methods or n in classes:
            continue
        bad.append((p, "CALL", n))
    for m in re.finditer(r"\bapex\.(?:\w+\.)?[A-Z]\w+\.[A-Z]\w+\b", s):
        n = m.group(0)
        en, mem = n.rsplit(".", 1)
        if en in enums:
            if mem not in enums[en]:
                bad.append((p, "ENUM MEMBER", n))
        elif en not in classes:
            bad.append((p, "UNKNOWN ENUM", n))
    # Names written without a call: `apex.environment.createGravity`,
    # `apex.studies.LoadCaseItem.getCommand`. A trailing `*` marks a family.
    for m in re.finditer(r"\bapex(?:\.\w+)+(?![\w(*])", s):
        n = m.group(0)
        head, _, last = n.rpartition(".")
        if (n in names or n in qualified
                or (head in enums and last in enums[head])
                or (head in classes and last in methods)):
            continue
        bad.append((p, "NAME", n))

print("\nISSUES: %d" % len(bad))
for p, k, n in bad:
    print("  %-13s %-50s <- %s" % (k, n, p))

sys.exit(1 if bad else 0)
