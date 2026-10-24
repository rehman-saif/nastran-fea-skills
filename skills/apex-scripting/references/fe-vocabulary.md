# FE vocabulary to Apex names

Analysts say "glue", "RBE2" and "SPC". Apex says interaction, node tie and
displacement constraint, so grepping the API for the FE word usually finds
nothing. Grep this file for the FE word, then confirm the call in `api/`
before writing it.

**Status** says how far each row has been checked:

- **ran**: ran in Apex 2024.1 and produced the Nastran card shown. There is a
  worked example in section 12 of [patterns-and-recipes.md](patterns-and-recipes.md).
- **api**: the name and signature are in `api/`, but the call has not been run.
  Read its per-argument documentation first.

Calls are written without their arguments where the arguments are the usual
ones. Methods are written on a variable (`pair.`, `scn.`, `sub.`). Look them
up in `api/methods-index.md`.

## Connections

| FE term | Apex concept | Calls | Status |
|---|---|---|---|
| glue, bonded contact, tied contact, permanent glue, BCONECT | interaction with a Glue representation | `apex.attribute.createInteractionPropertyGeometric` → `apex.attribute.createInteractionManualPair(targetSide1=, targetSide2=)` → `pair.createInteractionRep(interactionType=apex.attribute.InteractionType.Glue, interactionPropertyGeometric=)` | ran: BCONECT + BCONPRG. Needs `BCONTACT` in the subcases ([pitfalls.md](pitfalls.md) §20) |
| automatic contact detection, glue by proximity | automatic interaction pairs | `apex.attribute.createInteractionAutoPair(targetSide=, pairTolerance=, interactionType=)` | api |
| general contact, touching contact, frictional contact | interaction, GeneralContact | `InteractionType.GeneralContact`; friction via `apex.attribute.createInteractionPropertyPhysical` | api |
| self contact | interaction, SelfContact | `InteractionType.SelfContact` | api |
| RBE2, rigid spider, rigid link, rigid MPC | node tie (GUI: Discrete Tie), rigid | `apex.attribute.createNodeTie(referencePoint=, attachmentRegions=, dependentDoF="123456", distributionType=apex.attribute.DistributionType.Rigid)` | ran: RBE2 |
| RBE3, distributing coupling, interpolation element, load spreader | node tie, compliant | `apex.attribute.createNodeTie(..., distributionType=apex.attribute.DistributionType.Compliant)`, weights via `DOFAndWeightFactors=` | api. The Apex GUI help (Discrete Tie, node 2272) says a compliant tie "defines an RBE3" |
| independent node, reference node, master node | mesh node | `apex.mesh.createNodeByLocation(coordinates=apex.Coordinate(x, y, z), pathName=part.getPathName())` | ran: GRID |
| remote point | remote point entity | `apex.attribute.createRemotePointEntity(x=, y=, z=)` | api |
| beam bolt, 1D bolt, CBEAM bolt | curve + beam span + curve mesh + a node tie at each end | `apex.geometry.createCurve(behavior=apex.geometry.CurveBehavior.Polyline)` → `apex.attribute.createBeamShapeSolidRound` → `apex.attribute.createBeamSpanFree(beamTarget=, shapeEndA=, material=)` → `apex.mesh.createCurveMesh` → `apex.attribute.createNodeTie` ×2 | ran: CBEAM + PBEAML + 2 RBE2 |
| solid bolt, 3D bolt | 3D bolt by cross section | `apex.attribute.createBolt3DByCrossSectionAutomatic`, `apex.attribute.createBolt3DByCrossSectionManual` | api |
| beam section, CBEAM, CBAR, PBEAML | beam span with a beam shape | `apex.attribute.createBeamShape*` (SolidRound, HollowRound, ISymmetric, ...), `apex.attribute.createBeamSpanFree`, `apex.attribute.createBeamSpanFreeByVector` | ran for SolidRound; others api |
| spring, CBUSH, bushing, connector | discrete connector | `apex.attribute.createConnectorDiscrete` (`apex.attribute.createConnector` is deprecated), `apex.attribute.createBushingRepProperties`, `apex.attribute.createSpring1DRepProperties` | api |
| point mass, CONM2, lumped mass | point mass | `apex.attribute.createPointMass(mass=, location=, target=, applicationMethod=)` | api |
| mesh-dependent tie between faces or edges | mesh-dependent tie | `apex.attribute.createMeshDependentTie` | api |

## Constraints and loads

