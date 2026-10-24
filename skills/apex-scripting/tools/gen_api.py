"""Generate the compact Apex API reference in `api/` from Apex Doxygen XML.

Writes `api/functions-index.md`, `api/methods-index.md`, `api/enums.md`,
`api/classes.md`, `api/modules/*.md` and `api/classes/*.md`, each carrying the
full per-parameter documentation so the raw XML does not need to ship with the
skill.

Behaviour that only shows up at runtime (calls that raise although the
reference documents them, arguments that are silently ignored) is kept by hand
in `tools/runtime_overrides.json`. Each entry is stamped into the block and the
index line of the function or method it names. An entry naming a call that is
not in the reference stops the build.

    python tools/gen_api.py [source_xml_dir] [output_package_dir]

With no arguments it looks for the Apex documentation archive's `ScriptingXML`
folder near the skill, or at $APEX_SCRIPTING_ARCHIVE. Paths are derived from this
file's location, so the skill can be moved or copied anywhere.
"""
import xml.etree.ElementTree as ET
import glob, os, re, sys, collections, copy, json

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

def _find_src():
    """Locate a folder holding namespaceapex*.xml / classapex*.xml."""
    cands = []
    if os.environ.get("APEX_SCRIPTING_ARCHIVE"):
        cands.append(os.environ["APEX_SCRIPTING_ARCHIVE"])
    cands.append(os.path.join(PKG, "api", "xml"))       # legacy bundled copy
    parent = os.path.dirname(PKG)
    for base in (parent, os.path.dirname(parent)):
        cands += [
            os.path.join(base, "Archive", "Documentation", "ScriptingXML"),
            os.path.join(base, "Documentation", "ScriptingXML"),
        ]
    for c in cands:
        if c and glob.glob(os.path.join(c, "namespaceapex*.xml")):
            return c
    return cands[1]


SRC = sys.argv[1] if len(sys.argv) > 1 else _find_src()
OUT = sys.argv[2] if len(sys.argv) > 2 else PKG
OVERRIDES = os.path.join(HERE, "runtime_overrides.json")

def text(el):
    if el is None:
        return ""
    # Doxygen code examples are dropped: flattened onto one line they lose
    # their whitespace and read as broken code.
    if el.find(".//programlisting") is not None:
        el = copy.deepcopy(el)
        for parent in el.iter():
            for child in list(parent):
                if child.tag == "programlisting":
                    parent.remove(child)
    s = "".join(el.itertext())
    s = re.sub(r"\s+", " ", s).strip()
    return s

PRIM = {
    "double": "float", "float": "float", "int": "int", "bool": "bool",
    "std::string": "str", "std::wstring": "str", "char": "str",
    "void": "None", "size_t": "int",
    "unsigned": "int", "long": "int",
}

