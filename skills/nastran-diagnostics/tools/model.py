"""Load a Nastran deck with pyNastran, keeping file:line for every card.

    from model import load_deck
    ld = load_deck("model.bdf", include_dirs=[], sink=None, workdir=None)
    ld.bdf          pyNastran BDF (not cross-referenced except coordinates)
    ld.contact      [card_specs.Card] contact cards, named via card_specs
    ld.rejected     Counter of card types pyNastran has no class for and SPECS
                    does not cover ("card types not interpreted")
    ld.problems     [(loc, message)] cards pyNastran could not interpret
    ld.includes     [(spec, found)]
    ld.locs         {family: {id: "file:line"}} first definition of each ID
    ld.dups         {family: [(id, loc_first, loc_dup)]}
    ld.comments     header $ comments of the master file (unit system hints)
    ld.case_control raw case control lines; ld.executive, ld.sol

pyNastran is the only tokenizer. BDF._parse_cards_list is overridden so each
card passes through here once, in file order, with its (file, line) from
pyNastran's own line index. That gives three things pyNastran 1.4.1 does not
keep: file:line per card, identical duplicates (pyNastran drops them
silently), and the fields of cards it rejects, which card_specs then names.

pyNastran 1.4.1 API notes (verified on Python 3.12, numpy 1.26):
- read_bdf(save_file_structure=True) raises NotImplementedError on any
  rejected card (BCBODY1, BCONECT, ...), so it is not used; ilines are.
- iline is 0-based; the line reported here is iline + 1.
- A missing INCLUDE raises OSError and writes pyNastran_crash.bdf into the
  current directory, so INCLUDEs are resolved here first.
- Coord.transform_vector_to_global treats the vector as a point, which is
  wrong for a FORCE direction in a cylindrical/spherical system; deck_checks
  rotates with the local basis at the grid instead, from Coord.origin/i/j/k.
- CaseControlDeck keeps subcase 0 as the global block; values are
  [value, options, type] lists.
"""
from __future__ import annotations

import collections
import contextlib
import io
import os
import re
import tempfile

from deps import require

require()

from cpylog import SimpleLogger  # noqa: E402
from pyNastran.bdf.bdf import BDF, CaseControlDeck  # noqa: E402
from pyNastran.bdf.bdf_interface.utils import to_fields  # noqa: E402

from card_specs import Card, interpret, to_int  # noqa: E402

FAMILIES = (("GRID", ("nodes",)), ("ELEMENT", ("elements", "rigid_elements", "masses")),
            ("PROPERTY", ("properties",)), ("MATERIAL", ("materials", "hyperelastic_materials")),
            ("COORD", ("coords",)))
CONTACT_CARDS = {"BCSURF", "BSURF", "BCPROP", "BCBODY", "BCBODY1", "BCONECT", "BCTABLE",
                 "BCTABL1", "BCONPRG", "BCONPRP", "BGSET", "BCTSET", "BCTPARA", "BCTPARM",
                 "BCPARA", "BGPARM", "BCRPARA", "BCTADD", "BGADD"}
_RX_INCLUDE = re.compile(r"^\s*INCLUDE\s+(.*)$", re.I)


def _quiet_log():
    return SimpleLogger(level="critical")


class Loaded:
    def __init__(self):
        self.bdf = None
        self.contact = []
        self.rejected = collections.Counter()
        self.problems = []
        self.includes = []
        self.locs = {f: {} for f, _ in FAMILIES}
        self.first_locs = {}      # (card name, id) -> first "file:line", for non-family cards (SPC1 sets...)
        self.dups = collections.defaultdict(list)
        self.card_count = collections.Counter()
        self.comments = []
        self.case_control = []
        self.executive = []
        self.sol = None
        self.files = []

    def loc(self, family, id_):
        return self.locs[family].get(id_, "?")


