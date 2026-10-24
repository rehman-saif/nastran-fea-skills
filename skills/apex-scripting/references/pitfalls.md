# Apex pitfalls

Mistakes that produce plausible-looking Apex code that does not run, ordered by
how often they appear in generated scripts. Sections 17–22 cover the worse
case: code that runs, raises nothing, and leaves the model or the exported deck
wrong. Those were observed in Apex 2024.1 while building a SOL 101 assembly
model.

## 1. Positional arguments

The Apex API accepts **no positional arguments**. Every call needs name-value
pairs. This breaks more generated scripts than anything else.

```python
apex.mesh.createSurfaceMesh(target=bodies, meshSize=5.0)   # correct
apex.mesh.createSurfaceMesh(bodies, 5.0)                   # fails
```

Non-`Entity` value types are the exception, because they use normal Python
construction: `apex.ColorRGB(214, 255, 0)` is fine.

## 2. Assigning to a property instead of calling `update()`

`Entity`-derived classes have no setters. Assignment silently fails to change
the model rather than raising.

```python
my_mesh.update(meshSize=8.0)   # correct
my_mesh.meshSize = 8.0         # does nothing to the model
```

## 3. Invented enum members

Enum names read naturally, which makes them easy to guess and easy to get
wrong. `apex.geometry.CADFormat` has no `Parasolid` member — it has
`ParasolidText` and `ParasolidBinary`. Check `api/enums.md` every time.

The API also contains genuine misspellings that must be reproduced exactly:
`apex.mesh.FeatureMeshType.ArbirtaryHole`, `apex_sdk.PickFilterTypes.ExcludDof`.

## 4. Treating a Collection as a list

Passing a Python list where a collection is expected fails.

```python
bodies = apex.EntityCollection()
bodies.appendList([...])       # correct
bodies = [...]                 # not a collection
```

`len()` is a method on the collection, not the Python builtin:

```python
count = entity.nodes.len()     # correct
count = len(entity.nodes)      # not supported
```

Use `toList()` when you genuinely need list behaviour like `sorted()`.

## 5. Concluding a member does not exist because it is inherited

`api/classes/<module>.md` lists only the members declared on each class.
`apex.Part` shows no `name` property, yet `part.name` is valid — it comes from
`apex.IName`, one of the interfaces in that class's `(extends ...)` header.
Walk the base classes before deciding something is missing.

## 6. Expecting a tuple

Apex methods return exactly one value. Multiple heterogeneous results come back
as a `ZResult*` object whose properties hold the values.

```python
result = apex.mesh.createSurfaceMesh(...)   # ZResultCreateSurfaceMesh
meshes, ok = apex.mesh.createSurfaceMesh(...)   # fails
```

## 7. Reusing a model handle after `close()`

`Model.close()` returns a new empty model. The old handle is stale.

```python
model = model.close()   # correct
model.close()           # `model` is now stale
```

## 8. Importing `apex` in a tool's UI file

`*_ui.py` runs as IronPython in the UI process and must import only `apex_sdk`,
`clr` and `System.*`. `import apex` belongs in the worker script.

## 9. Doing model work in a click handler

Calling worker code directly — or importing the worker module and invoking its
function — stalls the Apex UI. Always go through `apex_sdk.runScript()` or
`apex_sdk.runScriptFunction()`.

## 10. Omitting `@apex_sdk.errorhandler`

An uncaught exception in an event handler terminates Apex. The decorator is
mandatory on every handler, not a nicety.

## 11. Forgetting that dictionary values are strings

`runScriptFunction` converts every key and value to a string. The worker must
cast:

```python
mesh_size = float(dictionary["MeshSize"])
include = dictionary["IncludeHidden"] == "True"
```

## 12. Skipping the unit system

Without `apex.setScriptUnitSystem(...)` the script runs in whatever units the
application currently has active, so the same script gives different geometry on
different machines. Set it explicitly.

## 13. Assuming `getParts()` is recursive

It is not. Nested assemblies need `getParts(recursive=True)`.

## 14. Documentation version skew

The API reference in `api/` is **Iberian Lynx FP2** (2024). The concept and
custom-tool documentation it was built alongside describes **Apex 2021.4**
with **Python 3.8.2**.

Treat `api/` as authoritative for what exists and what its signature is. Treat
the older material as authoritative for tool authoring structure and GUI SDK
behaviour, which have been stable. If the user names a specific Apex release,
say that the signature came from Iberian Lynx FP2 and may differ on theirs.

## 15. Third-party packages

Apex runs Python in its own process with its own interpreter and a modified
`PATH`/`PYTHONPATH`. Compiled packages must match Apex's Python version and its
VC++ 14.x runtime. Apex already ships numpy, scipy, pandas, h5py, tables,
matplotlib and vtk — prefer those. Any `sys.path` or `os.environ` manipulation
for an external distribution must happen **before** `import apex`.

## 16. Macro Record does not cover everything