def norm_type(t):
    """Normalize a C++ Doxygen type to its Python-facing equivalent."""
    if not t:
        return ""
    t = re.sub(r"\b\w*_DLL_LINKAGE\b", " ", t)
    t = re.sub(r"\bconst\b", " ", t)
    t = t.replace("&", " ").replace("*", " ")
    # Rewrite templates innermost-first: [^<>]* keeps each substitution inside a
    # single bracket pair, so nesting like map<ObjectSPtr<X>, int> unwraps
    # correctly instead of a greedy match running past the closing bracket.
    for _ in range(8):
        prev = t
        t = re.sub(r"ObjectSPtr\s*<([^<>]*)>", r"\1", t)
        t = re.sub(r"(?:std::)?(?:vector|list|set)\s*<([^<>]*)>", r"[\1]", t)
        t = re.sub(r"(?:std::)?(?:unordered_)?map\s*<([^<>]*?),([^<>]*)>",
                   r"{\1:\2}", t)
        t = re.sub(r"(?:std::)?pair\s*<([^<>]*?),([^<>]*)>", r"(\1, \2)", t)
        if t == prev:
            break
    t = t.replace("::", ".")
    # primitives (word-boundary)
    for k, v in PRIM.items():
        t = re.sub(r"\b%s\b" % re.escape(k.replace("::", ".")), v, t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*([\[\]{}:,])\s*", r"\1", t)
    return t


def norm_default(dv):
    """Render a C++ default value the way it would be written in Python."""
    if not dv:
        return ""
    # empty container constructions -> Python empty literals
    if re.fullmatch(r"(?:std::)?(?:vector|list)\s*<.*>\s*\(\s*\)", dv):
        return "[]"
    if re.fullmatch(r"(?:std::)?map\s*<.*>\s*\(\s*\)", dv):
        return "{}"
    # container literal, e.g. std::vector<double>({0.0, 1.0, 0.0}) -> [0.0, 1.0, 0.0]
    m = re.fullmatch(r"(?:std::)?(?:vector|list|set)\s*<.*?>\s*\(\s*\{(.*)\}\s*\)", dv)
    if m:
        return "[%s]" % m.group(1).strip()
    # a null smart pointer is just None
    if re.fullmatch(r"NULLSPtr\s*\(.*\)", dv):
        return "None"
    if dv in ("true", "false"):
        return dv.capitalize()
    if dv in ("nullptr", "NULL"):
        return "None"
    return dv.replace("::", ".")


def param_docs_of(m):
    """declname -> prose, from the <parameterlist> in <detaileddescription>."""
    docs = {}
    dd = m.find("detaileddescription")
    if dd is None:
        return docs
    for pl in dd.iter("parameterlist"):
        if (pl.get("kind") or "") != "param":
            continue
        for item in pl.findall("parameteritem"):
            names = [text(n) for n in item.iter("parametername")]
            desc = text(item.find("parameterdescription"))
            for n in names:
                if n and desc:
                    docs.setdefault(n, desc)
    return docs


def remarks_of(m):
    """Detailed prose with the parameter list and return section removed."""
    dd = m.find("detaileddescription")
    if dd is None:
        return ""
    dd = copy.deepcopy(dd)
    for parent in dd.iter():
        for child in list(parent):
            if child.tag in ("parameterlist", "simplesect"):
                parent.remove(child)
    t = text(dd)
    t = re.sub(r"^:\s*", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def returns_of(m):
    dd = m.find("detaileddescription")
    if dd is None:
        return ""
    for ss in dd.iter("simplesect"):
        if (ss.get("kind") or "") == "return":
            return text(ss)
    return ""


def params_of(m):
    out = []
    for p in m.findall("param"):
        ty = norm_type(text(p.find("type")))
        nm = text(p.find("declname")) or text(p.find("defname"))
        dv = norm_default(text(p.find("defval")))
        s = f"{nm}: {ty}" if ty else nm
        if dv:
            s += f" = {dv}"
        out.append(s)
    return out


# Doxygen enum briefs all trail off into the same "how to reference an enum"
# boilerplate. That convention is stated once in references/scripting-model.md,
# so drop it here -- but keep any deprecation notice that follows it.
SYNTAX_BOILER = re.compile(
    r"(?:\b[\w]+\s+)*?can be specified using the syntax.*?"
    r"(?=DEPRECATION NOTICE|$)", re.I | re.S)
LEAD_BOILER = re.compile(
    r"^(?:Enum(?:eration)?\b[\s:]*)?(?:An?\s+enumeration\s+)?"
    r"(?:used\s+)?(?:defining|to define|that defines)?\s*(?:the\s+)?", re.I)

def brief_of(m, is_enum=False):
    b = text(m.find("briefdescription"))
    b = re.sub(r"^:\s*", "", b)
    if is_enum:
        b = SYNTAX_BOILER.sub(" ", b)
        b = LEAD_BOILER.sub("", b)
        b = re.sub(r"\s+", " ", b).strip(" .")
        if b:
            b = b[0].upper() + b[1:]
    # Keep deprecation warnings but collapse the shouting.
    b = re.sub(r"DEPRECATION NOTICE\s*:?", "DEPRECATED:", b)
    b = re.sub(r"\b(THIS ENUMERATION IS DEPRECATED AND WILL BE REMOVED IN A "
               r"FUTURE RELEASE\.?)\s*", "", b)
    b = re.sub(r"\s+", " ", b)
    # Prose refers to types in C++ form; show them as Python paths.
    b = re.sub(r"\b(apex(?:::\w+)+)", lambda m: m.group(1).replace("::", "."), b)
    return b.strip()


def enum_values(m):
    vals = []
    for ev in m.findall("enumvalue"):
        vals.append(text(ev.find("name")))
    return vals


def load_namespaces():
    mods = {}
    for f in sorted(glob.glob(os.path.join(SRC, "namespaceapex*.xml"))):
        cd = ET.parse(f).getroot().find("compounddef")
        name = cd.findtext("compoundname").replace("::", ".")
        if not (name == "apex" or name.startswith("apex.")):
            continue
        funcs, enums = [], []
        for s in cd.findall("sectiondef"):
            kind = s.get("kind")
            for m in s.findall("memberdef"):
                if kind == "func":
                    funcs.append({
                        "name": m.findtext("name"),
                        "ret": norm_type(text(m.find("type"))),
                        "params": params_of(m),
                        "brief": brief_of(m),
                        "pdocs": param_docs_of(m),
                        "remarks": remarks_of(m),
                        "returns": returns_of(m),
                    })
                elif kind == "enum":
                    enums.append({
                        "name": m.findtext("name"),
                        "values": enum_values(m),
                        "brief": brief_of(m, is_enum=True),
                    })
        mods[name] = {
            "brief": text(cd.find("briefdescription")),
            "funcs": sorted(funcs, key=lambda d: d["name"]),
            "enums": sorted(enums, key=lambda d: d["name"]),
        }
    return mods


def load_classes():
    classes = []
    files = (glob.glob(os.path.join(SRC, "classapex*.xml"))
             + glob.glob(os.path.join(SRC, "structapex*.xml")))
    for f in sorted(files):
        cd = ET.parse(f).getroot().find("compounddef")
        full = cd.findtext("compoundname").replace("::", ".")
        if not full.startswith("apex"):
            continue
        # enable_shared_from_this is a C++ implementation detail, not a Python base.
        bases = [b.text.replace("::", ".") for b in cd.findall("basecompoundref")
                 if b.text and "enable_shared_from_this" not in b.text]
        props, meths = [], []
        for s in cd.findall("sectiondef"):
            k = s.get("kind")
            if k == "public-attrib":
                props = [m.findtext("name") for m in s.findall("memberdef")]
            elif k == "public-func":
                for m in s.findall("memberdef"):
                    meths.append({
                        "name": m.findtext("name"),
                        "ret": norm_type(text(m.find("type"))),
                        "params": params_of(m),
                        "brief": brief_of(m),
                        "pdocs": param_docs_of(m),
                        "remarks": remarks_of(m),
                        "returns": returns_of(m),
                    })
        mod = full.rsplit(".", 1)[0]
        classes.append({
            "full": full, "module": mod, "short": full.rsplit(".", 1)[1],
            "brief": text(cd.find("briefdescription")),
            "bases": bases, "props": props,
            "meths": sorted(meths, key=lambda d: d["name"]),
        })
    return classes


def short_brief(b, limit=160):
    """First sentence of a brief, capped, for one-line index and list entries."""
    if not b:
        return ""
    s = re.split(r"(?<=[.!?])\s+(?=[A-Z])", b, maxsplit=1)[0]
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " ..."
    if "DEPRECATED" in b and "DEPRECATED" not in s:
        s = "DEPRECATED. " + s
    return s


# Member lists longer than ENUM_WRAP characters are wrapped onto lines of about
# ENUM_CHUNK characters, each repeating the enum name, so a grep for one member
# returns a short line instead of the whole enum.
ENUM_WRAP = 300
ENUM_CHUNK = 220

def enum_members(vals):
    return ", ".join("`%s`" % v for v in vals)


def enum_chunks(vals):
    lines, cur, n = [], [], 0
    for v in vals:
        s = "`%s`" % v
        if cur and n + len(s) + 2 > ENUM_CHUNK:
            lines.append(", ".join(cur))
            cur, n = [], 0
        cur.append(s)
        n += len(s) + 2
    if cur:
        lines.append(", ".join(cur))
    return lines


OVERRIDE_LABEL = {"raises": "Raises at runtime",
                  "silent": "Fails silently at runtime",
                  "note": "Runtime behaviour"}
OVERRIDE_TAG = {"raises": "raises at runtime",
                "silent": "fails silently at runtime",
                "note": "runtime note"}

def load_overrides():
    """name -> [override], from tools/runtime_overrides.json."""
    if not os.path.exists(OVERRIDES):
        return {}
    with open(OVERRIDES, encoding="utf-8") as fh:
        data = json.load(fh)
    out = collections.defaultdict(list)
    for o in data["overrides"]:
        if o.get("kind") not in OVERRIDE_LABEL:
            sys.exit("runtime_overrides.json: %s has unknown kind %r" % (o.get("name"), o.get("kind")))
        out[o["name"]].append(o)
    return out


def override_lines(ovs):
    L = []
    for o in ovs:
        s = "> **%s (%s):** %s" % (OVERRIDE_LABEL[o["kind"]], o["observed"], o["behaviour"])
        if o.get("instead"):
            s += " **Instead:** " + o["instead"]
        L.append(s)
    return L


def override_tag(ovs):
    tags = []
    for o in ovs:
        t = "%s in %s" % (OVERRIDE_TAG[o["kind"]], o["observed"])
        if t not in tags:
            tags.append(t)
    return " **[%s]**" % "; ".join(tags) if tags else ""


def emit_detail(L, d, indent=""):
    """Append brief, per-parameter docs, return note and remarks for a member."""
    if d.get("brief"):
        L.append(indent + d["brief"])
    pdocs = d.get("pdocs") or {}
    if pdocs:
        L.append("")
        for pspec in d["params"]:
            nm = pspec.split(":")[0].split(" =")[0].strip()
            desc = pdocs.get(nm)
            if desc:
                L.append("%s- `%s` — %s" % (indent, nm, desc))
    if d.get("returns"):
        L.append("")
        L.append("%sReturns: %s" % (indent, d["returns"]))
    rem = d.get("remarks")
    if rem and rem != d.get("brief"):
        L.append("")
        L.append(indent + rem)


def sig(d):
    return "%s(%s) -> %s" % (d["name"], ", ".join(d["params"]), d["ret"] or "None")


def w(path, s):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(s)
    return len(s)


def main():
    if not os.path.isdir(SRC):
        sys.exit("source XML not found: %s\n"
                 "Run tools/import_docs.py <ScriptingXML dir> first." % SRC)

    mods = load_namespaces()
    classes = load_classes()
    if not mods:
        sys.exit("no namespaceapex*.xml found in %s" % SRC)
    by_mod = collections.defaultdict(list)
    for c in classes:
        by_mod[c["module"]].append(c)

    overrides = load_overrides()
    known = {"%s.%s" % (n, fn["name"]) for n, d in mods.items() for fn in d["funcs"]}
    known |= {"%s.%s" % (c["full"], m["name"]) for c in classes for m in c["meths"]}
    stale = sorted(set(overrides) - known)
    if stale:
        sys.exit("runtime_overrides.json names calls that are not in the reference: %s"
                 % ", ".join(stale))

    total = 0
    # ---- per-module files ----
    for name, d in mods.items():
        L = [f"# {name}", ""]
        if d["brief"]:
            L += [d["brief"], ""]
        L += ["Apex release: Iberian Lynx FP2. All arguments are keyword-only.", ""]

        if d["enums"]:
            L += ["## Enumerations", ""]
            for e in d["enums"]:
                full = f"{name}.{e['name']}"
                members = enum_members(e["values"])
                if len(members) <= ENUM_WRAP:
                    L.append(f"`{full}`: {members}")
                    if e["brief"]:
                        L.append(f"  - {e['brief']}")
                else:
                    # long list: the description goes first so a trimmed read keeps it
                    head = f"`{full}` — {len(e['values'])} members"
                    if e["brief"]:
                        head += f". {e['brief']}"
                    L.append(head)
                    for chunk in enum_chunks(e["values"]):
                        L.append(f"  - `{full}`: {chunk}")
                L.append("")

        if d["funcs"]:
            L += ["## Module functions", ""]
            for fn in d["funcs"]:
                L.append(f"### `{name}.{sig(fn)}`")
                L += override_lines(overrides.get(f"{name}.{fn['name']}", []))
                emit_detail(L, fn)
                L.append("")

        cs = sorted(by_mod.get(name, []), key=lambda x: x["short"])
        if cs:
            L += ["## Classes in this module", "",
                  f"Full method signatures are in `api/classes/{name}.md`.", "",
                  ", ".join("`%s`" % c["short"] for c in cs), ""]

        total += w(os.path.join(OUT, "api", "modules", f"{name}.md"), "\n".join(L) + "\n")

        if cs:
            C = [f"# {name} — classes", "",
                 "Properties are read via `obj.prop` or `obj.getProp()`. Entity-derived",
                 "classes have no setters: change them with `obj.update(...)`.", ""]
            for c in cs:
                head = f"## `{c['full']}`"
                if c["bases"]:
                    head += "  (extends %s)" % ", ".join("`%s`" % b for b in c["bases"])
                C.append(head)
                if c["brief"]:
                    C.append(c["brief"])
                if c["props"]:
                    C.append("Properties: " + ", ".join("`%s`" % p for p in c["props"]))
                if c["meths"]:
                    # Every signature first, one line each, then the prose under
                    # "Method details", so a trimmed read still has the list.
                    C += ["", "Methods:", ""]
                    details = []
                    for m in c["meths"]:
                        ovs = overrides.get(f"{c['full']}.{m['name']}", [])
                        sb = short_brief(m["brief"])
                        C.append(f"- `{sig(m)}`" + (f" — {sb}" if sb else "") + override_tag(ovs))
                        rem = m.get("remarks")
                        if (m.get("pdocs") or m.get("returns") or ovs or sb != m["brief"]
                                or (rem and rem != m["brief"])):
                            details.append((m, ovs))
                    if details:
                        C += ["", "Method details:", ""]
                        for m, ovs in details:
                            C.append(f"#### `{sig(m)}`")
                            C += override_lines(ovs)
                            emit_detail(C, m)
                            C.append("")
                C.append("")
            total += w(os.path.join(OUT, "api", "classes", f"{name}.md"), "\n".join(C) + "\n")

    # ---- flat function lookup ----
    L = ["# Function lookup index", "",
         "Flat, greppable list of every module-level function. Grep this file for a",
         "verb or noun, then open `api/modules/<module>.md` for the full signature.",
         ""]
    rows = []
    for name, d in mods.items():
        for fn in d["funcs"]:
            rows.append((fn["name"], name, fn["brief"]))
    for fn, mod, br in sorted(rows):
        tag = override_tag(overrides.get(f"{mod}.{fn}", []))
        L.append((f"- `{mod}.{fn}` — {br}" if br else f"- `{mod}.{fn}`") + tag)
    total += w(os.path.join(OUT, "api", "functions-index.md"), "\n".join(L) + "\n")

    # ---- flat method lookup ----
    by_full = {c["full"]: c for c in classes}
    by_short = collections.defaultdict(list)
    for c in classes:
        by_short[c["short"]].append(c["full"])

    def resolve_base(b, mod):
        if b in by_full:
            return b
        cands = by_short.get(b.rsplit(".", 1)[-1], [])
        same = [x for x in cands if x.rsplit(".", 1)[0] == mod]
        return (same or cands or [None])[0]

    children = collections.defaultdict(set)
    for c in classes:
        for b in c["bases"]:
            p = resolve_base(b, c["module"])
            if p and p != c["full"]:
                children[p].add(c["full"])

    def descendants(full):
        seen, todo = set(), [full]
        while todo:
            for ch in children.get(todo.pop(), ()):
                if ch not in seen:
                    seen.add(ch)
                    todo.append(ch)
        return seen

    L = ["# Method lookup index", "",
         "Flat, greppable list of every class method as `module.Class.method`, one",
         "line per method name. A method is listed on the class that declares it;",
         "\"inherited by\" names the classes that get it from there. Open",
         "`api/classes/<module>.md` for the signature and argument documentation.",
         ""]
    mcount = 0
    for c in sorted(classes, key=lambda x: x["full"]):
        if not c["meths"]:
            continue
        desc = descendants(c["full"])
        if not desc:
            inh = ""
        elif len(desc) <= 6:
            inh = " (inherited by %s)" % ", ".join("`%s`" % by_full[x]["short"] for x in sorted(desc))
        else:
            inh = " (inherited by %d classes)" % len(desc)
        groups = collections.OrderedDict()
        for m in c["meths"]:
            groups.setdefault(m["name"], []).append(m)
        for mname, ms in groups.items():
            mcount += 1
            line = f"- `{c['full']}.{mname}`"
            if len(ms) > 1:
                line += f" ({len(ms)} overloads)"
            sb = next((short_brief(m["brief"]) for m in ms if m["brief"]), "")
            if sb:
                line += f" — {sb}"
            L.append(line + override_tag(overrides.get(f"{c['full']}.{mname}", [])) + inh)
    total += w(os.path.join(OUT, "api", "methods-index.md"), "\n".join(L) + "\n")

    # ---- enums ----
    L = ["# Enumeration reference", "",
         "Every enumeration in the apex package with its exact members.",
         "Never invent an enum member; use one listed here.", ""]
    ecount = 0
    for name, d in mods.items():
        if not d["enums"]:
            continue
        L += [f"## {name}", ""]
        for e in d["enums"]:
            ecount += 1
            full = f"{name}.{e['name']}"
            members = enum_members(e["values"])
            dep = " — DEPRECATED" if "DEPRECATED" in e["brief"] else ""
            if len(members) <= ENUM_WRAP:
                L.append(f"- `{full}`: {members}{dep}")
            else:
                L.append(f"- `{full}` — {len(e['values'])} members, wrapped below{dep}")
                for chunk in enum_chunks(e["values"]):
                    L.append(f"  - `{full}`: {chunk}")
        L.append("")
    total += w(os.path.join(OUT, "api", "enums.md"), "\n".join(L) + "\n")

    # ---- class index ----
    L = ["# Class index", "",
         "Class -> module, base classes, and property names. Open",
         "`api/modules/<module>.md` for full method signatures.", ""]
    for c in sorted(classes, key=lambda x: x["full"]):
        line = f"- `{c['full']}`"
        if c["bases"]:
            line += " extends " + ", ".join(c["bases"])
        if c["brief"]:
            line += f" — {c['brief']}"
        L.append(line)
    total += w(os.path.join(OUT, "api", "classes.md"), "\n".join(L) + "\n")

    print("modules:", len(mods))
    print("functions:", len(rows))
    print("methods:", mcount)
    print("runtime overrides:", sum(len(v) for v in overrides.values()))
    print("enums:", ecount)
    print("classes:", len(classes))
    print("bytes written:", total)
    for name in mods:
        p = os.path.join(OUT, "api", "modules", f"{name}.md")
        cp = os.path.join(OUT, "api", "classes", f"{name}.md")
        csz = os.path.getsize(cp) if os.path.exists(cp) else 0
        print("  %-20s mod=%7d  classes=%7d" % (name, os.path.getsize(p), csz))


if __name__ == "__main__":
    main()
