"""Deterministic deck checks for a Nastran model.

    python tools/deck_checks.py model.bdf [-o outdir] [-I include_dir]

The deck is read by pyNastran (tools/model.py); cards pyNastran has no class
for are tokenized by pyNastran and named from the QRG layouts in
tools/card_specs.py. This module builds a compact model from those objects,
then runs checks that Nastran either does not do or reports only as a
consequence (a singular matrix, a rigid-body mode) far from the cause. Each
check emits findings:

    {code, severity, title, detail, count, ids, locs, basis, route}

basis is always "computed": these are facts about THIS deck, the third kind of
statement in references/answering-rules.md (neither catalogue text nor
extrapolation). route names the nastran-reference entries and the apex-docs
question that fix the finding.

The checks never raise on a malformed card: whatever cannot be interpreted is
counted and reported, so the rest of the report still arrives.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deps import require  # noqa: E402

require()

import numpy as np  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

from card_specs import expand_thru, to_float, to_int  # noqa: E402
from model import CONTACT_CARDS, load_deck, parse_case_control  # noqa: E402

# ----------------------------------------------------------------------------
# element knowledge
# ----------------------------------------------------------------------------
SHELLS = {"CQUAD4", "CQUADR", "CQUAD8", "CQUAD", "CTRIA3", "CTRIAR", "CTRIA6", "CSHEAR"}
SOLIDS = {"CHEXA", "CPENTA", "CTETRA", "CPYRAM"}
LINES = {"CBAR", "CBEAM", "CBEND", "CROD", "CTUBE", "CONROD"}
SPRINGS = {"CBUSH", "CBUSH1D", "CGAP", "CELAS1", "CELAS2", "CDAMP1", "CDAMP2", "CVISC"}
# element types that join parts; CFAST/CWELD are kept but join nothing (see run-digest.md)
ELEM_TYPES = SHELLS | SOLIDS | LINES | SPRINGS | {"CFAST", "CWELD"}
MASS_TYPES = {"CONM2", "CONM1", "CMASS1", "CMASS2"}
PROP_OK = {
    "shell": {"PSHELL", "PCOMP", "PCOMPG", "PSHEAR", "PLPLANE", "PSHLN1"},
    "solid": {"PSOLID", "PLSOLID", "PCOMPS", "PCOMPLS", "PSLDN1"},
    "beam": {"PBEAM", "PBEAML", "PBCOMP", "PBMSECT", "PBEAM3"},
    "bar": {"PBAR", "PBARL", "PBRSECT"},
    "rod": {"PROD"}, "tube": {"PTUBE"}, "bush": {"PBUSH", "PBUSHT"}, "bush1d": {"PBUSH1D"},
    "gap": {"PGAP"}, "elas": {"PELAS"}, "damp": {"PDAMP"}, "visc": {"PVISC"}, "bend": {"PBEND"},
}
ELEM_FAMILY = {**{e: "shell" for e in SHELLS}, **{e: "solid" for e in SOLIDS},
               "CBEAM": "beam", "CBAR": "bar", "CROD": "rod", "CTUBE": "tube", "CBUSH": "bush",
               "CBUSH1D": "bush1d", "CGAP": "gap", "CELAS1": "elas", "CDAMP1": "damp",
               "CVISC": "visc", "CBEND": "bend"}
PROP_CARDS = set().union(*PROP_OK.values())

# faces for volume by the divergence theorem (outward, MSC node order)
FACES = {
    "CHEXA": ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
    "CPENTA": ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
    "CTETRA": ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
    "CPYRAM": ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
}
CORNERS = {"CHEXA": 8, "CPENTA": 6, "CTETRA": 4, "CPYRAM": 5}
UNIT_LEN = {"M": 1.0, "MM": 1000.0, "CM": 100.0, "IN": 39.3701, "FT": 3.28084}
UNIT_TIME = {"S": 1.0, "SEC": 1.0, "MS": 1000.0}

# how each finding is fixed: (nastran-reference entries, apex-docs question)
ROUTES = {
    "PARSE_PROBLEM": ([], None),
    "INCLUDE_MISSING": (["INCLUDE"], None),
    "DUPLICATE_ID": ([], "how to renumber entities"),
    "MISSING_GRID": (["GRID"], None),
    "MISSING_PROPERTY": (["PSHELL", "PSOLID", "PCOMP"], "how to assign a property to a mesh"),
    "MISSING_MATERIAL": (["MAT1", "MAT8"], "how to assign a material"),
    "PROPERTY_TYPE_MISMATCH": (["PSHELL", "PSOLID", "PBEAML"], "how to assign a property to a mesh"),
    "MISSING_SET": (["LOAD", "SPC", "MPC", "BCONTACT"], "how to define a load or constraint in an analysis scenario"),
    "ORPHAN_GRID": (["GRID"], "how to delete unused nodes"),
    "FLOATING_MASS": (["CONM2", "RBE3"], "how to connect a lumped mass to the structure"),
    "UNUSED_PROPERTY": ([], None),
    "UNCONSTRAINED_GROUP": (["SPC1", "BCONECT", "RBE2"], "how to constrain or connect a part"),
    "GLUE_DEPENDENT_LOAD_PATH": (["BCONECT", "BCONPRG", "BCTABL1"], "how to create glued contact between parts"),
    "GLUE_COARSE_SECONDARY": (["BCONECT"], "how to swap source and target in a glued contact"),
    "GLUE_UNRESOLVED": (["BCONECT", "BCSURF", "BCBODY1"], "how to define contact bodies"),
    "GLUE_SAME_COMPONENT": (["BCONECT"], None),
    "UNUSED_CONTACT_SURFACE": (["BCSURF"], None),
    "CONTACT_NOT_ANALYSED": (["BGSET", "BCTABLE"], None),
    "COINCIDENT_UNMERGED": (["GRID"], "how to merge coincident nodes"),
    "SPC_ON_DEPENDENT": (["SPC1", "RBE2", "RBE3"], "how to edit a rigid connection"),
    "DOUBLE_DEPENDENT": (["RBE2", "RBE3", "MPC"], "how to edit a rigid connection"),
    "SPC_ON_UNATTACHED": (["SPC1"], "how to edit a constraint"),
    "LOAD_ON_UNATTACHED": (["FORCE"], "how to edit a load"),
    "POINT_LOAD_ONLY": (["GRAV", "ACCEL", "FORCE", "LOAD"], "how to apply a gravity or acceleration load"),
    "MIXED_UNITS": (["MAT1", "MAT8", "PARAM"], "how to set the unit system"),
    "ZERO_DENSITY": (["MAT1", "MAT8"], "how to edit material density"),
    "WTMASS": (["PARAM"], None),
    "OUTPUT_GAP": (["SPCFORCE", "PARAM"], "how to request output in an analysis scenario"),
    "NO_CASE_CONTROL": ([], None),
}
SEV_ORDER = {"error": 0, "warn": 1, "info": 2}


# ----------------------------------------------------------------------------
# small vector helpers
# ----------------------------------------------------------------------------
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def mul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a): return math.sqrt(dot(a, a))


class UF:
    """Union-find over arbitrary hashable keys."""
    def __init__(self):
        self.p = {}

    def find(self, x):
        p = self.p
        if x not in p:
            p[x] = x
            return x
        r = x
        while p[r] != r:
            r = p[r]
        while p[x] != r:
            p[x], x = r, p[x]
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _comps(c):
    """pyNastran component field -> '123456'-style string ('' when blank or 0)."""
    s = "" if c is None else str(c).strip()
    return "" if s in ("", "0") else s


def _ids(xs):
    return [x for x in (xs or []) if isinstance(x, (int, np.integer)) and x > 0]


# ----------------------------------------------------------------------------
# model: compact containers filled from the pyNastran BDF
# ----------------------------------------------------------------------------
class Model:
    def __init__(self):
        self.files = []
        self.grids = {}          # gid -> (cp, x, y, z, cd, ps, loc)
        self.coords = {}         # cid -> pyNastran coord
        self.elems = {}          # eid -> (name, pid, nodes, loc, extra)  extra: CONROD (mid, A)
        self.rigids = {}         # eid -> (name, indep, dep, dep_comps, loc)  dep_comps: {gid: comps}
        self.masses = {}         # eid -> (name, gid, mass, loc)
        self.mpcs = collections.defaultdict(list)   # sid -> [(grids, loc)]
        self.spcs = collections.defaultdict(list)   # sid -> [(name, comps, grids, loc)]
        self.spcadd = {}         # sid -> [sids]
        self.mpcadd = {}
        self.loads = collections.defaultdict(list)  # sid -> [dict]
        self.load_combo = {}     # sid -> (scale, [(s, lid)], loc)
        self.props = {}          # pid -> pyNastran property (.type)
        self.mats = {}           # mid -> pyNastran material (.type)
        self.params = {}
        self.contact = collections.defaultdict(list)  # name -> [card_specs.Card]
        self.card_count = collections.Counter()
        self.unknown = collections.Counter()
        self.dups = collections.defaultdict(list)  # family -> [(id, loc_first, loc_dup)]
        self.suport = []
        self.problems = []
        self.comments = []
        self.case_control = []
        self.executive = []
        self.includes = []
        self.sol = None
        self.bdf = None
        self.ld = None
        self._pos = {}

    def loc(self, family, id_):
        return self.ld.loc(family, id_) if self.ld else "?"

    # ---------------------------------------------------------------- coords
    def csys(self, cid):
        """cid -> (type, origin, (ex, ey, ez)) in basic, or None."""
        if cid in (0, None):
            return ("R", (0.0, 0.0, 0.0), ((1.0, 0, 0), (0, 1.0, 0), (0, 0, 1.0)))
        c = self.coords.get(cid)
        if c is None or getattr(c, "i", None) is None:
            return None
        return (c.type[-1], tuple(c.origin), (tuple(c.i), tuple(c.j), tuple(c.k)))

    def vec_to_basic(self, cid, v, at):
        """Direction v given in cid, evaluated at basic point `at` (the local
        r/theta/z or r/theta/phi basis at that point for C and S systems)."""
        cs = self.csys(cid)
        if cs is None:
            return None
        t, o, (ex, ey, ez) = cs
        if t != "R" and at is not None:
            d = sub(at, o)
            x, y, z = dot(d, ex), dot(d, ey), dot(d, ez)
            if t == "C":
                th = math.atan2(y, x)
                er, et = (math.cos(th), math.sin(th), 0.0), (-math.sin(th), math.cos(th), 0.0)
                v = add(add(mul(er, v[0]), mul(et, v[1])), (0.0, 0.0, v[2]))
            else:
                r = math.sqrt(x * x + y * y + z * z) or 1.0
                th, ph = math.acos(max(-1, min(1, z / r))), math.atan2(y, x)
                er = (math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th))
                et = (math.cos(th) * math.cos(ph), math.cos(th) * math.sin(ph), -math.sin(th))
                ep = (-math.sin(ph), math.cos(ph), 0.0)
                v = add(add(mul(er, v[0]), mul(et, v[1])), mul(ep, v[2]))
        return add(add(mul(ex, v[0]), mul(ey, v[1])), mul(ez, v[2]))

    def pos(self, gid):
        return self._pos.get(gid)


def _fill_positions(m, bdf):
    """Basic-frame positions for every grid, from pyNastran's transforms."""
    try:
        _, icp, xyz_cp, nid_cp_cd = bdf.get_displacement_index_xyz_cp_cd()
        xyz = bdf.transform_xyzcp_to_xyz_cid(xyz_cp, nid_cp_cd[:, 0], icp, cid=0)
        m._pos = {int(n): (float(p[0]), float(p[1]), float(p[2])) for n, p in zip(nid_cp_cd[:, 0], xyz)}
        return
    except Exception as e:  # noqa: BLE001 - fall back node by node
        m.problems.append(("coordinates", "vectorised transform failed (%s); positions per grid" % e))
    for gid, n in bdf.nodes.items():
        try:
            m._pos[gid] = tuple(float(x) for x in n.get_position())
        except Exception:  # noqa: BLE001 - grid in an unresolved coordinate system
            if (n.cp or 0) == 0:
                m._pos[gid] = tuple(float(x) for x in n.xyz)


