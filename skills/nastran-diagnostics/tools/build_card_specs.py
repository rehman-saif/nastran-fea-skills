"""Draft or check card_specs.SPECS against the Quick Reference Guide.

    python tools/build_card_specs.py --check            # every spec vs its QRG page
    python tools/build_card_specs.py --draft BCGRID     # print a draft spec to review

Pages come from the nastran-reference skill (tools/fetch_page.py), so the
layout is the published one, never written from memory. A draft covers the
fixed fields of the format table; repeating groups (lists, THRU, keyword
pairs) are read from the page by a person and written into the spec's "tail".
Needs network access the first time a page is fetched (it is cached after).

Exit 0 when every checked spec matches its page.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from card_specs import SPECS  # noqa: E402

FETCH = os.path.join(HERE, "..", "..", "nastran-reference", "tools", "fetch_page.py")


def fetch(card):
    r = subprocess.run([sys.executable, FETCH, card], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if r.returncode != 0:
        raise RuntimeError("fetch_page %s failed (exit %d): %s" % (card, r.returncode, r.stderr.strip()[-200:]))
    return r.stdout


def format_table(text, card):
    """First format table of the page -> {flattened index: field name}."""
    lines = text.splitlines()
    try:
        i = next(k for k, l in enumerate(lines) if l.startswith("#### Format"))
    except StopIteration:
        return {}
    out, k = {}, -1
    for l in lines[i + 1:]:
        if l.startswith("####"):
            break
        cells = [c.strip().strip("“”\"") for c in l.split("|")]
        if not l.strip() or cells[0] == "1":
            continue
        if cells[0].upper().rstrip("*") == card:
            k = 0
        elif cells[0] == "" and k >= 0:
            k += 1
        else:
            continue
        for j, name in enumerate(cells[1:9], 1):
            if name and not name.lower().startswith("-etc"):
                out[8 * k + j] = name.upper()
    return out


def check(card, spec):
    table = format_table(fetch(card), card)
    if not table:
        return ["no format table found on the page"]
    bad = []
    for idx, name in spec["fields"].items():
        if table.get(idx) != name:
            bad.append("field index %d: spec %s, QRG %s" % (idx, name, table.get(idx)))
    tail = spec.get("tail")
    if tail and tail["start"] not in table and tail["kind"] != "keyword_lists":
        bad.append("tail starts at index %d, which the QRG table leaves empty" % tail["start"])
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--draft", nargs="*", default=[])
    a = ap.parse_args()
    status = 0
    if a.check:
        for card, spec in SPECS.items():
            try:
                bad = check(card, spec)
            except RuntimeError as e:
                print("SKIP  %-8s %s" % (card, e))
                continue
            print("%s %-8s %s" % ("OK   " if not bad else "DIFF ", card, "; ".join(bad)))
            status |= bool(bad)
    for card in a.draft:
        card = card.upper()
        text = fetch(card)
        url = next((l for l in text.splitlines() if l.startswith("https://")), "")
        table = format_table(text, card)
        print("    %r: {" % card)
        print("        \"cite\": %r," % url)
        print("        \"fields\": {%s}," % ", ".join("%d: %r" % kv for kv in sorted(table.items()) if kv[0] < 9))
        rest = {k: v for k, v in table.items() if k >= 9}
        if rest:
            print("        # continuation fields on the page (write a \"tail\" for them): %s" % rest)
        print("    },")
    return status


if __name__ == "__main__":
    sys.exit(main())
