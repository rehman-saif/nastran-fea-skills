# Patterns and recipes

Verified building blocks for Apex batch scripts and custom tool worker scripts.
Every signature here was checked against `api/`. Confirm any function you add
beyond these the same way.

## Table of contents

1. Script skeleton
2. Model access
3. Traversing the hierarchy
4. Building collections
5. Acting on the user's selection
6. Importing and exporting
7. Meshing
8. Materials and attribution
9. Reporting progress
10. Measuring and querying
11. Safe mutation
12. Linear static (SOL 101) model, step by step

## 1. Script skeleton

```python
import apex

apex.setScriptUnitSystem(unitSystemName=r"m-kg-s-N")

model = apex.currentModel()
```

For a script invoked from a custom tool, suppress the trailing output dialog:

```python
apex.disableShowOutput()
```

Re-enable it with `apex.enableShowOutput()` if a later step should report.

## 2. Model access

```python
model = apex.currentModel()          # the session's single current model
model = model.close()                # close and start an empty model
model = apex.createModel(name="New Model")
```

`close()` returns the *new* empty model — rebind the name, do not keep using the
old handle.

## 3. Traversing the hierarchy

`Model` -> `Assembly` -> `Part` -> geometry and mesh entities.

```python
parts = model.getParts(recursive=True)

for part in parts:
    for solid in part.solids:
        print(part.name, solid.name, solid.volume)
```

Useful `Part` properties: `solids`, `surfaces`, `curves`, `points`,
`geometryBodies`, `meshes`, `nodes`, `elements`, `beamSpans`, `partProperties`.

`getParts(recursive=True)` flattens nested assemblies; without it you get only
direct children.

## 4. Building collections

Most bulk functions take an `apex.EntityCollection`. Build one with
`appendList`, because a Python list is not accepted:

```python
bodies = apex.EntityCollection()
bodies.appendList([body
                   for part in model.getParts(recursive=True)
                   for body in part.geometryBodies])
```

Filter first, then append, so the collection holds only real targets:

```python
large = apex.EntityCollection()
large.appendList([s
                  for part in model.getParts(recursive=True)
                  for s in part.solids
                  if s.volume >= 1.0e-4])
```

## 5. Acting on the user's selection

The natural input for a custom tool: operate on what the user picked.

```python
targets = apex.selection.getCurrentSelection()
```

It returns an `EntityCollection`. Constrain *what* can be picked through the
tool's pick filter rather than by filtering afterwards — see
[gui-sdk-reference.md](gui-sdk-reference.md).

## 6. Importing and exporting

```python
model.importGeometry(geometryFileNames=[r"C:\data\part.x_t"])
```

Optional flags (all default `True` unless noted): `importSolids`,
`importSurfaces`, `importCurves`, `importPoints`, `importGeneralBodies`,
`cleanOnImport`; `importHiddenGeometry` and `sewOnImport` default `False`.

```python
model.exportFEModel(filename=r"C:\out\model.bdf", unitSystem="m")

model.exportGeometry(filename=r"C:\out\model.x_t",
                     cadFormat=apex.geometry.CADFormat.ParasolidText)
```

`CADFormat` members are exactly: `ParasolidText`, `ParasolidBinary`, `STLText`,
`STLBinary`, `ACISText`, `IGES_5_3`, `STP_AP214`. There is no plain `Parasolid`
or `STL` member — this is a typical place to guess wrong, so check `api/enums.md`
for any enum before using it.

## 7. Meshing

```python
result = apex.mesh.createSurfaceMesh(
    target=bodies,
    meshSize=5.0,
    meshType=apex.mesh.SurfaceMeshElementShape.Mixed,
    meshMethod=apex.mesh.SurfaceMeshMethod.Auto,
    elementOrder=apex.mesh.ElementOrder.Linear)
```

`createSolidMesh`, `createHexMesh`, `createHybridMesh` and `createCurveMesh`
follow the same shape. Each returns a `ZResult*` object, not the mesh itself —
read the meshes from its properties.