def _rigid(r):
    """pyNastran rigid element -> (independent grids, dependent grids, {dep grid: comps})."""
    t = r.type
    indep, dep, depc = [], [], {}
    if t == "RBE2":
        indep = _ids([r.gn])
        dep = _ids(r.Gmi)
        depc = {g: _comps(r.cm) for g in dep}
    elif t == "RBE3":
        dep = _ids([r.refgrid])
        depc = {g: _comps(r.refc) for g in dep}
        um = _ids(r.Gmi)
        for g, c in zip(r.Gmi or [], r.Cmi or []):
            if g:
                depc[g] = _comps(c)
        dep += um
        indep = [g for gs in (r.Gijs or []) for g in _ids(gs) if g not in um]
    elif t == "RBAR":
        ends = ((r.ga, r.cna, r.cma), (r.gb, r.cnb, r.cmb))
        for g, cn, cm in ends:
            if not g:
                continue
            if _comps(cm):
                dep.append(g)
                depc[g] = _comps(cm)
            else:
                indep.append(g)
        if not dep and r.gb:  # all blank: GB dependent in all six
            indep, dep, depc = _ids([r.ga]), [r.gb], {r.gb: "123456"}
    elif t == "RBAR1":
        indep, dep = _ids([r.ga]), _ids([r.gb])
        depc = {g: _comps(r.cb) or "123456" for g in dep}
    elif t == "RROD":
        ga, gb = (list(r.nodes) + [None, None])[:2]
        if _comps(r.cma):
            indep, dep, depc = _ids([gb]), _ids([ga]), {ga: _comps(r.cma)}
        else:
            indep, dep, depc = _ids([ga]), _ids([gb]), {gb: _comps(r.cmb) or "123456"}
    elif t == "RBE1":
        indep = _ids(r.Gni)
        dep = _ids(r.Gmi)
        depc = {g: _comps(c) for g, c in zip(r.Gmi, r.Cmi) if g}
    else:
        try:
            indep = _ids(r.independent_nodes)
            dep = _ids(r.dependent_nodes)
        except Exception:  # noqa: BLE001
            indep, dep = [], []
        depc = {g: "123456" for g in dep}
    return tuple(indep), tuple(dep), depc