class _DiagBDF(BDF):
    """BDF whose card loop reports every card to a Loaded."""

    def _parse_cards_list(self, cards_list, strict=True):
        ld, sink = self._ld, self._sink
        names = self._display_names
        family_of = {}
        for icard, (name, comment, lines, (ifile, iline)) in enumerate(cards_list):
            name = (name or "").rstrip("*").upper()
            ifile, iline = int(ifile), int(iline)
            fname = names.get(ifile, "?")
            if "=" in name:  # replication: let pyNastran expand it
                try:
                    for rep in self._expand_replication(name, icard, cards_list, lines):
                        self.add_card(rep, rep[0], comment=comment, ifile=ifile, is_list=True, has_none=True)
                except Exception as e:  # noqa: BLE001
                    ld.problems.append(("%s:%d" % (fname, iline + 1), "replication %s not expanded: %s" % (name, e)))
                continue
            ld.card_count[name] += 1
            if self.is_reject(name):
                try:
                    flds = to_fields(lines, name)
                except Exception as e:  # noqa: BLE001
                    ld.problems.append(("%s:%d" % (fname, iline + 1), "%s not tokenized: %s" % (name, e)))
                    continue
                c = _card(name, flds, fname, iline + 1)
                if not interpret(c):
                    ld.rejected[name] += 1
                if c.i(1) is not None:
                    ld.first_locs.setdefault((name, c.i(1)), c.loc)
                if name in CONTACT_CARDS:
                    ld.contact.append(c)
                if sink:
                    sink(c)
                continue
            n_err = len(self._stored_parse_errors)
            try:
                co = self.add_card(lines, name, comment=comment, ifile=ifile, is_list=False, has_none=False)
            except Exception as e:  # noqa: BLE001 - never raise on a bad card
                ld.problems.append(("%s:%d" % (fname, iline + 1), "%s could not be interpreted: %s" % (name, e)))
                co = None
            if len(self._stored_parse_errors) > n_err:
                err = self._stored_parse_errors[-1][1]
                ld.problems.append(("%s:%d" % (fname, iline + 1), "%s could not be interpreted: %s"
                                    % (name, " ".join(err).strip()[:160])))
            if co is None:
                continue
            c = _card(name, co.card, fname, iline + 1)
            id_ = c.i(1)
            fam = family_of.get(name, 0)
            if fam == 0:
                fam = self._family(name, id_)
                if fam is not None:
                    family_of[name] = fam
            if fam and id_ is not None:
                seen = ld.locs[fam]
                if id_ in seen:
                    ld.dups[fam].append((id_, seen[id_], c.loc))
                else:
                    seen[id_] = c.loc
            elif id_ is not None:
                ld.first_locs.setdefault((name, id_), c.loc)
            if name in CONTACT_CARDS:
                ld.contact.append(c)
            if sink:
                sink(c)

    def _family(self, name, id_):
        for fam, attrs in FAMILIES:
            for a in attrs:
                obj = getattr(self, a, {}).get(id_)
                if obj is not None and getattr(obj, "type", None) == name:
                    return fam
        return None


def _card(name, flds, fname, line):
    f = [name] + ["" if v is None else str(v).strip() for v in list(flds)[1:]]
    while len(f) > 1 and f[-1] == "":
        f.pop()
    return Card(name, f, fname, line)