Element counts come from the entity, via `.len()` on the collection:

```python
for entity in apex.selection.getCurrentSelection():
    print(entity.nodes.len(), entity.elements.len())
```

## 8. Materials and attribution

Create or fetch the material in `apex.catalog`, assign it in `apex.attribute`:

```python
material = apex.catalog.getMaterial(name="Steel")
apex.attribute.assignMaterial(target=solid_collection, material=material)
```

Prefer the bulk assignment above to calling `solid.assignMaterial(...)` in a
loop.

## 9. Reporting progress

```python
apex.session.displayStatusMessage("Meshing started ...")
# ... work ...
apex.session.displayStatusMessage("Meshing completed.")
```

Use this for anything slow — it is the only feedback the user gets while a
worker script runs.

## 10. Measuring and querying

Measure and transform helpers live directly on `apex`. Proximity search is in
`apex.utility`. Grep `api/functions-index.md` for `measure` or `distance` to
find the exact call rather than computing geometry by hand.

Highlighting is useful for review tools:

```python
color = apex.ColorRGB(214, 255, 0)
solid.highlight(colorRGB=color, lineWidth=2, pointSize=3)
```

## 11. Safe mutation

Entity-derived objects change only through `update()`:

```python
mesh_body.update(meshSize=8.0, elementOrder=apex.mesh.ElementOrder.Quadratic)
```

Guard operations that can genuinely fail, and let everything else raise:

```python
try:
    model.importGeometry(geometryFileNames=[path])
except Exception as exc:
    apex.session.displayStatusMessage("Import failed: %s" % exc)
    raise
```

Collect the entities you intend to change before changing them. Mutating while
iterating a live collection gives unpredictable results.

## 12. Linear static (SOL 101) model, step by step

Each block below ran in **Apex 2024.1** and produced a SOL 101 deck that
Nastran solved cleanly: an assembly of three solid parts with glue, beam bolts,
an RBE2 load spider, a clamped face and four subcases. They are written as
separate steps because that is how they were run. Names and part paths are
from that model, so replace them with yours. Units are `mm-t-s-N-K`
throughout. For the traps behind several of these steps, see sections 17–22 of
[pitfalls.md](pitfalls.md).

### 12.1 Helpers used below

```python
import apex
import numpy as np   # ships with Apex

apex.setScriptUnitSystem(unitSystemName="mm-t-s-N-K")

def coll(items):
    c = apex.EntityCollection()
    c.appendList(list(items))
    return c

def faces_by_id(part_path, ids):
    """Faces of the part's solids by face id (find ids from f.centroid / f.area)."""
    part = apex.getPart(pathName=part_path)
    out = [f for s in part.solids for f in s.getFaces() if str(f.id) in ids]
    assert len(out) == len(ids), (part_path, ids)
    return coll(out)
```

To find a face, print `f.id`, `f.area` and `f.centroid` for every face of the
part's solids, then pick by position.

### 12.2 Material (MAT1)

```python
steel = apex.catalog.createMaterial(name="Steel4340", primaryMaterialModel="MAT1")
steel.getMaterialModel(materialModel="MAT1").update(
    materialProperties={"E": 205000.0, "NU": 0.29, "RHO": 7.85e-9})
```

`getProperties()` on the material model is empty until this `update`.

### 12.3 PSOLID, assignment and solid mesh

```python
part = apex.getPart(pathName="base/GE_Bracket_Assembly/Bracket/Part 4")
prop = apex.catalog.createPropertiesElement3D(name="PSOLID_Bracket",
                                              primaryProperties3D="PSOLID")
prop.getProperties3DModel(properties3DModel="PSOLID").update(
    elementProperties3D={"MID": steel.id})          # the integer id, not the object
solids = coll(part.solids)
apex.attribute.assignPropertiesElement3D(target=solids, property=prop)
apex.mesh.createSolidMesh(name="Mesh_Bracket", target=solids, meshSize=3.0,
                          elementOrder=apex.mesh.ElementOrder.Quadratic)   # CTETRA(10)
```