def _fill(m, ld):
    bdf = m.bdf = ld.bdf
    m.ld = ld
    m.files = ld.files
    m.card_count = ld.card_count
    m.dups = ld.dups
    m.problems = list(ld.problems)
    m.comments, m.case_control, m.executive = ld.comments, ld.case_control, ld.executive
    m.includes, m.sol = ld.includes, (str(ld.sol) if ld.sol is not None else None)
    m.unknown.update(ld.rejected)
    first = ld.first_locs
    L = ld.loc

    for gid, n in bdf.nodes.items():
        m.grids[gid] = (n.cp or 0, n.xyz[0], n.xyz[1], n.xyz[2], n.cd or 0, _comps(n.ps), L("GRID", gid))
    m.coords = bdf.coords
    _fill_positions(m, bdf)

    for eid, e in bdf.elements.items():
        t = e.type
        if t not in ELEM_TYPES:
            m.unknown[t] += 1
            continue
        if t in ("CFAST", "CWELD"):
            m.elems[eid] = (t, getattr(e, "pid", None), (), L("ELEMENT", eid), None)
            continue
        try:
            nodes = tuple(_ids(e.node_ids))
        except Exception:  # noqa: BLE001
            nodes = ()
        if t == "CONROD":
            m.elems[eid] = (t, None, nodes, L("ELEMENT", eid), (e.mid, e.A or 0.0))
        else:
            m.elems[eid] = (t, getattr(e, "pid", None), nodes, L("ELEMENT", eid), None)
    for eid, e in bdf.masses.items():
        t = e.type
        if t not in MASS_TYPES:
            m.unknown[t] += 1
            continue
        if t in ("CONM2", "CONM1"):
            g, mass = e.nid, (e.mass if t == "CONM2" else 0.0)
        else:
            nid = _ids(e.node_ids)
            g, mass = (nid[0] if nid else None), (e.mass if t == "CMASS2" else 0.0)
        m.masses[eid] = (t, g, mass or 0.0, L("ELEMENT", eid))
    for eid, r in bdf.rigid_elements.items():
        try:
            ind, dep, depc = _rigid(r)
        except Exception as e:  # noqa: BLE001
            m.problems.append((L("ELEMENT", eid), "%s %s could not be interpreted: %s" % (r.type, eid, e)))
            continue
        m.rigids[eid] = (r.type, ind, dep, depc, L("ELEMENT", eid))

    for sid, cards in bdf.spcs.items():
        for c in cards:
            loc = first.get((c.type, sid), "?")
            if c.type == "SPC1":
                m.spcs[sid].append((c.type, _comps(c.components), _ids(c.nodes), loc))
            elif c.type == "SPC":
                for g, comp in zip(c.nodes, c.components):
                    if g:
                        m.spcs[sid].append((c.type, _comps(comp), [g], loc))
            else:
                m.unknown[c.type] += 1
    for sid, cards in bdf.spcadds.items():
        m.spcadd[sid] = [s for c in cards for s in c.sets]
    for sid, cards in bdf.mpcadds.items():
        m.mpcadd[sid] = [s for c in cards for s in c.sets]
    for sid, cards in bdf.mpcs.items():
        for c in cards:
            m.mpcs[sid].append((_ids(getattr(c, "nodes", [])), first.get((c.type, sid), "?")))

    for sid, cards in bdf.loads.items():
        for c in cards:
            t = c.type
            loc = first.get((t, sid), "?")
            if t in ("FORCE", "MOMENT"):
                m.loads[sid].append({"type": t, "g": c.node, "cid": c.cid or 0, "f": c.mag or 0.0,
                                     "n": tuple(float(x) for x in c.xyz), "loc": loc})
            elif t == "GRAV":
                m.loads[sid].append({"type": t, "cid": c.cid or 0, "a": c.scale or 0.0,
                                     "n": tuple(float(x) for x in c.N), "loc": loc})
            elif t in ("FORCE1", "FORCE2", "MOMENT1", "MOMENT2"):
                m.loads[sid].append({"type": t, "g": c.node, "loc": loc})
            elif t == "SPCD":
                g = _ids(getattr(c, "nodes", []))
                m.loads[sid].append({"type": t, "g": g[0] if g else None, "loc": loc})
            else:
                m.loads[sid].append({"type": t, "g": None, "loc": loc})
    for sid, cards in bdf.load_combinations.items():
        for c in cards:
            if c.type == "LOAD":
                m.load_combo[sid] = (c.scale, list(zip(c.scale_factors, c.load_ids)), first.get(("LOAD", sid), "?"))
    m.props = dict(bdf.properties)
    for pid, p in m.props.items():
        if p.type not in PROP_CARDS:
            m.unknown[p.type] += 1
    m.mats = {**bdf.materials, **bdf.hyperelastic_materials}
    for name, p in bdf.params.items():
        v = p.values[0] if getattr(p, "values", None) else ""
        m.params[name.upper()] = str(v).upper()
    m.suport = [x for x in (bdf.suport or [])] + list((bdf.suport1 or {}).values())
    for c in ld.contact:
        m.contact[c.name].append(c)
    return m


# ----------------------------------------------------------------------------
# geometry / mass
# ----------------------------------------------------------------------------
def elem_measure(m, name, nodes):
    """(kind, measure): shell area, solid volume, line length; None if unknown."""
    try:
        if name in SHELLS:
            k = 4 if name.startswith("CQUAD") or name == "CSHEAR" else 3
            p = [m.pos(g) for g in nodes[:k]]
            if None in p or len(p) < k:
                return None
            if k == 4:
                return ("area", 0.5 * norm(cross(sub(p[2], p[0]), sub(p[3], p[1]))))
            return ("area", 0.5 * norm(cross(sub(p[1], p[0]), sub(p[2], p[0]))))
        if name in SOLIDS:
            k = CORNERS[name]
            p = [m.pos(g) for g in nodes[:k]]
            if None in p or len(p) < k:
                return None
            v = 0.0
            for face in FACES[name]:
                a = p[face[0]]
                for j in range(1, len(face) - 1):
                    v += dot(a, cross(p[face[j]], p[face[j + 1]]))
            return ("volume", abs(v) / 6.0)
        if name in LINES:
            p = [m.pos(g) for g in nodes[:2]]
            if None in p or len(p) < 2:
                return None
            return ("length", norm(sub(p[1], p[0])))
    except Exception:  # noqa: BLE001
        return None
    return None


def rho_of(m, mid):
    c = m.mats.get(mid)
    if c is None:
        return None
    return getattr(c, "rho", None)


def young_of(c):
    return getattr(c, "e", None) if c.type == "MAT1" else (getattr(c, "e11", None) if c.type == "MAT8" else None)


def mids_of(p):
    """Material IDs a property references (raw plies, not SYM-doubled)."""
    t = p.type
    if t == "PSHELL":
        return [p.mid1, p.mid2, p.mid3, p.mid4]
    if t in ("PCOMP", "PCOMPG"):
        return list(p.mids)
    if t in ("PSOLID", "PBAR", "PBARL", "PBEAM", "PBEAML", "PROD", "PTUBE", "PSHEAR", "PLSOLID"):
        return [p.mid]
    return []


def prop_mass_per_measure(m, pid, cache):
    """mass per unit area (shell) / volume (solid) / length (line); None if unknown."""
    if pid in cache:
        return cache[pid]
    p = m.props.get(pid)
    out = None
    try:
        if p is None:
            out = None
        elif p.type == "PSHELL":
            out = (rho_of(m, p.mid1) or 0.0) * (p.t or 0.0) + (p.nsm or 0.0)
        elif p.type in ("PCOMP", "PCOMPG"):
            tot = sum((rho_of(m, mid) or 0.0) * (t or 0.0) for mid, t in zip(p.mids, p.thicknesses))
            sym = p.type == "PCOMP" and (p.lam or "").upper() == "SYM"
            out = tot * (2 if sym else 1) + (p.nsm or 0.0)
        elif p.type in ("PSOLID", "PLSOLID"):
            out = rho_of(m, p.mid) or 0.0
        elif p.type == "PROD":
            out = (rho_of(m, p.mid) or 0.0) * (p.A or 0.0) + (p.nsm or 0.0)
        elif p.type == "PBAR":
            out = (rho_of(m, p.mid) or 0.0) * (p.A or 0.0) + (p.nsm or 0.0)
        elif p.type == "PBEAM":
            out = (rho_of(m, p.mid) or 0.0) * (p.A[0] or 0.0)
        elif p.type in ("PBARL", "PBEAML"):
            nsm = p.nsm if p.type == "PBARL" else 0.0
            out = (rho_of(m, p.mid) or 0.0) * p.Area() + (nsm or 0.0)
    except Exception:  # noqa: BLE001 - section pyNastran cannot size
        out = None
    cache[pid] = out
    return out