| FE term | Apex concept | Calls | Status |
|---|---|---|---|
| SPC, fixed, clamped, encastre | displacement constraint, Clamped | `apex.environment.createConstraintDisplacement(target=, constraintType=apex.attribute.ConstraintType.Clamped, applicationMethod=apex.attribute.ApplicationMethod.Direct)` | ran: SPC 123456 on every node of the face |
| pinned, roller, per-DOF SPC | displacement constraint with chosen DOFs | `apex.environment.createConstraintDisplacement(constraintType=apex.attribute.ConstraintType.General, translationX=, ..., rotationZ=)` | api: read the argument documentation for what the translation/rotation values mean |
| symmetry BC | displacement constraint, Symmetry | `constraintType=apex.attribute.ConstraintType.Symmetry` | api |
| single-point constraint | single-point constraint | `apex.environment.createConstraintSinglePoint` | api |
| FORCE, point load, nodal force | force component load | `apex.environment.createLoadForceComponent(target=, forceX=, forceY=, forceZ=, applicationMethod=apex.attribute.ApplicationMethod.Direct)` | ran: FORCE |
| MOMENT, nodal moment, torque | moment component load | `apex.environment.createLoadMomentComponent(target=, momentX=, momentY=, momentZ=, ...)` | ran: MOMENT |
| PLOAD4, pressure | constant pressure | `apex.environment.createPressureConstant` (`apex.environment.createLoadPressure` is deprecated) | api |
| GRAV, gravity, g-load | gravity | `apex.environment.createGravity`, `apex.environment.createGravityByG` | api |
| body acceleration | spatial acceleration | `apex.environment.createLoadAccelerationSpatial` | api |
| temperature load, TEMP | temperature load | `apex.environment.createLoadTemperature`, `apex.environment.createLoadTemperatureNodal` | api |
| load combination | static load combination | `apex.environment.createLoadCombinationStatic` | api |
| load or SPC set id | the entity's `id` | `load.id`, `constraint.id` | ran: the ids written to `LOAD =` and `SPC =` |

## Materials, properties and mesh

| FE term | Apex concept | Calls | Status |
|---|---|---|---|
| MAT1, isotropic material | catalog material with a MAT1 model | `apex.catalog.createMaterial(name=, primaryMaterialModel="MAT1")` → `mat.getMaterialModel(materialModel="MAT1").update(materialProperties={"E": ..., "NU": ..., "RHO": ...})` | ran: MAT1 |
| PSOLID | 3D element property | `apex.catalog.createPropertiesElement3D(primaryProperties3D="PSOLID")` → `prop.getProperties3DModel(properties3DModel="PSOLID").update(elementProperties3D={"MID": mat.id})` → `apex.attribute.assignPropertiesElement3D(target=, property=)` | ran: PSOLID. MID must be the integer id |
| PSHELL | 2D element property | `apex.catalog.createPropertiesElement2D(primaryProperties2D="PSHELL")` → `prop.getProperties2DModel(properties2DModel="PSHELL").update(elementProperties2D={...})` → `apex.attribute.assignProperty2D(property2d=, target=)` | api. The dictionary keys are not verified: print `getProperties()` on the model first |
| material on geometry | material assignment | `apex.attribute.assignMaterial(target=, material=)` | api |
| CTETRA, tet mesh | solid mesh | `apex.mesh.createSolidMesh(target=, meshSize=, elementOrder=apex.mesh.ElementOrder.Quadratic)` | ran: 10-node CTETRA |
| CHEXA, hex mesh | hex mesh | `apex.mesh.createHexMesh` | api |
| CQUAD4, CTRIA3, shell mesh | surface mesh | `apex.mesh.createSurfaceMesh(meshType=apex.mesh.SurfaceMeshElementShape.Mixed, ...)` | api ([patterns-and-recipes.md](patterns-and-recipes.md) §7) |
| beam mesh | curve mesh | `apex.mesh.createCurveMesh(target=, meshSize=, elementOrder=apex.mesh.ElementOrder.Linear)` | ran: CBEAM |

## Analysis, case control and export

| FE term | Apex concept | Calls | Status |
|---|---|---|---|
| SOL 101, linear static | Nastran scenario | `apex.getPrimaryStudy().createScenarioNastran(scenarioNastranType=apex.studies.NastranSolutionType.Statics_101, numberOfSubcases=, subcaseType=apex.studies.NastranAnalysisType.Statics)` → `scn.associateModelRep(modelRep=assembly)` | ran: SOL 101 |
| SOL 103, normal modes | Nastran scenario | `NastranSolutionType.Modes_103`, `NastranAnalysisType.Modes` | api |
| SOL 105, buckling | Nastran scenario | `NastranSolutionType.Buckling_105`, `NastranAnalysisType.Buckling` | api |
| SUBCASE, load case | `SubcaseNastran` | `scn.getSubcases()`; more with `createSubcase` | ran |
| SUBTITLE, LABEL, TITLE | load case item text | `sub.setSubtitle`, `sub.setLabel`, `sub.setTitle` (rename: `sub.setName`) | ran: setSubtitle, setLabel, setName |
| case control `LOAD =`, `SPC =`, `BCONTACT =` | scenario command on the subcase | `cmd = sub.getCommand(commandName="LOAD"); cmd.setValue(id); sub.setCommand(commandName="LOAD", activate=True)` | ran. The order matters ([pitfalls.md](pitfalls.md) §19) |
| output requests: DISPLACEMENT, STRESS, SPCFORCES | scenario defaults, not subcase commands | none needed for the defaults. `sub.getCommand(commandName="STRESS")` raises UNSUPPORTED | ran: all three written `= ALL` |
| export BDF, write the deck | scenario export | `scn.exportFEModel(filename=, unitSystem=, resultOutputType=apex.attribute.NastranResultOutputType.Hdf5)`; whole model: `apex.currentModel().exportFEModel` | ran |
| HDF5 / OP2 / XDB results | result output type | `apex.attribute.NastranResultOutputType.Hdf5`, `.Op2`, `.Xdb` | ran for Hdf5: `MDLPRM,HDF5,1` |
| unit system | script unit system | `apex.setScriptUnitSystem(unitSystemName="mm-t-s-N-K")` | ran |

Found a mapping that is missing or wrong? Add or fix the row, and mark it
**ran** only if you ran it.
