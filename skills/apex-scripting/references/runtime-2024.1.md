# Apex 2024.1 at runtime

Measured in a running MSC Apex 2024.1 (build CLR:011290, Python 3.11.6) through
the Apex MCP bridge, November 2026. `api/` is generated from the Iberian Lynx FP2
documentation; where the two disagree, what is below is what Apex did. Re-check
on another release. With the Apex MCP server connected, `apex_describe` shows
what the running Apex has.

## Names the reference has wrong

The names are also listed under `runtime_names` in
`tools/runtime_overrides.json`, which `tools/validate_references.py` checks
against `api/`.

| In `api/` | In Apex 2024.1 |
|---|---|
| `apex.DataTable2Col`, `apex.DataTable3Col` | `apex.catalog.DataTable2Col`, `apex.catalog.DataTable3Col` |
| `apex.attribute.PointSensor` | `apex.instrument.PointSensor` |
| `apex.ConstraintAxis` | `apex.session.ConstraintAxis` |
| `apex.LocationInternal`, `apex.studies.ModalFrequencyStep` | absent |
| `apex.attribute.ExtendedKeyword`, `apex.attribute.KeywordMaterialPrimary`, `apex.attribute.KeywordMaterialSecondary`, `apex.attribute.MaterialModelType`, `apex.attribute.MaterialTypeDomain` | absent |
| `apex.geometry.GeometryFaultType`, `apex.geometry.GeometryFeatureType` | absent: `findGeometryFaults` returns fault types as plain ints, in the documented order Sliver, SmallEdge, SmallFace, Overhang, Gap, Crack, Spike |

Methods documented but absent: `apex.Entity.asEvent`, `apex.Entity.asLoadCase`,
`apex.Entity.asStep`, `apex.gendes.NonDesignRegion.getLocationInternal`,
`apex.studies.FrequencyResponseSimulationSettings.update`,
`apex.studies.MultiBodyTransientStep.getEndTime`,
`apex.studies.MultiBodyTransientStep.getOutputFrequency`,
`apex.studies.MultiBodyTransientStep.getOutputStepSize`,
`apex.studies.MultiBodyTransientStep.getOutputSteps`,
`apex.studies.Scenario.createDynamicStep`, `apex.studies.Scenario.createStaticStep`,
`apex.studies.Scenario.getAcfCommands`, `apex.studies.Scenario.getDynamicStep`,
`apex.studies.Scenario.getStaticStep`, `apex.studies.Study.createScenarioMBDScripted`,
`apex.studies.Study.createScenarioMBDStandard`.

Present but undocumented (no docstrings, signatures unknown):
`apex.display.rotateView`, `apex.display.panView`, `apex.display.zoomAtPoint`,
`apex.display.zoomInView`, `apex.display.zoomOutView`, `apex.display.checkRotatingMode`,
`apex.geometry.createBoxByCoordinateSystem`, `apex.geometry.createCylinderByCoordinateSystem`,
`apex.geometry.createEllipsoidByCoordinateSystem`, `apex.geometry.compareModel`,
`apex.runPythonScript`, `apex.runPythonFunction`, `apex.getShortPath`, and the
enum `apex.Visibility` (`Hidden` = 0, `NotSet` = -1, `Visible` = 1). The other
undocumented callables are SWIG containers (`IntList`, `StringToStringMap`, ...).

`apex.mesh` also defines classes for about 90 enums that `api/` documents under
`apex.attribute`: separate classes with the same names.

## Calling conventions

- **Positional arguments worked** in every call tried: `apex.getEntities(["a/b"])`,
  `apex.mesh.getCurveMeshes([{...}])`, `apex.deleteEntities(coll)`, `coll.append(p)`.
  Pass arguments by keyword anyway: `api/` documents names, not order, and 470 of
  the 1,297 functions are SWIG wrappers that show no parameter order at runtime.
- **An unknown keyword raises at once**, before the call does anything:
  `TypeError: getEntities() got an unexpected keyword argument 'paths'` (Python
  wrappers) or `'nme' is an invalid keyword argument for Part_update()` (SWIG).
- **Plain assignment to a property raises**:
  `AttributeError: property 'name' of 'Part' object has no setter`. It is not
  silently ignored, as older documentation says. Change properties with `update()`.
- `len(collection)` works as well as `collection.len()`.
- `apex.Model.setCurrentPart(pathName=...)` takes the path below the model:
  `"Assembly/Part"`, not `"base/Assembly/Part"` as `part.pathName` gives it. The
  full path raises `RuntimeError: Specified part is invalid in this Model`. A part
  created with `Assembly.createPart` is already current.
- The documented parameter names match the runtime: 596 of the 599 documented
  functions with a real signature have exactly the documented names, and for the
  SWIG wrappers "takes at most N keyword arguments" equals the documented count in
  all 314 checked.
- **Enums are classes of ints.** A value read back is a plain int: `part.entityType`
  is `11` for a part (`apex.EntityType` has 421 members) and `part.getVisibility()`
  is `1`. Map the int back through the enum class to get the name. Some enums have
  members `api/` leaves out, e.g. `apex.mesh.SurfaceMeshElementShape.Undefined`.
- Modules report runtime names: `apex.mesh` is named `leaf.mesh`,
  `apex.construct` is `glef.construct`, `apex.setting` is `clef.setting`; entity
  classes such as `Part` have `__module__ == "glef"`. The `apex` namespace also
  re-exports `os`, `sys` and `site`.

## Entities and properties

- **No docstrings anywhere**: modules, functions, classes, methods and properties
  all have an empty `__doc__`. Descriptions only exist in `api/`.
- `Part` has 57 properties and 190 methods; its class chain is `Part, Entity,
  IPhysical, ILocation, IDisplayable, IUserAttributes, IName, IPath, IActivatable`.
  `api/methods-index.md` often says only "inherited by 404 classes", so look up
  inherited methods on those base classes.
- **Properties that hold every element or node** (`elements`, `nodes`,
  `...Entities`, `elementIDs`, `nodeCoordinates`, `elementConnectivities`) build
  whole-model collections or arrays. Iterating `part.elements` exhausted Apex's
  memory on a 90k-element model. Count and select with the MeshBody arrays
  (`getElementIDs()`, `getNodeIDs()`, `getNodeCoordinates()`) and numpy.
- The 33 `IOrientation` properties (`orientation`, `alpha`, `euler123`, `xAxis`
  ...) are computed on every read, about 0.25 s each: reading all properties of
  one solid took 8.4 s, 0.65 s without them.
- Some properties raise on read: `activeRep` gives "only Adams Product support
  activating".
- `Part.colorRGB` is (112, 255, 184) on every part; the displayed colour is
  `color` / `getColor()`.

## Undo

- `apex.setting.getUndoRedoStackSize()` is 50.
- `apex.undo()` reverts one command per step: part create, rename
  (`update(name=)`), `deleteEntities`, `hide()` / `show()`, `update(color=)`.
- `beginUndoIndent()` ... `endUndoIndent(description=)` makes everything in
  between one step (verified with 2 creates and with 57 visibility toggles).
  Close it in `finally`.
- Visibility and colour changes are undo entries: 56 ungrouped toggles pushed an
  older entry off the stack.

## Display

- `apex.session.hideAll()` sets a visibility flag on every entity, so the earlier
  visibility cannot be restored from it; use `part.hide()` / `part.show()`.
- `apex.display.captureImage()` grabs the screen pixels of Apex's window: windows
  covering Apex end up in the image, and with the UI hidden it writes a 0-byte file
  without raising.