# ------------------------------------------------------------------ includes
def _resolve_include(spec, cur_file, include_dirs):
    spec = spec.strip().strip("'\"").strip()
    cands = [spec, os.path.join(os.path.dirname(cur_file), spec)]
    cands += [os.path.join(d, spec) for d in include_dirs]
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    base = os.path.basename(spec.replace("\\", "/"))
    for d in [os.path.dirname(cur_file)] + list(include_dirs):
        c = os.path.join(d, base)
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def _prepare_includes(path, include_dirs, ld, workdir, display, depth=0):
    """Resolve every INCLUDE before pyNastran sees it.

    Returns the path pyNastran should read for `path`: the file itself, or a
    copy in workdir whose INCLUDEs point at absolute paths (missing ones
    commented out). `display` maps any path read to the name findings show."""
    try:
        with open(path, "r", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as e:
        ld.problems.append((os.path.basename(path), "cannot open: %s" % e))
        return path
    out, changed, pending, start = [], False, None, 0
    for n, line in enumerate(lines, 1):
        m = _RX_INCLUDE.match(line) if pending is None else None
        if pending is None and not m:
            out.append(line)
            continue
        txt = (pending or "") + (m.group(1).strip() if m else line.strip())
        if pending is None:
            start = n
        if txt.count("'") == 1 or txt.count('"') == 1:
            pending = txt
            continue
        pending = None
        spec = txt.strip().strip("'\"")
        inc = _resolve_include(txt, path, include_dirs)
        ld.includes.append((spec, bool(inc)))
        if not inc:
            ld.problems.append(("%s:%d" % (os.path.basename(path), start), "INCLUDE not found: %s" % spec))
            out.append("$ INCLUDE not found, skipped: %s\n" % spec)
            changed = True
            continue
        if depth > 20:
            ld.problems.append(("%s:%d" % (os.path.basename(path), start), "INCLUDE nesting too deep"))
            out.append("$ INCLUDE too deep, skipped: %s\n" % spec)
            changed = True
            continue
        target = _prepare_includes(inc, include_dirs, ld, workdir, display, depth + 1)
        out.append("INCLUDE '%s'\n" % target.replace("\\", "/"))
        changed = True   # always absolute, so the copy reads from anywhere
    if not changed:
        display[os.path.abspath(path)] = os.path.basename(path)
        return path
    sub = tempfile.mkdtemp(dir=workdir)
    cp = os.path.join(sub, os.path.basename(path))
    with open(cp, "w") as fh:
        fh.writelines(out)
    display[os.path.abspath(cp)] = os.path.basename(path)
    return cp


def _is_bulk_only(path, max_lines=200000):
    try:
        with open(path, "r", errors="replace") as fh:
            for k, line in enumerate(fh):
                u = line.lstrip().upper()
                if u.startswith("CEND"):   # BEGIN BULK alone is still a bulk-only file
                    return False
                if k > max_lines:
                    break
    except OSError:
        return False
    return True


def _header_comments(path, n=200):
    out = []
    try:
        with open(path, "r", errors="replace") as fh:
            for k, line in enumerate(fh):
                s = line.strip()
                if s.startswith("$"):
                    out.append(s.lstrip("$").strip())
                    if len(out) >= n:
                        break
                if k > 4000:
                    break
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ load
def load_deck(path, include_dirs=(), sink=None, workdir=None):
    """Read a deck. Raises only if pyNastran cannot read it at all."""
    ld = Loaded()
    include_dirs = list(include_dirs)
    own_tmp = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix="ndiag_deck_")
    os.makedirs(workdir, exist_ok=True)
    display = {}
    read_path = os.path.abspath(_prepare_includes(path, include_dirs, ld, workdir, display))
    ld.comments = _header_comments(path)
    bdf = _DiagBDF(debug=None, log=_quiet_log())
    bdf._ld, bdf._sink = ld, sink
    bdf._stop_on_duplicate_error = False
    bdf._stop_on_parsing_error = False
    bdf._stop_on_xref_error = False
    bdf._nparse_errors = 10 ** 9
    bdf._display_names = {}
    orig_get_lines = bdf._set_pybdf_attributes

    def set_attrs(obj, save_file_structure=False):
        orig_get_lines(obj, save_file_structure)
        bdf._display_names = {i: display.get(os.path.abspath(p), os.path.basename(p))
                              for i, p in enumerate(bdf.active_filenames)}
    bdf._set_pybdf_attributes = set_attrs
    cwd = os.getcwd()
    try:
        os.chdir(workdir)   # pyNastran writes pyNastran_crash.bdf into the cwd on failure
        with contextlib.redirect_stdout(io.StringIO()):
            bdf.read_bdf(read_path, xref=False, validate=False, punch=_is_bulk_only(read_path),
                         encoding="latin1")
    finally:
        os.chdir(cwd)
    ld.files = [bdf._display_names.get(i) for i in sorted(bdf._display_names)]
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            bdf.safe_cross_reference(xref=True, xref_nodes=True, xref_elements=False,
                                     xref_properties=False, xref_masses=False, xref_materials=False,
                                     xref_loads=False, xref_constraints=False, xref_aero=False,
                                     xref_sets=False, xref_optimization=False, debug=False)
        except Exception as e:  # noqa: BLE001
            ld.problems.append(("coordinates", "coordinate systems not resolved: %s" % e))
    ld.bdf = bdf
    ld.case_control = [s for s in (bdf.case_control_lines or []) if s.strip()]
    ld.executive = list(bdf.executive_control_lines or [])
    ld.sol = bdf.sol
    if own_tmp:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
    return ld


# ------------------------------------------------------------------ case control
def parse_case_control(lines):
    """Case control lines -> {'global': {KEY: val}, 'subcases': {id: {KEY: val}}, 'params': [..]}.

    Parsed by pyNastran's CaseControlDeck; values are upper-case strings."""
    out = {"global": {}, "subcases": {}, "params": []}
    txt = [(x[0] if isinstance(x, tuple) else x) for x in lines]
    txt = [t for t in txt if t.strip() and not t.strip().upper().startswith(("BEGIN", "CEND"))]
    if not txt:
        return out
    with contextlib.redirect_stdout(io.StringIO()):
        deck = CaseControlDeck(txt, log=_quiet_log())
    # PARAM statements: one key per subcase in CaseControlDeck, so read them from the text
    out["params"] = [re.sub(r"\s+", "", t.split("$", 1)[0]).upper() for t in txt
                     if t.strip().upper().startswith("PARAM")]
    for sid, sc in deck.subcases.items():
        d = {}
        for key, val in sc.params.items():
            if key == "PARAM":
                continue
            v = val[0] if isinstance(val, (list, tuple)) else val
            d[key.upper()] = str(v).upper()
        if sid == 0:
            out["global"] = d
        else:
            out["subcases"][sid] = d
    return out
