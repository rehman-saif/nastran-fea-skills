"""Field layouts for the bulk entries pyNastran 1.4.1 rejects but the checks need.

pyNastran tokenizes every card, including the ones it has no class for (see
model.py), so this module never splits text. It only names fields, using the
layout published in the MSC Nastran Quick Reference Guide. Each spec cites its
page; `tools/build_card_specs.py --check` compares the spec against the page.

Field addressing is the flattened layout model.py produces:

    fields[0]          card name
    fields[n-1]        QRG field n of the first line (n = 2..9)
    fields[8k+n-1]     QRG field n of continuation line k

Tail kinds, for the repeating part of an entry:

    id_list      integers from `start` to the end, "THRU" (and "BY") expanded
    pairs        (NAME, VALUE) pairs from `start`
    keyword_lists  lists opened by a keyword in field 2 of a continuation
    groups       fixed-size groups from `start`; layout chosen by another field
"""
from __future__ import annotations

from dataclasses import dataclass, field

QRG = ("https://nexus.hexagon.com/documentationcenter/en-US/bundle/MSC_Nastran_2025.2/page/"
       "Nastran/Quick_Reference_Guide/Bulk_Data_Entries/Entries_A_B/")
RELEASE = "MSC Nastran 2025.2 QRG"

SPECS = {
    "BCONECT": {
        "cite": QRG + "64_BCONECT.htm",
        "fields": {1: "ID", 2: "BCGPID", 3: "BCPPID", 4: "IDSCND", 5: "IDPRIM"},
        "tail": {"kind": "keyword_lists", "start": 9, "keywords": {"SECNDRY": "IDSEC", "PRIMARY": "IDPRIM_LIST"}},
    },
    "BCTABL1": {
        "cite": QRG + "82_BCTABL1.htm",
        "fields": {1: "BCID"},
        "tail": {"kind": "id_list", "start": 2, "name": "IDS"},
    },
    "BCONPRG": {
        "cite": QRG + "66_BCONPRG.htm",
        "fields": {1: "BCGPID"},
        "tail": {"kind": "pairs", "start": 3, "name": "PARAMS"},
    },
    "BCBODY1": {
        "cite": QRG + "53_BCBODY1.htm",
        "fields": {1: "BID", 2: "BPID", 3: "DIM", 4: "BEHAV", 5: "BSID", 6: "BCRGID", 7: "BCGOUT"},
    },
    "BCPROP": {
        "cite": QRG + "74_BCPROP.htm",
        "fields": {1: "ID"},
        "tail": {"kind": "id_list", "start": 2, "name": "IPS"},
    },
    "BCSURF": {
        "cite": QRG + "79_BCSURF.htm",
        "fields": {1: "BID", 2: "BPID", 3: "DIM", 5: "FORM", 6: "INCTHK", 7: "EDGCNT"},
        "tail": {"kind": "groups", "start": 9, "size": 4, "by": "FORM", "default": "FACE", "name": "ITEMS",
                 "layouts": {"FACE": ("ESID", "FACEID", "IDTYPE", None),
                             "GRID": ("EID", "G1", "G2", "G3"),
                             "RIGID": ("BSID", "BCRGID", None, None)}},
    },
}


def to_int(s, default=None):
    s = (s or "").strip()
    try:
        return int(s)
    except ValueError:
        return default


def to_float(s, default=None):
    """Nastran reals: 1.5, 1.5E-3, 1.5D-3, 1.5-3, .5+2, 12."""
    s = (s or "").strip().upper().replace("D", "E")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        for i in range(len(s) - 1, 0, -1):
            if s[i] in "+-" and s[i - 1] != "E":
                try:
                    return float(s[:i] + "E" + s[i:])
                except ValueError:
                    return default
        return default


def expand_thru(vals):
    """["1", "THRU", "4", "9"] -> [1, 2, 3, 4, 9]; "BY" steps honoured."""
    out, i = [], 0
    vals = [(v or "").strip().upper() for v in vals]
    while i < len(vals):
        v = vals[i]
        if v == "THRU" and out and i + 1 < len(vals):
            a, b = out[-1], to_int(vals[i + 1])
            step = 1
            if i + 3 < len(vals) and vals[i + 2] == "BY":
                step = to_int(vals[i + 3], 1) or 1
                i += 2
            if b is not None and b >= a and (b - a) // step < 5_000_000:
                out.extend(range(a + step, b + 1, step))
            i += 2
            continue
        n = to_int(v)
        if n is not None:
            out.append(n)
        i += 1
    return out


@dataclass
class Card:
    """One bulk entry as tokenized by pyNastran: flattened string fields plus where it is."""
    name: str
    fields: list
    file: str
    line: int
    named: dict = field(default_factory=dict)

    def f(self, i, default=""):
        return self.fields[i] if i < len(self.fields) else default

    def i(self, i, default=None):
        return to_int(self.f(i), default)

    def r(self, i, default=None):
        return to_float(self.f(i), default)

    def get(self, key, default=None):
        return self.named.get(key, default)

    @property
    def loc(self):
        import os
        return "%s:%d" % (os.path.basename(self.file), self.line)


def interpret(card):
    """Fill card.named from SPECS. Returns False when the card has no spec."""
    spec = SPECS.get(card.name)
    if spec is None:
        return False
    named = {}
    for i, key in spec["fields"].items():
        v = card.f(i).strip()
        named[key] = to_int(v, v.upper() or None)
    tail = spec.get("tail")
    if tail:
        rest = card.fields[tail["start"]:]
        kind = tail["kind"]
        if kind == "id_list":
            named[tail["name"]] = expand_thru(rest)
        elif kind == "pairs":
            pairs = {}
            for k in range(0, len(rest) - 1, 2):
                key = (rest[k] or "").strip().upper()
                if key:
                    v = (rest[k + 1] or "").strip()
                    pairs[key] = to_int(v, to_float(v, v.upper()))
            named[tail["name"]] = pairs
        elif kind == "keyword_lists":
            cur = None
            for v in rest:
                u = (v or "").strip().upper()
                if u in tail["keywords"]:
                    cur = named.setdefault(tail["keywords"][u], [])
                    continue
                n = to_int(u)
                if cur is not None and n is not None:
                    cur.append(n)
        elif kind == "groups":
            form = (named.get(tail["by"]) or tail["default"])
            layout = tail["layouts"].get(form, tail["layouts"][tail["default"]])
            items = []
            size = tail["size"]
            for k in range(0, len(rest), size):
                g = rest[k:k + size]
                if not any((x or "").strip() for x in g):
                    continue
                d = {}
                for key, v in zip(layout, g):
                    if key:
                        v = (v or "").strip()
                        d[key] = to_int(v, v.upper() or None)
                items.append(d)
            named[tail["name"]] = items
    card.named = named
    return True
