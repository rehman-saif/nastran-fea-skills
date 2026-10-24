# Maintaining nastran-fea-skills

Notes for rebuilding the bundled indexes and understanding how the skills get
their content. For installing and using the skills, see the
[README](../README.md).

## How it gets its content

The Hexagon documentation portal is a JavaScript application: fetching a page URL
returns an empty shell, there is no listing, and there is no full-text search. The
portal reads its content from a raw backend that serves plain HTML, and that is
what these skills fetch.

So each skill bundles **only what cannot be fetched or found** — indexes,
procedures and generated references — and pulls page text live:

| Bundled locally | Why |
|---|---|
| Apex tool procedures (168 tools, 1,849 steps) | ship inside Apex; published nowhere online |
| Apex keyword index (1,690 aliases) | the portal cannot be searched |
| Apex Python API reference | the Doxygen pages 404 on every bundle |
| Nastran keyword index | the portal cannot be crawled; topic pages have no links |
| Nastran message index (5,552 messages) | source files are ~680 KB each; the index makes lookup cheap |

Page prose is never stored. It is fetched, cited, and — for Nastran messages —
sliced to the single message asked about, so reading one costs a few hundred
characters rather than a whole page.

## Documentation releases

Set per skill in each `config.md`, because the best source differs by book:

- Apex GUI — `msc_apex_help` (rolling)
- Nastran QRG and Reference Guide — `MSC_Nastran_2025.2`
- Nastran messages — `MSC_Nastran_2025.1` (the only release publishing them as HTML)
- Apex Python API — Iberian Lynx FP2

Every citation records its release, because bulk data fields and Apex API
signatures both change between versions.

## Diagnosing a run

`nastran-diagnostics` never reads a raw `.f06` or deck into the conversation.
`tools/run_digest.py` streams the .f06/.f04/.log (and the deck, or the deck
rebuilt from the f06 echo) into a digest of ~2-3k tokens and a queryable index.
It then checks the deck for faults the solver reports late or not at all:
unconstrained parts, load paths that exist only through glue, coarse glue
secondaries, floating masses, coincident unmerged grids, missing references,
mixed units and point loads standing in for inertia. Each finding names the
`nastran-reference` entries and the `apex-docs` question that fix it. A 191 MB
f06 of a 3.5M-DOF model digests in about 35 s. The tools are stdlib-only Python;
scipy is used when present.

## Testing locally

```
claude --plugin-dir .          # try the plugin from this checkout
claude plugin validate .       # check plugin.json and marketplace.json
```

`cache/` directories are created at runtime by the fetch tools and are ignored
by git. Clear them before packaging or uploading, or they inflate the file
count:

```
find . -type d -name cache -exec rm -rf {} +
```

## Rebuilding

Each skill has its own tools and validator:

```
python skills/nastran-reference/tools/build_index.py
python skills/nastran-diagnostics/tools/build_messages.py --resume
python skills/apex-scripting/tools/gen_api.py <path to ScriptingXML>
```

Then run every validator; each must exit 0:

```
python skills/apex-docs/tools/validate.py
python skills/apex-scripting/tools/validate_references.py
python skills/nastran-reference/tools/validate.py
python skills/nastran-diagnostics/tools/validate.py
```

The portal refuses sustained request bursts, reporting it as a DNS or
connection-reset error rather than an HTTP 429. The builders retry with backoff;
`--resume` picks up ranges that still failed.

## Releasing

The version appears in `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json` and `gemini-extension.json`. Bump all three
together; installed users only receive an update when the version changes.

## Known limits

- The raw documentation endpoint is undocumented and MSC Apex and Nastran are
  moving from Hexagon to Cadence. If it goes away, the indexes, procedures and
  API reference keep working; live page prose does not.
- The Apex archive the indexes were built from is a ~2021.4 snapshot, while the
  page text fetched is current. `apex-docs` flags the skew.
- The deck checks trace contact only for BCONECT with BCSURF, BCBODY/BCBODY1
  and BCTABL1. BGSET/BCTSET are reported but not traced; CWELD/CFAST don't join
  parts. `skills/nastran-diagnostics/references/run-digest.md` lists every limit.
- No element theory or solver theory exists in either corpus. That is what
  `fea-modelling-strategy` is for, and why it marks its reasoning.