Recorded macros are a good starting point but several areas are not captured,
including geometry cleanup, incremental meshing, feature mesh settings, import
and export, application settings, auto-thickness attribution, interface points,
cross-section force sensors, and study/scenario definitions. A user reporting
"the macro is empty" for one of these is hitting a documented limitation, not a
bug.

## 17. Calls the reference documents but the installed Apex rejects

`api/` is generated from Iberian Lynx FP2. A few calls it lists raise in Apex
2024.1, and a few accept arguments they then ignore. Known cases are kept in
`tools/runtime_overrides.json` and stamped into the reference. An index line
tagged **[raises at runtime in Apex 2024.1]** or **[fails silently at runtime in
Apex 2024.1]** has a note under its signature with what to use instead.

`apex.catalog.createPropertiesElement3DHomogeneous` is the common one. It raises
`THIS FUNCTION IS DEPRECATED`. Build the PSOLID with
`apex.catalog.createPropertiesElement3D` instead (section 12 of
[patterns-and-recipes.md](patterns-and-recipes.md)).

When you find a new case, add it to `tools/runtime_overrides.json` and
regenerate.

## 18. A property `MID` given the `Material` object

```python
pm = prop.getProperties3DModel(properties3DModel="PSOLID")
pm.update(elementProperties3D={"MID": material.id})   # correct
pm.update(elementProperties3D={"MID": material})      # accepted, ignored
```

The second form raises nothing, and `pm.getProperties()` afterwards has no
`MID`. The exported PSOLID then has no material. Check with
`prop.getReferenceMaterial()`, which returns the material once MID is set.

## 19. Subcase case control that does not persist

On a `SubcaseNastran`, a value set through `getCommand(...).setValue(...)`
reads back correctly in the same script and is gone by the next one. The
export then writes no `LOAD =` line. Only this order kept the value:

```python
cmd = subcase.getCommand(commandName="LOAD")
cmd.setValue(load.id)
subcase.setCommand(commandName="LOAD", activate=True)   # after setValue
```

Calling `setCommand` first and `setValue` second lost the value too. This was
seen through a remote bridge that runs each script as a separate call, and has
not been reproduced in the Apex script editor. Either way, confirm by reading
the values back in a later script or in the exported deck's case control.

Output requests are not subcase commands. `getCommand(commandName="DISPLACEMENT")`
(and `STRESS`, `SPCFORCES`) raises `Command 'DISPLACEMENT' is UNSUPPORTED`. With
the defaults, Apex 2024.1 wrote `DISPLACEMENT(PLOT) = ALL`,
`STRESS(PLOT,VONMISES,CORNER) = ALL` and `SPCFORCES(PLOT) = ALL` above the first
subcase.

## 20. Glue or contact that exports but is never active

A glue pair is created in two steps. `apex.attribute.createInteractionManualPair`
makes a pair with no representation (`getActiveRep()` is `None`), and
`createInteractionRep(interactionType=apex.attribute.InteractionType.Glue, ...)`
makes it a glue.

Even then, Apex 2024.1 exported the `BCONECT` glue cards **without a `BCONTACT`
line in the case control**. In SOL 101 `BCONTACT` defaults to `NONE`, so the
glue is ignored and the parts are disconnected. Nothing in Apex warns about it.
Set it on every subcase, with the same order as section 19:

```python
cmd = subcase.getCommand(commandName="BCONTACT")
cmd.setValue("1")
subcase.setCommand(commandName="BCONTACT", activate=True)
```

The value is the ID of the contact set in the deck: `BCONECT` id 1 in the run
this came from. Check the exported deck. The solver side of this is in
`nastran-reference`'s
[pre-run-checklist.md](../../nastran-reference/references/pre-run-checklist.md).

## 21. Where new entities land

| Call | Lands in | Control |
|---|---|---|
| `apex.geometry.createCurve` | the most recently created part, not the part of its input locations | none on the call; `Curve.update` lists a `parent` argument (untested) |
| `apex.mesh.createNodeByLocation` | the part named by `pathName` | `pathName=part.getPathName()` |
| `apex.attribute.createNodeTie` | the assembly, as `Node Tie <id>` | none |
| loads and constraints | `/Environment/<name>` | `name=` |

Check `entity.getPathName()` after creating anything you will look up again.

## 22. Renaming is different on every class

| Class | Rename with | Note |
|---|---|---|
| most `Entity` classes | `obj.update(name=...)` | e.g. `Curve.update(name=...)` |
| `SubcaseNastran` | `subcase.setName(...)` | has no `update`: `subcase.update(name=...)` raises `AttributeError`. `setName` works in Apex 2024.1 but is **not in the reference**. `setLabel`, `setSubtitle`, `setTitle` are. |
| `NodeTie` | cannot be renamed | keep the returned objects in a dict under your own names |

Before renaming, check the class's `update` signature in `api/classes/`, or the
class in `api/methods-index.md`.