Do not use `createPropertiesElement3DHomogeneous`: it raises in Apex 2024.1.
`prop.getReferenceMaterial().name` confirms the MID took.

### 12.4 Glue between two faces

```python
geo = apex.attribute.createInteractionPropertyGeometric(
    name="GlueGeom_0p5mm",
    contactToleranceCalculationMethod=apex.AutoManual.Manual, contactTolerance=0.5)
pair = apex.attribute.createInteractionManualPair(
    name="Glue_Bracket_BasePlate",
    targetSide1=faces_by_id("base/GE_Bracket_Assembly/Bracket/Part 4", ["32201"]),
    targetSide2=faces_by_id("base/GE_Bracket_Assembly/BasePlate/Part 3", ["377"]))
pair.createInteractionRep(name="GlueRep_Bracket_BasePlate",
                          interactionType=apex.attribute.InteractionType.Glue,
                          interactionPropertyGeometric=geo)
```

This exported as `BCONECT`/`BCONPRG` permanent glue, but **with no `BCONTACT`
in the case control**. Set it per subcase (12.9), or the glue is inactive.

### 12.5 Reference node and RBE2 spider on a face

```python
asm = apex.getAssembly(pathName="base/GE_Bracket_Assembly")
conn = asm.createPart(name="Connections")        # holds reference nodes and beams
ref = apex.mesh.createNodeByLocation(coordinates=apex.Coordinate(-74.028, -56.85, 114.644),
                                     pathName=conn.getPathName())
spider = apex.attribute.createNodeTie(
    referencePoint=ref, dependentDoF="123456",
    attachmentRegions=faces_by_id("base/GE_Bracket_Assembly/LiftingLink/Part 2", ["34225"]),
    distributionType=apex.attribute.DistributionType.Rigid)                      # RBE2
```

The other option, `DistributionType.Compliant`, is the default; it was not
exercised in this run. The tie is created at assembly level and cannot be
renamed, so keep the returned object.

### 12.6 Beam bolt with a spider at each end

A bolt is a curve, a beam span on its edges, a curve mesh, and an RBE2 from each
end node to the faces it clamps.

```python
pts = apex.ILocationCollection()
pts.appendList([apex.Coordinate(0.0, 0.0, 7.849), apex.Coordinate(0.0, 0.0, -12.647)])
curve = apex.geometry.createCurve(target=pts, behavior=apex.geometry.CurveBehavior.Polyline)
curve.update(name="Bolt1")                      # lands in the last created part
shape = apex.attribute.createBeamShapeSolidRound(name="Bolt_D9p525", radius=9.525 / 2)
edges = apex.geometry.EdgeCollection()
edges.appendList(list(curve.getEdges()))
apex.attribute.createBeamSpanFree(name="Span_Bolt1", beamTarget=edges,
                                  shapeEndA=shape, material=steel)
apex.mesh.createCurveMesh(name="BeamMesh", target=coll([curve]), meshSize=4.0,
                          elementOrder=apex.mesh.ElementOrder.Linear)           # CBEAM

def beam_node_at(part, xyz, tol=0.01):
    """End node of a beam mesh, found from the bulk coordinate array."""
    for m in part.meshes:
        c = np.array(m.getNodeCoordinates()).reshape(-1, 3)
        ids = m.getNodeIDs()
        d = np.linalg.norm(c - np.array(xyz), axis=1)
        i = int(np.argmin(d))
        if d[i] < tol:
            return m.getNode(id=int(ids[i]))
    raise RuntimeError("no beam node at %s" % (xyz,))

head = beam_node_at(conn, (0.0, 0.0, 7.849))
apex.attribute.createNodeTie(
    referencePoint=head, dependentDoF="123456",
    attachmentRegions=faces_by_id("base/GE_Bracket_Assembly/Bracket/Part 4", ["22"]),
    distributionType=apex.attribute.DistributionType.Rigid)
```

