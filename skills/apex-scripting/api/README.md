# Generated API reference

Apex Python API for **Iberian Lynx FP2**, generated from the Doxygen XML by
`tools/gen_api.py`. This is the authority on what exists and what its signature
is. Do not write an Apex call that is not confirmed here.

Coverage: 22 modules, 989 module functions, 5108 class methods, 237
enumerations, 733 classes.

## Files

| File | Contents | Use it to |
|---|---|---|
| `functions-index.md` | every module function as `module.name — brief` | find which module owns an operation |
| `methods-index.md` | every class method as `module.Class.method — brief (inherited by ...)` | find a method when you don't know its class |
| `enums.md` | every enum with its exact members | confirm an enum member |
| `classes.md` | every class with base classes and brief | find which module owns an entity type |
| `modules/<module>.md` | that module's enums and full function signatures | get argument names, types and defaults |
| `classes/<module>.md` | that module's class properties and methods | find what an entity can do |

## How to search

Start flat, then narrow. Do not open a module file before you know the module.

```
grep -i "mesh"              api/functions-index.md
grep "createScenarioNastran" api/methods-index.md
grep -i "CADFormat"         api/enums.md
grep -i "Solid"             api/classes.md
```

A method is indexed on the class that declares it.
`apex.studies.LoadCaseItem.getCommand` ends with "(inherited by
`ScenarioNastran`, `StepNastran`, `SubcaseNastran`, `SubstepNastran`)", and
that is where you find what a subcase can do.

Enums with long member lists (`apex.EntityType` has 421) are wrapped over
several lines, each starting with the enum name, so a grep for one member
returns one short line.

Then open the one relevant file:

```
api/modules/apex.mesh.md
api/classes/apex.geometry.md
```

`apex.environment` and `apex.studies` class files are large. **Grep them rather
than reading them whole**:

```
grep -A15 '^## `apex.studies.Scenario`' api/classes/apex.studies.md
```

Each class entry lists every method signature first, one line each with a
short brief, then the full documentation under "Method details". So the first
lines after the header are always the list of what the class can do.

## Runtime notes

A few calls do not behave on a real Apex 2024.1 install as the Iberian Lynx
FP2 reference describes. Their index lines carry a tag:

- **[raises at runtime in Apex 2024.1]**
- **[fails silently at runtime in Apex 2024.1]**
- **[runtime note in Apex 2024.1]**

Each tagged block has a quoted note under its signature saying what happens and
what to use instead. The notes come from `tools/runtime_overrides.json`, which
is kept by hand; add an entry there when you observe a new case, then
regenerate.

## Reading a signature

```
### `apex.mesh.createSurfaceMesh(name: str, target: apex.EntityCollection, meshSize: float, ...) -> apex.mesh.ZResultCreateSurfaceMesh`
```

- Types are shown Python-side: `float`, `str`, `int`, `bool`, `[X]` for a list,
  `{K:V}` for a dict.
- `= value` marks a default; everything else is effectively optional too, since
  Apex supports optional arguments broadly.
- **All arguments are keyword-only.** The order shown is documentation order,
  not a calling order.
- A `ZResult*` return means several values come back on one object — check its
  entry in `classes/<module>.md` for the property names.

## Inherited members are not repeated

Each class entry lists only the members **declared on that class**. Anything it
inherits is listed under its base class, named in the `(extends ...)` header.

So `apex.Part` shows no `name` property, but its header reads
`(extends Entity, IPhysical, IDisplayable, IUserAttributes, IName, IActivatable)`
and `apex.IName` supplies `name`, `description` and `pathName`. `part.name`
is valid.

Before concluding a member does not exist, walk the base classes in the
`extends` list. The common interfaces are:

| Interface | Supplies |
|---|---|
| `apex.IName` | `name`, `description`, `pathName` (all read-only) |
| `apex.IIdentifier` | `id` |
| `apex.IPhysical` | physical/mass properties |
| `apex.IDisplayable` | visibility and display state |
| `apex.Entity` | type introspection and casting |

## Per-parameter documentation

Every argument's documentation is inline, directly under the signature it belongs
to, in `modules/<module>.md` and `classes/<module>.md`:

```
### `apex.mesh.createSurfaceMesh(name: str, target: ..., meshSize: float, ...)`
create surface mesh.

- `target` — Homogeneous List of Geometry objects to be meshed. Only Solids,
  Surfaces and Faces are supported ...
- `meshSize` — Specify the Global Edge Length to use in meshing ...
```

This is where per-argument constraints and deprecation notices live, so read the
argument list before using an unfamiliar call — several parameters are only valid
when another is set, and a few are deprecated in place.

Files are large; grep for the member name with context rather than reading a
whole module.

## Regenerating

Everything in `api/` is generated from the Apex documentation archive's
`ScriptingXML` folder. The generated markdown is what ships; the XML is not
bundled, so regeneration needs that archive:

```
python tools/gen_api.py
```

Paths come from the script's own location. Both are overridable:

```
python tools/gen_api.py [source_xml_dir] [output_package_dir]
```

The generator stops if `tools/runtime_overrides.json` names a call that is not
in the reference, so a release that renames or removes a call forces the note
to be revisited.

To move the skill to a **new Apex release**, point the generator at that
release's `ScriptingXML` folder:

```
python tools/gen_api.py <path to that release's ScriptingXML>
python tools/validate_references.py
```

`validate_references.py` re-checks every `apex.*` name used in `SKILL.md`,
`references/` and `assets/` against the regenerated index, and exits non-zero if
a name no longer exists — which is how you find prose that a release has
invalidated.