# ----------------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------------
class Findings:
    def __init__(self):
        self.items = []

    def add(self, code, severity, title, detail="", ids=(), locs=(), count=None, **extra):
        ref, apex = ROUTES.get(code, ([], None))
        ids = list(ids)
        d = {"code": code, "severity": severity, "title": title, "detail": detail,
             "count": count if count is not None else len(ids), "ids": ids[:12],
             "locs": list(locs)[:5], "basis": "computed",
             "route": {"nastran-reference": ref, "apex-docs": apex}}
        d.update(extra)
        self.items.append(d)

    def sorted(self):
        return sorted(self.items, key=lambda d: (SEV_ORDER[d["severity"]], d["code"]))


def active_sets(m, cc):
    """Resolve case control -> active LOAD/SPC/MPC/BCONTACT ids per subcase."""
    subs = cc["subcases"] or ({1: {}} if cc["global"] else {})
    out = {}
    for sid, s in subs.items():
        eff = dict(cc["global"])
        eff.update(s)
        out[sid] = {k: eff.get(k) for k in ("LOAD", "SPC", "MPC", "BCONTACT", "METHOD", "TEMPERATURE(LOAD)")}
    return out


def expand_add(table, sid, seen=None):
    seen = seen or set()
    if sid in seen:
        return set()
    seen.add(sid)
    if sid in table:
        out = set()
        for s in table[sid]:
            out |= expand_add(table, s, seen) or {s}
        return out
    return {sid}


def expand_load(m, sid, scale=1.0, depth=0):
    """-> [(scale, load_dict)]"""
    if depth > 10:
        return []
    if sid in m.load_combo:
        s0, pairs, _ = m.load_combo[sid]
        out = []
        for s, lid in pairs:
            out += expand_load(m, lid, scale * s0 * s, depth + 1)
        return out
    return [(scale, d) for d in m.loads.get(sid, [])]