The attachment region can also be a collection of mesh nodes, for example the
ring of nodes on a hole wall. `mesh.getNodes(ids="101-101,102-102")` takes a
string of id ranges. Pick the nodes from `getNodeCoordinates()` with numpy
rather than looping over `mesh.nodes`. Keep every spider's dependent nodes
clear of any SPC and of other spiders (see the Nastran checklist under 12.10).

### 12.7 Clamp a face

```python
fixed = apex.environment.createConstraintDisplacement(
    name="Fixed_BasePlate_Bottom",
    target=faces_by_id("base/GE_Bracket_Assembly/BasePlate/Part 3", ["33269"]),
    constraintType=apex.attribute.ConstraintType.Clamped,
    applicationMethod=apex.attribute.ApplicationMethod.Direct)        # SPC 123456, id 1
```

### 12.8 Nodal force and moment

```python
on_ref = apex.EntityCollection()
on_ref.append(entity=ref)
lc1 = apex.environment.createLoadForceComponent(
    name="LC1_vertical", target=on_ref, forceX=0.0, forceY=0.0, forceZ=35585.8,
    applicationMethod=apex.attribute.ApplicationMethod.Direct)          # FORCE, id 1
lc4 = apex.environment.createLoadMomentComponent(
    name="LC4_torsion", target=on_ref, momentX=0.0, momentY=0.0, momentZ=564924.0,
    applicationMethod=apex.attribute.ApplicationMethod.Direct)          # MOMENT
```

Each load gets an integer `id`. That id is what a subcase's `LOAD` selects.

### 12.9 SOL 101 scenario with N subcases

```python
study = apex.getPrimaryStudy()
scn = study.createScenarioNastran(
    name="GE_Bracket_SOL101",
    scenarioNastranType=apex.studies.NastranSolutionType.Statics_101,
    numberOfSubcases=4, subcaseType=apex.studies.NastranAnalysisType.Statics)
scn.associateModelRep(modelRep=asm)

def set_cc(sub, name, value):
    cmd = sub.getCommand(commandName=name)
    cmd.setValue(value)
    sub.setCommand(commandName=name, activate=True)   # after setValue, or it is lost

for sub, load, title in zip(scn.getSubcases(), loads, titles):   # loads: your load objects
    sub.setName(title)            # SubcaseNastran has no update()
    sub.setLabel(title)
    sub.setSubtitle(title)
    set_cc(sub, "LOAD", load.id)
    set_cc(sub, "SPC", fixed.id)
    set_cc(sub, "BCONTACT", "1")  # only if the model has glue or contact
```

In a **later** script, check that the values stuck:

```python
scn = apex.getPrimaryStudy().getScenarioNastran(name="GE_Bracket_SOL101")
print([(s.name, s.getCommand(commandName="LOAD").getValue(),
        s.getCommand(commandName="SPC").getValue()) for s in scn.getSubcases()])
```

Output requests (`DISPLACEMENT`, `STRESS`, `SPCFORCES`) are not subcase
commands. The scenario defaults wrote all three, for all nodes and elements.

### 12.10 Export the deck

```python
scn.exportFEModel(filename=r"C:\runs\ge_bracket.bdf", unitSystem="mm-t-s-N-K",
                  resultOutputType=apex.attribute.NastranResultOutputType.Hdf5)
```

This writes the case control and bulk data together, with `MDLPRM,HDF5,1` for
HDF5 results. Before running it, read the case control at the top of the file:
one `SUBCASE` per load case, each with `LOAD`, `SPC` and, if there is glue,
`BCONTACT`. Then work through the
[pre-run checklist](../../nastran-reference/references/pre-run-checklist.md) in
`nastran-reference`. The deck checks in `nastran-diagnostics`
(`tools/run_digest.py --bdf`) run most of it automatically.
