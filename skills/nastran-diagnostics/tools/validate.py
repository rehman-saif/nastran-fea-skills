"""Validate the nastran-diagnostics skill.

    python tools/validate.py [--offline]

Exit 0 if clean, 1 on any error. Warnings never fail the run.
"""
import argparse
import glob
import os
import re
import subprocess
import sys

from common import PKG, read_config

os.chdir(PKG)
errors, warnings = [], []


def err(m):
    errors.append(m)


def warn(m):
    warnings.append(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    bundle = read_config()["bundle"]

    for f in ("SKILL.md", "config.md", "index/ranges.md",
              "references/answering-rules.md", "references/f06-triage.md"):
        if not os.path.exists(f):
            err("missing %s" % f)

    msg_files = sorted(glob.glob("index/messages-*.md"))
    if len(msg_files) < 15:
        err("only %d message index files, expected ~20" % len(msg_files))

    # ---- message rows ----
    total, ranges_seen = 0, []
    row_re = re.compile(r"^\|\s*(\d+)\s*\|\s*(\S+)\s*\|")
    for f in msg_files:
        m = re.match(r"index/messages-(\d+)-(\d+)\.md$", f.replace("\\", "/"))
        if not m:
            err("%s does not follow messages-<lo>-<hi>.md" % f)
            continue
        lo, hi = int(m.group(1)), int(m.group(2))
        ranges_seen.append((lo, hi))
        rows = 0
        for line in open(f, encoding="utf-8"):
            r = row_re.match(line)
            if not r:
                continue
            rows += 1
            num = int(r.group(1))
            if not lo <= num <= hi:
                err("%s: message %d is outside its range %d-%d" % (f, num, lo, hi))
        if rows == 0:
            err("%s has no message rows" % f)
        total += rows
    if total < 4000:
        err("only %d messages indexed, expected ~5500" % total)

    # ---- ranges.md must cover every index file, without duplicates ----
    mapped = set()
    rng_re = re.compile(r"^\|\s*(\d+)\s*-\s*(\d+)\s*\|")
    for line in open("index/ranges.md", encoding="utf-8"):
        m = rng_re.match(line)
        if not m:
            continue
        pair = (int(m.group(1)), int(m.group(2)))
        if pair in mapped:
            err("index/ranges.md lists %d-%d twice" % pair)
        mapped.add(pair)
    for pair in ranges_seen:
        if pair not in mapped:
            err("index/ranges.md is missing range %d-%d" % pair)

    # ---- links ----
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for f in (glob.glob("*.md") + glob.glob("references/*.md")
              + glob.glob("index/*.md")):
        base = os.path.dirname(f)
        for t in link_re.findall(open(f, encoding="utf-8").read()):
            if t.startswith(("http://", "https://", "#")):
                continue
            t = t.split("#", 1)[0]
            if t and not os.path.exists(os.path.normpath(os.path.join(base, t))):
                err("%s: broken link -> %s" % (f, t))

    # ---- the skill must route, not answer everything ----
    skill = open("SKILL.md", encoding="utf-8").read()
    for other in ("nastran-reference", "apex-scripting", "apex-docs"):
        if other not in skill:
            err("SKILL.md must hand over to %s" % other)

    # ---- a real lookup must work end to end ----
    if not a.offline:
        r = subprocess.run([sys.executable, "tools/fetch_message.py", "740"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out = r.stdout or ""
        if r.returncode != 0:
            warn("fetch_message 740 failed (offline?): %s"
                 % (r.stderr or "").strip().splitlines()[:1])
        elif "RDASGN" not in out or "User action" not in out:
            warn("fetch_message 740 returned unexpected content")
        elif len(out) > 4000:
            err("fetch_message 740 returned %d chars - it should slice one "
                "message, not the whole range file" % len(out))
        r = subprocess.run([sys.executable, "tools/build_card_specs.py", "--check"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        for line in (r.stdout or "").splitlines():
            if line.startswith("DIFF"):
                err("card_specs does not match the QRG: %s" % line[5:].strip())
            elif line.startswith("SKIP"):
                warn("card_specs not checked against the QRG: %s" % line[5:].strip())

    check_digest_tools()

    for w in warnings:
        print("WARN  %s" % w)
    for e in errors:
        print("ERROR %s" % e)
    print("\n%d error(s), %d warning(s)   bundle=%s   ranges=%d   messages=%d"
          % (len(errors), len(warnings), bundle, len(msg_files), total))
    return 1 if errors else 0


FAULTS_EXPECTED = {"DUPLICATE_ID", "MISSING_PROPERTY", "MISSING_SET", "SPC_ON_DEPENDENT",
                   "UNCONSTRAINED_GROUP", "COINCIDENT_UNMERGED", "FLOATING_MASS", "MIXED_UNITS",
                   "ORPHAN_GRID"}
GLUE_EXPECTED = {"GLUE_DEPENDENT_LOAD_PATH", "GLUE_COARSE_SECONDARY"}


def check_digest_tools():
    """Run the digest tools against tests/fixtures (offline, a few seconds)."""
    import json
    import shutil
    import tempfile
    tools = os.path.join(PKG, "tools")
    fx = os.path.join(PKG, "tests", "fixtures")
    for f in ("faults.bdf", "faults_mesh.inc", "glue.bdf", "mini.f06"):
        if not os.path.exists(os.path.join(fx, f)):
            err("missing test fixture tests/fixtures/%s" % f)
            return
    for f in ("references/run-digest.md", "tools/run_digest.py", "tools/nastran_query.py",
              "tools/deck_checks.py", "tools/model.py", "tools/card_specs.py", "tools/deps.py"):
        if not os.path.exists(f):
            err("missing %s" % f)
            return
    if os.path.exists("tools/deck_reader.py"):
        err("tools/deck_reader.py is retired: pyNastran is the only deck reader")
    sys.path.insert(0, tools)
    try:
        import importlib
        for n in ("pyNastran", "numpy", "scipy"):
            importlib.import_module(n)
    except ImportError as e:
        err("digest tools need pyNastran/numpy/scipy (see requirements.txt): %s" % e)
        return
    try:
        from card_specs import SPECS
        from deck_checks import build_model, run_checks, ROUTES
        from model import load_deck
    except Exception as e:  # noqa: BLE001
        err("digest tools do not import: %s" % e)
        return
    for name, spec in SPECS.items():
        if not spec.get("cite", "").startswith("https://"):
            err("card_specs: %s has no QRG citation" % name)
    quiet = lambda *a: None  # noqa: E731
    tmp = tempfile.mkdtemp(prefix="ndiag_")
    try:
        # ---- fallback parser: pyNastran-rejected cards named the same in every field format
        def small(*f):
            return "".join("%-8s" % x for x in f) + "\n"

        def large(*f):
            out = "%-8s" % (f[0] + "*") + "".join("%16s" % x for x in f[1:5]) + "\n"
            return out + "%-8s" % "*" + "".join("%16s" % x for x in f[5:9]) + "\n"
        tail = (small("BCONECT", 9, "", "", "", "", "", "", "", "+B9") + small("+B9", "SECNDRY", 30, 26)
                + small("+", "PRIMARY", 294, 135))
        layouts = {
            "small": small("BCONECT", 5, 5, "", 2, 1) + small("BCTABL1", 7, 5, "THRU", 7, 12)
            + small("BCONPRG", 5, "", "ICOORD", 1, "IGLUE", 3) + tail,
            "large": large("BCONECT", 5, 5, "", 2, 1) + large("BCTABL1", 7, 5, "THRU", 7, 12)
            + large("BCONPRG", 5, "", "ICOORD", 1, "IGLUE", 3) + tail,
            "free": "BCONECT,5,5,,2,1\nBCTABL1,7,5,THRU,7,12\nBCONPRG,5,,ICOORD,1,IGLUE,3\n"
                    "BCONECT,9,,,,,,,,+\n+,SECNDRY,30,26\n+,PRIMARY,294,135\n",
        }
        want = {("BCONECT", 5): {"ID": 5, "BCGPID": 5, "BCPPID": None, "IDSCND": 2, "IDPRIM": 1},
                ("BCTABL1", 7): {"BCID": 7, "IDS": [5, 6, 7, 12]},
                ("BCONPRG", 5): {"BCGPID": 5, "PARAMS": {"ICOORD": 1, "IGLUE": 3}},
                ("BCONECT", 9): {"ID": 9, "BCGPID": None, "BCPPID": None, "IDSCND": None, "IDPRIM": None,
                                 "IDSEC": [30, 26], "IDPRIM_LIST": [294, 135]}}
        for fmt, body in layouts.items():
            p = os.path.join(tmp, "fmt_%s.bdf" % fmt)
            with open(p, "w") as fh:
                fh.write("BEGIN BULK\nGRID    1               0.      0.      0.\n" + body + "ENDDATA\n")
            got = {(c.name, c.named.get("ID", c.named.get("BCID", c.named.get("BCGPID")))): c.named
                   for c in load_deck(p).contact}
            for k, v in want.items():
                if got.get(k) != v:
                    err("card_specs: %s %s in %s field read as %s, expected %s" % (k[0], k[1], fmt, got.get(k), v))

        # ---- seeded faults
        m = build_model(os.path.join(fx, "faults.bdf"), log=quiet)
        F, S, _ = run_checks(m, m.case_control, log=quiet)
        got = {f["code"] for f in F.items}
        for code in FAULTS_EXPECTED - got:
            err("deck_checks: seeded fault %s not detected in faults.bdf" % code)
        fr = S["loads"].get(10, S["loads"].get("10", {})).get("force_resultant_basic")
        if not fr or abs(fr[0] - 17.888544) > 1e-4 or abs(fr[1] - 8.944272) > 1e-4:
            err("deck_checks: LOAD 10 resultant through CORD2C should be (17.8885, 8.9443, 0), got %s" % fr)
        if S.get("coincident", {}).get("across_unconnected_components") != 3:
            err("deck_checks: expected 3 coincident unmerged pairs, got %s" % S.get("coincident"))
        m = build_model(os.path.join(fx, "glue.bdf"), log=quiet)
        F, S, _ = run_checks(m, m.case_control, log=quiet)
        got2 = {f["code"] for f in F.items}
        for code in GLUE_EXPECTED - got2:
            err("deck_checks: %s not detected in glue.bdf" % code)
        if "UNCONSTRAINED_GROUP" in got2:
            err("deck_checks: glue.bdf is constrained through its glue pair but was reported unconstrained")
        doc = open("references/run-digest.md", encoding="utf-8").read()
        for code in set(ROUTES) | got | got2:
            if code not in ROUTES:
                err("deck_checks emits %s but ROUTES has no entry for it" % code)
            if "`%s`" % code not in doc:
                err("finding code %s is not documented in references/run-digest.md" % code)

        # ---- end to end: f06 with echo -> digest -> query
        out = os.path.join(tmp, "mini")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "tools/run_digest.py", "--f06", os.path.join(fx, "mini.f06"),
                            "-o", out], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            err("run_digest.py failed on mini.f06: %s" % r.stderr.strip()[-300:])
            return
        d = open(os.path.join(out, "digest.md"), encoding="utf-8").read()
        if "first fatal: UFM 9050" not in d:
            err("run_digest: first fatal (UFM 9050) not reported")
        if "UWM 4698 (DCMPD) x2" not in d:
            err("run_digest: duplicate warnings not deduplicated")
        if "rebuilt from the f06 bulk data echo" not in d:
            err("run_digest: deck not rebuilt from the f06 echo")
        if len(d) > 12500:
            err("run_digest: digest exceeds its cap (%d chars)" % len(d))
        q = subprocess.run([sys.executable, "tools/nastran_query.py", out, "grid", "3"],
                           capture_output=True, text=True, env=env)
        if "GRID 3" not in q.stdout or "FORCE set 1" not in q.stdout:
            err("nastran_query grid 3 did not return the card and its load: %r" % q.stdout[:200])
        json.load(open(os.path.join(out, "findings.json")))
    except Exception as e:  # noqa: BLE001
        err("digest tool self-test crashed: %r" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