def run_checks(m, cc_lines, sol=None, unit_hint=None, coincident=True, log=print):
    F = Findings()
    S = {}  # summary
    t0 = time.time()
    cc = parse_case_control(cc_lines) if cc_lines else {"global": {}, "subcases": {}, "params": []}
    have_cc = bool(cc_lines)
    sol = sol or m.sol
    S["sol"] = sol
    S["cards"] = dict(m.card_count.most_common())
    S["grids"], S["elements"] = len(m.grids), len(m.elems)
    S["rigid_elements"], S["masses"] = len(m.rigids), len(m.masses)
    for cc_param in cc.get("params", []):
        p = [x.strip() for x in re.split(r"[,\s]+", cc_param) if x.strip()]
        if len(p) >= 3:
            m.params.setdefault(p[1], p[2])
    S["params"] = m.params

    # ---------------- parse problems
    probs = list(m.problems)
    rejected = m.ld.rejected if m.ld else {}
    if rejected:
        probs.append(("-", "card types pyNastran has no class for and card_specs does not name: %s"
                      % ", ".join("%s (%d)" % kv for kv in rejected.most_common(8))))
    inc_missing = [p for p in probs if "INCLUDE not found" in p[1]]
    other = [p for p in probs if p not in inc_missing]
    if inc_missing:
        F.add("INCLUDE_MISSING", "error", "INCLUDE file(s) not found - the deck read here is incomplete",
              "; ".join(p[1] for p in inc_missing[:5]), locs=[p[0] for p in inc_missing], count=len(inc_missing))
    if other:
        F.add("PARSE_PROBLEM", "warn", "Lines or cards that could not be interpreted",
              "; ".join("%s %s" % p for p in other[:5]), locs=[p[0] for p in other], count=len(other))
    if m.unknown:
        S["cards_not_checked"] = dict(m.unknown.most_common(20))

    # ---------------- duplicates
    for fam, lst in m.dups.items():
        F.add("DUPLICATE_ID", "error", "Duplicate %s IDs" % fam.lower(),
              "IDs defined more than once (first and repeat location): " +
              "; ".join("%s at %s and %s" % x for x in lst[:4]),
              ids=[x[0] for x in lst], locs=[x[2] for x in lst], count=len(lst), family=fam)

    # ---------------- reference integrity
    grids = m.grids
    miss_g = collections.defaultdict(list)
    for eid, (n, pid, nodes, loc, _) in m.elems.items():
        for g in nodes:
            if g not in grids:
                miss_g[g].append(("element", eid, loc))
    for eid, (n, ind, dep, _, loc) in m.rigids.items():
        for g in ind + dep:
            if g not in grids:
                miss_g[g].append(("rigid", eid, loc))
    for eid, (n, g, mass, loc) in m.masses.items():
        if g not in grids:
            miss_g[g].append(("mass", eid, loc))
    for sid, lst in m.spcs.items():
        for n, comps, gl, loc in lst:
            for g in gl:
                if g not in grids:
                    miss_g[g].append(("spc", sid, loc))
    for sid, lst in m.loads.items():
        for d in lst:
            if d.get("g") and d["g"] not in grids:
                miss_g[d["g"]].append(("load", sid, d["loc"]))
    if miss_g:
        F.add("MISSING_GRID", "error", "References to grids that do not exist",
              "; ".join("GRID %s used by %s %s" % (g, v[0][0], v[0][1]) for g, v in list(miss_g.items())[:5]),
              ids=list(miss_g), locs=[v[0][2] for v in miss_g.values()], count=len(miss_g))
    miss_p, mismatch = collections.defaultdict(list), collections.defaultdict(list)
    for eid, (n, pid, nodes, loc, _) in m.elems.items():
        if pid is None or n == "CONROD":
            continue
        pc = m.props.get(pid)
        if pc is None:
            miss_p[pid].append((eid, loc))
        else:
            fam = ELEM_FAMILY.get(n)
            if fam and pc.type in PROP_CARDS and pc.type not in PROP_OK[fam]:
                mismatch[(n, pc.type)].append((eid, loc))
    if miss_p:
        F.add("MISSING_PROPERTY", "error", "Elements reference properties that do not exist",
              "; ".join("PID %s (%d elements, e.g. %s)" % (p, len(v), v[0][0]) for p, v in list(miss_p.items())[:5]),
              ids=list(miss_p), locs=[v[0][1] for v in miss_p.values()], count=sum(len(v) for v in miss_p.values()))
    for (en, pn), v in mismatch.items():
        F.add("PROPERTY_TYPE_MISMATCH", "error", "%s elements reference a %s" % (en, pn),
              ids=[x[0] for x in v], locs=[x[1] for x in v], count=len(v))
    used_mids = collections.defaultdict(list)
    for pid, c in m.props.items():
        for mid in mids_of(c):
            if mid:
                used_mids[mid].append((pid, m.loc("PROPERTY", pid)))
    for eid, e in m.elems.items():
        if e[0] == "CONROD" and e[4] and e[4][0]:
            used_mids[e[4][0]].append((eid, e[3]))
    miss_m = {mid: v for mid, v in used_mids.items() if mid not in m.mats}
    if miss_m:
        F.add("MISSING_MATERIAL", "error", "Properties reference materials that do not exist",
              "; ".join("MID %s used by PID %s" % (mid, v[0][0]) for mid, v in list(miss_m.items())[:5]),
              ids=list(miss_m), locs=[v[0][1] for v in miss_m.values()])
    used_pids = {e[1] for e in m.elems.values()}
    unused_p = sorted(p for p in m.props if p not in used_pids)
    unused_m = sorted(x for x in m.mats if x not in used_mids)
    if unused_p or unused_m:
        F.add("UNUSED_PROPERTY", "info", "Unreferenced properties/materials (harmless, often leftovers)",
              "properties: %s; materials: %s" % (unused_p[:10], unused_m[:10]),
              ids=unused_p + unused_m, count=len(unused_p) + len(unused_m))

    # ---------------- case control sets
    subs = active_sets(m, cc)
    S["subcases"] = subs
    active_spc, active_mpc, active_load, bcontact = set(), set(), set(), set()
    missing_sets = []
    for sid, s in subs.items():
        for key, table, target, have in (("SPC", m.spcadd, active_spc, m.spcs),
                                         ("MPC", m.mpcadd, active_mpc, m.mpcs)):
            v = to_int(s.get(key) or "")
            if v is not None:
                ex = expand_add(table, v)
                target |= ex
                for x in ex:
                    if x not in have:
                        missing_sets.append("%s=%s (subcase %s): set %s not defined" % (key, v, sid, x))
        v = to_int(s.get("LOAD") or "")
        if v is not None:
            active_load.add(v)
            if v not in m.loads and v not in m.load_combo:
                missing_sets.append("LOAD=%s (subcase %s) not defined" % (v, sid))
            for _, lid in (m.load_combo.get(v, (0, [], 0))[1]):
                if lid not in m.loads and lid not in m.load_combo:
                    missing_sets.append("LOAD %s refers to load set %s, which is not defined" % (v, lid))
        if s.get("BCONTACT"):
            bcontact.add(s["BCONTACT"])
    if missing_sets:
        F.add("MISSING_SET", "error", "Case control or LOAD combination points to undefined sets",
              "; ".join(missing_sets[:6]), count=len(missing_sets))
    if not have_cc:
        active_spc, active_mpc = set(m.spcs), set(m.mpcs)
        active_load = set(m.loads) | set(m.load_combo)
        bcontact = {"(all)"} if m.contact.get("BCONECT") else set()
        F.add("NO_CASE_CONTROL", "info", "No case control available - every SPC/MPC/load/contact set treated as active")
    S["active"] = {"SPC": sorted(active_spc), "MPC": sorted(active_mpc), "LOAD": sorted(active_load),
                   "BCONTACT": sorted(bcontact)}

    # ---------------- attachment maps
    stiff_grids = set()           # grids with stiffness attachment
    for e in m.elems.values():
        stiff_grids.update(e[2])
    for r in m.rigids.values():
        stiff_grids.update(r[1]); stiff_grids.update(r[2])
    for sid in active_mpc:
        for gl, _ in m.mpcs.get(sid, []):
            stiff_grids.update(gl)
    spc_grids = {}
    for sid in active_spc:
        for n, comps, gl, loc in m.spcs.get(sid, []):
            for g in gl:
                spc_grids[g] = spc_grids.get(g, "") + (comps or "")
    for g, v in grids.items():
        ps = (v[5] or "").strip()
        if ps and ps != "0":
            spc_grids[g] = spc_grids.get(g, "") + ps
    mass_grids = {v[1] for v in m.masses.values()}
    load_grids = set()
    for lid in active_load:
        for s, d in expand_load(m, lid):
            if d.get("g"):
                load_grids.add(d["g"])
    coord_grids = {g for c in m.coords.values() if c.type.startswith("CORD1") for g in (c.g1, c.g2, c.g3) if g}

    # ---------------- orphans, floating masses, unattached spc/load
    referenced = stiff_grids | mass_grids | set(spc_grids) | load_grids | coord_grids
    orphans = sorted(g for g in grids if g not in referenced)
    if orphans:
        F.add("ORPHAN_GRID", "info", "Grids not used by any element, rigid element, mass, constraint or load",
              ids=orphans, locs=[grids[g][6] for g in orphans[:5]], count=len(orphans))
    floating = [(eid, v) for eid, v in m.masses.items() if v[1] not in stiff_grids]
    if floating:
        tot = sum(v[2] for _, v in floating)
        F.add("FLOATING_MASS", "warn", "Lumped masses on grids with no element or rigid connection",
              "%d masses, total %.4g mass units. In statics AUTOSPC removes these DOFs silently; "
              "under GRAV/ACCEL or in a modal run the mass is lost or gives zero-frequency modes. "
              "Masses: %s" % (len(floating), tot, "; ".join("%s %s on GRID %s (%.4g)" % (v[0], e, v[1], v[2])
                                                            for e, v in floating[:6])),
              ids=[e for e, _ in floating], locs=[v[3] for _, v in floating])
    un_spc = sorted(g for g in spc_grids if g not in stiff_grids and g not in mass_grids and g in grids)
    if un_spc:
        F.add("SPC_ON_UNATTACHED", "warn", "Constraints on grids with no element attached (they constrain nothing)",
              ids=un_spc, count=len(un_spc))
    un_load = sorted(g for g in load_grids if g not in stiff_grids and g in grids)
    if un_load:
        F.add("LOAD_ON_UNATTACHED", "error", "Loads on grids with no stiffness attachment - the load goes nowhere",
              ids=un_load, count=len(un_load))

    # ---------------- rigid-element dependency conflicts
    dep_owner = collections.defaultdict(list)
    for eid, (n, ind, dep, depc, loc) in m.rigids.items():
        for g in dep:
            dep_owner[g].append((eid, n, depc.get(g, ""), loc))
    doubles, spc_dep = [], []
    for g, owners in dep_owner.items():
        if len(owners) > 1:
            seen = set()
            for eid, n, comps, loc in owners:
                cs = set(comps or "123456")
                if seen & cs:
                    doubles.append((g, [o[0] for o in owners], loc))
                    break
                seen |= cs
        if g in spc_grids:
            cs = set().union(*[set(o[2] or "123456") for o in owners])
            if cs & set(spc_grids[g]):
                spc_dep.append((g, owners[0][0], owners[0][3]))
    if doubles:
        F.add("DOUBLE_DEPENDENT", "error", "Grids dependent in more than one rigid element (same DOFs)",
              "; ".join("GRID %s in %s" % (g, e) for g, e, _ in doubles[:5]),
              ids=[d[0] for d in doubles], locs=[d[2] for d in doubles])
    if spc_dep:
        F.add("SPC_ON_DEPENDENT", "error", "SPC applied to dependent DOFs of rigid elements",
              "; ".join("GRID %s (dependent in %s)" % (g, e) for g, e, _ in spc_dep[:5]),
              ids=[d[0] for d in spc_dep], locs=[d[2] for d in spc_dep])
    log("  checks: references and attachment done (%.1fs)" % (time.time() - t0))

    # ---------------- connectivity components (elements + rigid + active MPC)
    uf = UF()
    for e in m.elems.values():
        nd = e[2]
        if nd:
            r0 = uf.find(nd[0])
            for g in nd[1:]:
                uf.union(r0, g)
    for r in m.rigids.values():
        nd = r[1] + r[2]
        for g in nd[1:]:
            uf.union(nd[0], g)
    for sid in active_mpc:
        for gl, _ in m.mpcs.get(sid, []):
            for g in gl[1:]:
                uf.union(gl[0], g)
    for g in mass_grids | set(spc_grids) | load_grids:
        uf.find(g)
    comp_of = {g: uf.find(g) for g in uf.p}
    comp_nodes = collections.Counter(comp_of.values())
    comp_elems = collections.Counter()
    comp_pids = collections.defaultdict(collections.Counter)
    elem_comp = {}
    for eid, e in m.elems.items():
        if e[2]:
            c = comp_of[e[2][0]]
            elem_comp[eid] = c
            comp_elems[c] += 1
            comp_pids[c][e[1]] += 1
    comp_spc = collections.Counter(comp_of[g] for g in spc_grids if g in comp_of)
    comp_load = collections.Counter(comp_of[g] for g in load_grids if g in comp_of)
    comp_mass = collections.defaultdict(float)
    for v in m.masses.values():
        if v[1] in comp_of:
            comp_mass[comp_of[v[1]]] += v[2]
    # label components 1..n by size; single-grid comps with no element are orphans/floating masses
    order = [c for c, _ in comp_nodes.most_common()]
    label = {c: i + 1 for i, c in enumerate(order)}
    real = [c for c in order if comp_elems[c] > 0 or any(
        comp_of.get(g) == c for r in m.rigids.values() for g in r[1][:1])]
    log("  checks: %d connected components (%.1fs)" % (len(real), time.time() - t0))

    # ---------------- element sizes & mass (needed for glue + mass summary)
    pm_cache = {}
    elem_size = {}
    mass_by = collections.Counter()
    mass_unknown = collections.Counter()
    comp_emass = collections.defaultdict(float)
    xyz_min, xyz_max = [math.inf] * 3, [-math.inf] * 3
    for eid, (n, pid, nodes, loc, extra) in m.elems.items():
        meas = elem_measure(m, n, nodes)
        if meas is None:
            continue
        kind, val = meas
        elem_size[eid] = math.sqrt(val) if kind == "area" else (val ** (1 / 3) if kind == "volume" else val)
        if n == "CONROD" and extra:
            per = (rho_of(m, extra[0]) or 0.0) * extra[1]
        else:
            per = prop_mass_per_measure(m, pid, pm_cache)
        if per is None:
            mass_unknown[n] += 1
            continue
        em = per * val
        mass_by[n] += em
        comp_emass[elem_comp.get(eid)] += em
    for g in list(grids)[:: max(1, len(grids) // 200000)]:
        p = m.pos(g)
        if p:
            for k in range(3):
                xyz_min[k] = min(xyz_min[k], p[k]); xyz_max[k] = max(xyz_max[k], p[k])
    conm = sum(v[2] for v in m.masses.values())
    wtmass = to_float(m.params.get("WTMASS", ""), 1.0) or 1.0
    total_mass = (sum(mass_by.values()) + conm)
    S["mass"] = {"total_estimate": total_mass, "elements": dict(mass_by), "lumped": conm,
                 "not_estimated": dict(mass_unknown), "wtmass": wtmass,
                 "note": "estimate from element geometry and property density; element thickness overrides "
                         "and offsets ignored. Grid point weight output (PARAM,GRDPNT) is authoritative."}
    S["bbox"] = [xyz_min, xyz_max] if xyz_min[0] < math.inf else None
    if wtmass != 1.0:
        F.add("WTMASS", "info", "PARAM,WTMASS = %g scales all structural mass" % wtmass,
              "the mass estimate above is before WTMASS; check it matches the unit system")
    log("  checks: geometry and mass estimate (%.1fs)" % (time.time() - t0))

    # ---------------- contact / glue graph
    glue = analyse_contact(m, F, comp_of, elem_size, label, bcontact, have_cc)
    S["contact"] = glue["summary"]

    # super-groups: components + active contact links
    uf2 = UF()
    for c in real:
        uf2.find(c)
    for p in glue["pairs"]:
        for a in p["sec_comps"]:
            for b in p["main_comps"]:
                uf2.union(a, b)
    groups = collections.defaultdict(list)
    for c in real:
        groups[uf2.find(c)].append(c)
    inrel = m.params.get("INREL", "0") not in ("0", "")
    static = (sol or "").upper() in ("101", "SESTATIC", "1", "400", "106", "NLSTATIC", "SOL101", "")
    comp_table = []
    for c in real:
        comp_table.append({"component": label[c], "grids": comp_nodes[c], "elements": comp_elems[c],
                           "props": dict(comp_pids[c].most_common(4)), "spc_grids": comp_spc[c],
                           "loaded_grids": comp_load[c], "lumped_mass": round(comp_mass[c], 6),
                           "element_mass": round(comp_emass.get(c, 0.0), 6), "group": label[uf2.find(c)]})
    S["components"] = comp_table[:40]
    S["components_total"] = len(real)
    S["groups_total"] = len(groups)
    unconstrained = [(root, cs) for root, cs in groups.items() if not any(comp_spc[c] for c in cs)]
    if unconstrained and static and not inrel and not m.suport:
        for root, cs in unconstrained:
            loaded = any(comp_load[c] for c in cs)
            F.add("UNCONSTRAINED_GROUP", "error",
                  "A part (or glued assembly of parts) has no path to any SPC%s" % (" and carries load" if loaded else ""),
                  "components %s: %d grids, %d elements, props %s. In a static run this is a mechanism "
                  "(singularity / rigid-body motion) unless something outside the deck constrains it."
                  % ([label[c] for c in cs], sum(comp_nodes[c] for c in cs), sum(comp_elems[c] for c in cs),
                     dict(sum((comp_pids[c] for c in cs), collections.Counter()).most_common(4))),
                  ids=[label[c] for c in cs], count=len(cs))
    # load path: loaded comps that reach SPC only through contact
    comp_graph = collections.defaultdict(list)
    for p in glue["pairs"]:
        for a in p["sec_comps"]:
            for b in p["main_comps"]:
                if a != b:
                    comp_graph[a].append((b, p["id"]))
                    comp_graph[b].append((a, p["id"]))
    for c in real:
        if comp_load[c] and not comp_spc[c] and comp_graph.get(c):
            # BFS to nearest constrained component
            prev, q, hit = {c: None}, [c], None
            while q and hit is None:
                nq = []
                for x in q:
                    for y, pid in comp_graph[x]:
                        if y not in prev:
                            prev[y] = (x, pid)
                            if comp_spc[y]:
                                hit = y
                                break
                            nq.append(y)
                    if hit:
                        break
                q = nq
            if hit is None:
                continue
            path, y = [], hit
            while prev[y]:
                x, pid = prev[y]
                path.append(pid)
                y = x
            involved = sorted({p["id"] for p in glue["pairs"] if c in p["sec_comps"] + p["main_comps"]
                               or any(x in p["sec_comps"] + p["main_comps"] for x in groups[uf2.find(c)])})
            F.add("GLUE_DEPENDENT_LOAD_PATH", "warn",
                  "The loaded part reaches its constraints only through contact/glue",
                  "component %d (loaded, no SPC) -> constrained component %d via contact pair(s) %s. "
                  "Without those pairs the loaded part would be unconstrained. All pairs in this assembly: %s. "
                  "Result quality at the glued interfaces governs the whole load path."
                  % (label[c], label[hit], list(reversed(path)), involved),
                  ids=list(reversed(path)), count=len(involved))
    log("  checks: contact and load path (%.1fs)" % (time.time() - t0))

    # ---------------- loads
    unit = detect_units(m, unit_hint)
    S["units"] = unit
    load_sum = {}
    point_only = True
    for lid in sorted(active_load, key=str):
        fx = [0.0, 0.0, 0.0]; mx = [0.0, 0.0, 0.0]
        kinds = collections.Counter()
        grav = []
        for s, d in expand_load(m, lid):
            kinds[d["type"]] += 1
            if d["type"] in ("FORCE", "MOMENT"):
                at = m.pos(d["g"])
                v = m.vec_to_basic(d["cid"], d["n"], at)
                if v is None or at is None:
                    continue
                v = mul(v, d["f"] * s)
                if d["type"] == "FORCE":
                    fx = [fx[k] + v[k] for k in range(3)]
                    mom = cross(at, v)
                    mx = [mx[k] + mom[k] for k in range(3)]
                else:
                    mx = [mx[k] + v[k] for k in range(3)]
            elif d["type"] == "GRAV":
                point_only = False
                gv = m.vec_to_basic(d["cid"], d["n"], None)
                grav.append([round(x * d["a"] * s, 6) for x in (gv or (0, 0, 0))])
            elif d["type"] not in ("FORCE", "MOMENT"):
                point_only = False
        load_sum[lid] = {"cards": dict(kinds), "force_resultant_basic": [round(x, 6) for x in fx],
                         "moment_about_origin": [round(x, 6) for x in mx], "grav": grav,
                         "point_grids": sorted({d.get("g") for _, d in expand_load(m, lid) if d.get("g")})[:10]}
    S["loads"] = load_sum
    if load_sum and point_only and total_mass > 0:
        ftot = max(norm(v["force_resultant_basic"]) for v in load_sum.values())
        g = unit.get("g") if unit else None
        eq = ("equivalent to %.3g g on the estimated model mass (%.4g)" % (ftot / (total_mass * wtmass * g), total_mass)
              if g else "unit system unknown, so the g-level is not computed")
        F.add("POINT_LOAD_ONLY", "info", "Loading is point forces only - no GRAV/ACCEL, so structural inertia is not loaded",
              "largest resultant %.4g force units, %s. Fine if the forces represent the complete loading; "
              "for an inertial (launch, shock, manoeuvre) case the rest of the mass carries no load."
              % (ftot, eq))

    # ---------------- materials / units
    mats = []
    for mid, c in m.mats.items():
        e = young_of(c)
        rho = rho_of(m, mid)
        cw = math.sqrt(e / rho) if e and rho else None
        mats.append({"mid": mid, "card": c.type, "E": e, "rho": rho, "wave_speed": cw, "loc": m.loc("MATERIAL", mid)})
    S["materials"] = mats
    ws = [x["wave_speed"] for x in mats if x["wave_speed"] and x["card"] == "MAT1"]
    if len(ws) >= 2 and max(ws) / min(ws) > 10:
        F.add("MIXED_UNITS", "warn", "Isotropic materials differ >10x in sqrt(E/rho) - possible mixed unit systems",
              "; ".join("MID %s E=%g rho=%g" % (x["mid"], x["E"], x["rho"]) for x in mats if x["wave_speed"]))
    zero = [x["mid"] for x in mats if (x["rho"] or 0) == 0 and x["mid"] in used_mids]
    if zero:
        F.add("ZERO_DENSITY", "info" if static else "warn", "Materials in use with zero density", ids=zero)

    # ---------------- output requests worth having
    gaps = []
    ccu = " ".join(t.upper() for t, *_ in ([(x,) if isinstance(x, str) else x for x in cc_lines]))
    if have_cc and "SPCFORCE" not in ccu:
        gaps.append("no SPCFORCE request - reactions cannot be balanced against the applied load")
    if "GRDPNT" not in m.params and "GRDPNT" not in ccu:
        gaps.append("no PARAM,GRDPNT - the f06 has no grid point weight (mass) table")
    if gaps:
        F.add("OUTPUT_GAP", "info", "Output that would make this run checkable", "; ".join(gaps))

    # ---------------- coincident nodes across components
    if coincident and S["bbox"]:
        coincident_nodes(m, F, comp_of, label, glue, S)
    log("  checks: done (%.1fs)" % (time.time() - t0))
    return F, S, {"comp_of": comp_of, "label": label, "elem_comp": elem_comp}


def detect_units(m, hint=None):
    txt = " ".join(m.comments).upper() + " " + (hint or "").upper()
    L = re.search(r"LENGTH\s+(\w+)", txt)
    T = re.search(r"TIME\s+(\w+)", txt)
    M = re.search(r"MASS\s+(\w+)", txt)
    Fo = re.search(r"FORCE\s+(\w+)", txt)
    sysname = re.search(r"UNIT\s+SYSTEM\s*[:=]?\s*(\S+)|(SI_\w+)", txt)
    if not (L and T):
        return {"system": sysname.group(0) if sysname else None, "g": None}
    lf, tf = UNIT_LEN.get(L.group(1)), UNIT_TIME.get(T.group(1))
    if not lf or not tf:
        return {"system": None, "g": None}
    return {"length": L.group(1), "time": T.group(1), "mass": M.group(1) if M else None,
            "force": Fo.group(1) if Fo else None, "g": 9.80665 * lf / tf ** 2,
            "system": sysname.group(0) if sysname else None, "source": "deck header comments"}



def analyse_contact(m, F, comp_of, elem_size, label, bcontact, have_cc):
    """Trace BCONECT pairs to elements and parts.

    Surfaces: BCSURF (FACE/GRID forms; SET3 lists resolved), BCBODY/BCBODY1 to
    BSURF or BCPROP. Rejected cards are named by card_specs (QRG layouts);
    BSURF, BCBODY and SET3 come from pyNastran's own objects."""
    ctab = m.contact
    out = {"pairs": [], "summary": {}}
    if not ctab:
        return out
    bdf = m.bdf
    sets = getattr(bdf, "sets", {}) or {}
    surf = {}
    for c in ctab.get("BCSURF", []):
        eids = []
        for it in c.get("ITEMS", []):
            esid = it.get("ESID", it.get("EID"))
            if it.get("IDTYPE") == "SET" and esid in sets:
                eids += list(getattr(sets[esid], "ids", []))
            elif isinstance(esid, int):
                eids.append(esid)
        surf[c.get("BID")] = (eids, c.loc, c.get("FORM") == "RIGID")
    bsurf = {sid: (list(s.eids), m.ld.first_locs.get(("BSURF", sid), "?"))
             for sid, s in (getattr(bdf, "bsurf", {}) or {}).items()}
    bcprop = {c.get("ID"): (c.get("IPS", []), c.loc) for c in ctab.get("BCPROP", [])}
    body = {}
    for c in ctab.get("BCBODY1", []):
        body[c.get("BID")] = (c.get("BSID"), c.loc)
    for bid, b in (getattr(bdf, "bcbodys", {}) or {}).items():
        body[bid] = (b.bsid, m.ld.first_locs.get(("BCBODY", bid), "?"))
    pid_elems = None

    def resolve(i):
        nonlocal pid_elems
        if i in surf:
            return surf[i][0], "BCSURF %s%s" % (i, " (rigid)" if surf[i][2] else "")
        if i in body:
            bsid = body[i][0]
            if bsid in bsurf:
                return bsurf[bsid][0], "BCBODY %s -> BSURF %s" % (i, bsid)
            if bsid in bcprop:
                if pid_elems is None:
                    pid_elems = collections.defaultdict(list)
                    for eid, e in m.elems.items():
                        pid_elems[e[1]].append(eid)
                pids = bcprop[bsid][0]
                return [e for p in pids for e in pid_elems.get(p, [])], "BCBODY %s -> BCPROP %s" % (i, bsid)
        return None, None

    # which BCONECTs are active: BCONTACT selects a BCTABL1, or a BCONECT directly (BCTABL1 remark 1)
    tables = {c.get("BCID"): set(c.get("IDS", [])) for c in ctab.get("BCTABL1", [])}
    conect_ids = {c.get("ID") for c in ctab.get("BCONECT", [])}
    active = None
    note = []
    if have_cc:
        ids = set()
        for b in bcontact:
            bi = to_int(b)
            if bi is not None and bi in tables:
                ids |= tables[bi]
            elif bi is not None and bi in conect_ids:
                ids.add(bi)
            else:
                note.append("BCONTACT=%s selects no BCTABL1 or BCONECT - all BCONECT assumed active" % b)
                ids = None
                break
        active = ids if bcontact else set()
    iglue = {c.get("BCGPID"): c.get("PARAMS", {}).get("IGLUE") for c in ctab.get("BCONPRG", [])}
    used_surf = set()
    pairs = []

    def collect(ids):
        es, desc = [], []
        for x in ids:
            e, d = resolve(x)
            if e is None:
                return None, None
            es += e
            desc.append(d)
        return es, desc

    def comps(es):
        return sorted({label[comp_of[m.elems[e][2][0]]] for e in es if e in m.elems and m.elems[e][2]})

    def size(es):
        v = [elem_size[e] for e in es if e in elem_size]
        return sum(v) / len(v) if v else None

    for c in ctab.get("BCONECT", []):
        cid = c.get("ID")
        if active is not None and cid not in active:
            continue
        secs = [c.get("IDSCND")] if isinstance(c.get("IDSCND"), int) else list(c.get("IDSEC", []))
        mains = [c.get("IDPRIM")] if isinstance(c.get("IDPRIM"), int) else list(c.get("IDPRIM_LIST", []))
        used_surf.update(secs)
        used_surf.update(mains)
        sec_e, sec_desc = collect(secs)
        main_e, main_desc = collect(mains)
        if not secs or not mains or sec_e is None or main_e is None:
            F.add("GLUE_UNRESOLVED", "warn", "Contact pair %s: a surface could not be resolved to elements" % cid,
                  "secondary %s, main %s" % (secs, mains), ids=[cid], locs=[c.loc])
            continue
        sec_desc = ", ".join(sec_desc)
        p = {"id": cid, "secondary": sec_desc, "main": main_desc, "sec_elems": len(sec_e), "main_elems": len(main_e),
             "sec_size": size(sec_e), "main_size": size(main_e), "iglue": iglue.get(c.get("BCGPID")),
             "sec_comps": [], "main_comps": [], "loc": c.loc}
        # comps as raw comp roots for graph use; labels for display
        p["sec_comps"] = sorted({comp_of[m.elems[e][2][0]] for e in sec_e if e in m.elems and m.elems[e][2]})
        p["main_comps"] = sorted({comp_of[m.elems[e][2][0]] for e in main_e if e in m.elems and m.elems[e][2]})
        p["sec_comp_labels"], p["main_comp_labels"] = comps(sec_e), comps(main_e)
        pairs.append(p)
        if p["sec_size"] and p["main_size"] and p["sec_size"] > 2.0 * p["main_size"]:
            F.add("GLUE_COARSE_SECONDARY", "warn",
                  "Contact pair %s: the secondary (tied) side is %.1fx coarser than the main side" %
                  (cid, p["sec_size"] / p["main_size"]),
                  "secondary %s: %d elements, mean size %.3g; main %s: %d elements, mean size %.3g. "
                  "Only secondary nodes are tied, so a coarse secondary leaves most main-side nodes free."
                  % (sec_desc, p["sec_elems"], p["sec_size"], ", ".join(main_desc), p["main_elems"], p["main_size"]),
                  ids=[cid], locs=[c.loc])
        if set(p["sec_comps"]) & set(p["main_comps"]):
            F.add("GLUE_SAME_COMPONENT", "info",
                  "Contact pair %s joins surfaces that are already mesh-connected" % cid, ids=[cid], locs=[c.loc])
    all_surf = set(surf) | set(body)
    unused = sorted(s for s in all_surf if s not in used_surf)
    if unused and ctab.get("BCONECT"):
        F.add("UNUSED_CONTACT_SURFACE", "info", "Contact surfaces/bodies not used by any active contact pair",
              ids=unused, count=len(unused))
    other = [n for n in ("BGSET", "BCTSET", "BCTABLE") if ctab.get(n)]
    if other:
        F.add("CONTACT_NOT_ANALYSED", "warn", "Contact defined with %s is not traced by these checks" % other,
              "the component/load-path conclusions below ignore those connections")
    out["pairs"] = pairs
    out["summary"] = {"pairs": [{k: v for k, v in p.items() if k not in ("sec_comps", "main_comps")} for p in pairs],
                      "notes": note,
                      "cards": {k: len(v) for k, v in ctab.items()}}
    return out


def coincident_nodes(m, F, comp_of, label, glue, S):
    lo, hi = S["bbox"]
    diag = math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3))) or 1.0
    tol = 1e-5 * diag
    ids = [g for g in m.grids if g in comp_of and m.pos(g) is not None]
    pairs = set()
    if ids:
        tree = cKDTree(np.array([m.pos(g) for g in ids], dtype=float))
        for a, b in tree.query_pairs(tol):
            pairs.add((ids[a], ids[b]))
    glued = set()
    for p in glue["pairs"]:
        for a in p["sec_comps"]:
            for b in p["main_comps"]:
                glued.add((a, b)); glued.add((b, a))
    across, at_glue = [], 0
    for a, b in pairs:
        ca, cb = comp_of[a], comp_of[b]
        if ca == cb:
            continue
        if (ca, cb) in glued:
            at_glue += 1
        else:
            across.append((a, b, label[ca], label[cb]))
    S["coincident"] = {"tolerance": tol, "pairs_total": len(pairs), "across_glued_components": at_glue,
                       "across_unconnected_components": len(across)}
    if across:
        F.add("COINCIDENT_UNMERGED", "warn",
              "Coincident grids in different, unconnected parts (tol %.3g) - missing node merge or connection?" % tol,
              "; ".join("GRID %s (comp %s) / GRID %s (comp %s)" % (a, ca, b, cb) for a, b, ca, cb in across[:6]),
              ids=[a for a, *_ in across], count=len(across))


# ----------------------------------------------------------------------------
def build_model(path, include_dirs=(), sink=None, log=print, workdir=None):
    """Read the deck with pyNastran and fill the compact model the checks use."""
    t = time.time()
    ld = load_deck(path, include_dirs, sink=sink, workdir=workdir)
    m = _fill(Model(), ld)
    log("  deck: %d cards read in %.1fs (pyNastran)" % (sum(m.card_count.values()), time.time() - t))
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bdf")
    ap.add_argument("-I", "--include-dir", action="append", default=[])
    ap.add_argument("--sol")
    ap.add_argument("--no-coincident", action="store_true")
    ap.add_argument("-o", "--out", default="deck_check_out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    m = build_model(a.bdf, a.include_dir)
    F, S, _ = run_checks(m, m.case_control, a.sol, coincident=not a.no_coincident)
    json.dump({"findings": F.sorted(), "summary": S}, open(os.path.join(a.out, "deck.json"), "w"),
              indent=1, default=str)
    for f in F.sorted():
        print("%-5s %-26s %s" % (f["severity"].upper(), f["code"], f["title"]))


if __name__ == "__main__":
    main()
