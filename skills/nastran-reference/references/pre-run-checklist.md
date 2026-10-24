# Pre-run checklist for an exported deck

Checks to make on a deck written by a pre-processor (Apex, or any other)
before it goes to the solver. Each one is a deck that runs without a fatal
message and still gives the wrong answer, or results you cannot open.

Quotations are from the **MSC Nastran 2025.2** Quick Reference Guide. If your
solver is an older release, say so when you rely on them. Most of these checks
are automated by `nastran-diagnostics` (`tools/run_digest.py --bdf deck.bdf`),
and each item names the finding code it raises.

## 1. Glue and contact need `BCONTACT` in the case control

A deck can carry a complete glue or contact definition (`BCONECT`, `BCTABLE`,
`BCTABL1` with their surfaces and bodies) and still have no contact in the
analysis, because nothing selects it.

> `NONE` | All contact definitions (BCTABLE, BCTABL1, BCONECT, BCBODY, and
> BCBODY1) are ignored. For SOL 400 and SOL 101, if BCONTACT = NONE is entered
> in any subcase, it applies for all subcases. (Default for SOLs 101 and 400.)

> The contact analysis during any loadcase is dominated by BCONTACT=n (n>0).
> Without the presence of BCONTACT=n (n>0), no contact analysis works in that
> particular loadcase.

> `n` | Identification number of a BCTABLE, BCTABL1, BCONECT, BCHANGE, and/or
> BCMOVE Bulk Data entry.

— [BCONTACT (Case), MSC Nastran 2025.2 QRG](https://nexus.hexagon.com/documentationcenter/en-US/bundle/MSC_Nastran_2025.2/page/Nastran/Quick_Reference_Guide/Case_Control_Commands/Case_Control_Commands/38_BCONTACT_Case.htm)

**Check:** if the bulk data has `BCONECT`, `BCTABLE` or `BCTABL1`, every
subcase that should see the contact needs `BCONTACT = n`, with `n` the ID of
that entry, and no subcase may say `BCONTACT = NONE`.

> **Not found in the documentation — observed:** Apex 2024.1 exported a SOL 101
> deck with a glued `BCONECT` pair and no `BCONTACT` line at all. The parts were
> therefore unconnected for the solver. Adding `BCONTACT = 1` to each subcase
> (1 being the `BCONECT` ID) made Nastran report the permanent glue as active.

Finding code: `CONTACT_INACTIVE`.

## 2. An RBE2 dependent DOF is dependent only once

> Dependent degrees-of-freedom assigned by one rigid element may not also be
> assigned dependent by another rigid element or by a multipoint constraint.

— [RBE2, MSC Nastran 2025.2 QRG](https://nexus.hexagon.com/documentationcenter/en-US/bundle/MSC_Nastran_2025.2/page/Nastran/Quick_Reference_Guide/Bulk_Data_Entries/Entries_Q_S/23_RBE2.htm), Remarks

**Check:** no grid appears as a dependent (`GMi`) of two `RBE2`s, of an `RBE2`
and an `RBE3`'s dependent list, or of an `RBE2` and an `MPC`, for the same
component.

> **Not found in the documentation — general engineering knowledge:** this
> usually happens where two spiders share a face edge, or where a bolt-end
> spider and a load spider pick up the same ring of nodes.

Finding code: `DOUBLE_DEPENDENT`.

## 3. An RBE2 dependent DOF is not also constrained by an SPC

> The m‑set coordinates specified on this entry may not be specified on other
> entries that define mutually exclusive sets. See Degree-of-Freedom Sets for a
> list of these entries.

— [RBE2, MSC Nastran 2025.2 QRG](https://nexus.hexagon.com/documentationcenter/en-US/bundle/MSC_Nastran_2025.2/page/Nastran/Quick_Reference_Guide/Bulk_Data_Entries/Entries_Q_S/23_RBE2.htm), Remarks

> **Not found in the documentation — general engineering knowledge:** the
> Degree-of-Freedom Sets page this remark points to is not in the bundled
> index. `SPC`/`SPC1` put DOFs in the s-set, which is one of the sets mutually
> exclusive with the m-set, so a constrained dependent DOF is the case this
> remark forbids. In an assembly it typically happens when a spider's
> attachment region (a hole wall, a seat face) shares nodes with a clamped face.
> Leave the shared edge ring out of the spider, or move the constraint.

Finding code: `SPC_ON_DEPENDENT`.

## 4. HDF5 results need the Nastran HDF5 plugin to be read

> CMPRMTHD | Compress method. Characters, "NONE", "BLOSCLZ", "LZ4" (default) or
> "GZIP".

> It is required to set below environment variable to view or use hdf5
> utilities for an hdf5 file compressed by LZ4 or BloscLZ filter.
> HDF5_PLUGIN_PATH=<msc_nastran_version>/<arch>/lib/hdf5plugin/plugins

— [HDF5OUT, MSC Nastran 2025.2 QRG](https://nexus.hexagon.com/documentationcenter/en-US/bundle/MSC_Nastran_2025.2/page/Nastran/Quick_Reference_Guide/Bulk_Data_Entries/Entries_F_L/62_HDF5OUT.htm)

The same page notes that quotation marks cannot be used in the path, even if it
contains spaces.

> **Not found in the documentation — observed:** the quotation is from the
> `HDF5OUT` entry. Apex 2024.1 requests HDF5 with `MDLPRM,HDF5,1` instead, and
> MSC Nastran 2024.1 still wrote a compressed file (HDF5 filter 32001, Blosc).
> `h5py` could not read the result datasets until `HDF5_PLUGIN_PATH` pointed at
> `<install>\msc20241\win64i8\lib\hdf5plugin\plugins`. Set it before `h5py` is
> imported:
>
> ```python
> import os
> NASTRAN_HOME = r"..."   # the Nastran install folder that contains msc20241
> os.environ["HDF5_PLUGIN_PATH"] = os.path.join(
>     NASTRAN_HOME, "msc20241", "win64i8", "lib", "hdf5plugin", "plugins")
> import h5py
> ```

This one is not a deck fault, so there is no finding code.

## 5. Every subcase selects what it should

> **Not found in the documentation — general engineering knowledge:** read the
> case control above `BEGIN BULK` and confirm one `SUBCASE` per load case, each
> with the `LOAD` and `SPC` IDs you intended (and `BCONTACT` from item 1). An
> exporter can write a subcase with its selection missing. With no `LOAD` the
> subcase solves and reports zero response. With no `SPC` a static subcase
> usually stops on a singular stiffness matrix, which looks like a constraint
> problem rather than an export problem.

Finding code for selections that point at undefined sets: `MISSING_SET`.
