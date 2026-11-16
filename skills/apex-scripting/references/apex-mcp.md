# Working through the Apex MCP server

The [Apex MCP server](https://github.com/rehman-saif/apex-mcp) is a bridge to the
user's open Apex session. It carries no documentation: this skill is where the
API signatures and rules are. Everything in this skill applies to scripts sent
through it. Tool names below are those of server 2.0.

| To | Use |
|---|---|
| read the model (parts, connections, loads, constraints, catalog, scenarios) | `model_overview`, then `part_summary` and `list_faces` on the parts of interest |
| run a script that only reads | `query_apex_python`: refused if it would change anything |
| run a script that changes the model or the view | `run_apex_python`, after the user agrees |
| see what this Apex really has (a module's names, a signature, enum values, an entity's properties) | `apex_describe` |
| look at the model | `screenshot`; `restore=false` leaves the scene and view as set up |
| check an exported deck | `export_bdf`, then `nastran-diagnostics`: `python tools/deck_checks.py <path>` |

How the two divide the work:

1. Find the call here first: `api/functions-index.md`, `api/methods-index.md`,
   `api/enums.md`. This is where arguments are explained.
2. Where this skill and the running Apex may differ (a name in another module, an
   enum member the reference lacks), ask `apex_describe`. Apex's objects have no
   docstrings, so `apex_describe` gives names, signatures and values only.
3. The server does not check names or arguments before a script runs. Apex raises
   at the call, and the result names the failing line and the signature this Apex
   exposes for the failing call. Look the call up here before retrying, rather
   than guessing a new signature.
4. The result of `run_apex_python` ends with `effects=`: what the script created,
   deleted or changed in the model. Check it against what you meant to do.

Rules that matter more in a live session:

- Apex runs one call at a time and shares memory with the user's model. Never
  iterate `.elements` / `.nodes` (the tools refuse it); use the MeshBody arrays.
  Aggregate in the script and return counts or top-N, not raw lists.
- Variables persist between script calls.
- Use the `screenshot` tool, not `apex.display.captureImage`, and its scene or
  `part.hide()` / `part.show()`, not `apex.session.hideAll()` (see
  [runtime-2024.1.md](runtime-2024.1.md)).

## Helpers in the script namespace

Scripts get `apex` and two helper modules from the server. `apex_describe('$Q')`
and `apex_describe('$B')` list them; `apex_describe('$B.rbe2')` gives one
helper's arguments and documentation.

`Q` reads without walking elements: `Q.part_summary(part)`,
`Q.mesh_summary(mesh, sample=3)`, `Q.topology_counts(mesh)`,
`Q.sample_elements(mesh, n)`, `Q.solid_summary(solid)`, `Q.surface_summary(surf)`,
`Q.bbox(entity)`, `Q.faces_by_id(part, ids)`, `Q.face_shape(face)`,
`Q.nodes_on_face(faces)`, `Q.nodes_where(mesh_or_part, fn)` with `fn` taking the
N x 3 coordinate array and returning a mask, `Q.nodes_by_id(part, ids)`,
`Q.node_near(part, xyz, tol)`, `Q.rle(ids)`, and `Q.geometry_check(parts,
tolerance=0.5)`: geometry faults counted by type and small features, nothing
repaired.

`B` builds a linear static model, one tested step per call, the same steps as
section 12 of [patterns-and-recipes.md](patterns-and-recipes.md). Each is
idempotent: a repeat call with the same name replaces what the earlier one made.

```python
B.create_material(name="Ti64", E=113800.0, nu=0.342, rho=4.43e-9)
B.assign_solid_property(paths=["base/Bracket"], material="Ti64")
B.mesh_solid(paths=["base/Bracket"], size=3.0)                      # tets, replaces the old mesh
B.glue(name="G1", side1={"path": partA, "faces": [12]}, side2={"path": partB, "faces": [7]})
bolt = B.beam(name="Bolt1", points=[[0, 0, 10], [0, 0, 0]], radius=4.0,
              material="Ti64", mesh_size=2.0, part="base/Connections")
B.rbe2(ref={"path": "base/Connections", "node": bolt["nodes_at_points"][0]},
       attach={"path": partA, "faces": [31]})
B.constrain(name="Fix", target={"path": partB, "faces": [3]})          # type="Clamped"
B.nodal_load(name="LC1", target={"path": "base/Connections", "nodes": [n]}, force=[0, 0, 100])
B.static_scenario(name="SOL101", subcases=[{"name": "LC1", "load": "LC1", "constraint": "Fix"}])
```

A target is a pathName, `{"path": part, "faces": [ids]}` (ids from `list_faces`)
or `{"path": part, "nodes": [ids]}`, or a list of these. `B.static_scenario`
sets `BCONTACT` when the model has interactions; glue is ignored by Nastran
without it. `B.constrain(dof="123")` is not yet proven in Apex: check the SPC
cards of the exported deck.
