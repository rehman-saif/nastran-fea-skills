# Apex scripting cheat sheet

The rules that break most generated Apex code. The full version, with examples,
is [scripting-model.md](scripting-model.md).

- `import apex` loads every module. Call `apex.setScriptUnitSystem(unitSystemName="mm-t-s-N-K")`
  (or your system) before creating or measuring anything.
- **Keyword arguments**: `createSolidMesh(target=t, meshSize=3.0)`. Only the
  names are documented, not the order.
  Value types are the exception: `apex.Coordinate(0.0, 0.0, 1.0)`, `apex.ColorRGB(r, g, b)`.
- **Change entities with `update(...)`**. Assigning `obj.prop = x` raises
  `AttributeError` (no setter).
  Some classes have no `update` (a Nastran subcase has `setName`): check `api/methods-index.md`.
- **Collections are not lists**: `c = apex.EntityCollection(); c.appendList([...])`.
  Count with `c.len()` (or `len(c)`), convert with `c.toList()`.
- **Never iterate `mesh.elements` / `part.nodes`** on a real model: it makes one
  Python object per element and can exhaust Apex's memory. Use
  `mesh.getElementIDs()` (`{topology: ids}`), `getNodeIDs()`, `getNodeCoordinates()`.
- **One return value**. Several results come back on a `ZResult*` object; read
  its properties (`api/classes/<module>.md`).
- `model.getParts(recursive=True)` for nested assemblies.
- Failures raise exceptions. Some calls also fail silently: an ignored argument
  or a value that does not persist. Read [pitfalls.md](pitfalls.md) §17–22.
- Property `MID` takes the material's integer id (`material.id`), not the
  `Material` object.
- Subcase case control: `cmd = sub.getCommand(commandName="LOAD"); cmd.setValue(load.id)`,
  **then** `sub.setCommand(commandName="LOAD", activate=True)`.
- **Look the call up before writing it**:
  - `api/functions-index.md` for module functions
  - `api/methods-index.md` for class methods
  - `api/enums.md` for enum members
  - [fe-vocabulary.md](fe-vocabulary.md) to go from an FE term (glue, RBE2, SPC) to the Apex name
- A **[raises at runtime]** or **[fails silently]** tag on an index line means
  the reference is wrong for the installed Apex. Read the note before using the call.
- Names `api/` puts in the wrong module or that Apex 2024.1 lacks:
  [runtime-2024.1.md](runtime-2024.1.md).
