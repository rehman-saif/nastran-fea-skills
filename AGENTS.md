# fea-structural-help — agent instructions

Structural FEA help for **MSC Apex** and **MSC Nastran**. This repository is a
set of five skills. Each one lives in `skills/<name>/SKILL.md` and owns the
indexes, references and Python helpers in its own folder.

This file is for coding agents that are not Claude Code (Codex, Gemini CLI,
Cursor, Copilot and others). Claude Code loads the same skills through
`.claude-plugin/plugin.json`.

## How to use this repository

1. **Pick the skill** from the routing table below.
2. **Read that skill's `SKILL.md` in full before answering** and follow its
   *Required workflow* section step by step. The skills are not
   self-explanatory from their file names: they contain false-friend warnings,
   lookup orders and citation rules that change the answer.
3. **Open only the files the skill tells you to open.** Several reference
   files are large (the Apex API reference, the Nastran message index). Search
   them with `grep` or `rg` for the keyword, message number or function name
   rather than reading them whole.
4. When a skill hands off to another one ("for X use nastran-reference"), read
   that skill's `SKILL.md` before continuing.

## Routing

| The user wants… | Read |
|---|---|
| How to model something: shell vs solid, how to represent a bolt, weld or joint, where to constrain, mesh density, what result to expect, whether a result is believable | `skills/fea-modelling-strategy/SKILL.md` |
| How to do something in the Apex GUI, what a tool or setting does, where a feature lives | `skills/apex-docs/SKILL.md` |
| Apex Python: write, fix or review a script, macro or custom tool, or look up an `apex` function, enum or class | `skills/apex-scripting/SKILL.md` |
| What a Nastran bulk data entry, case control command, parameter or solution sequence means (CQUAD4, PSHELL, RBE2, PARAM, SUBCASE, SOL 101…) | `skills/nastran-reference/SKILL.md` |
| Why a Nastran run failed or looks wrong: UFM/SFM/UWM numbers, singular matrix, rigid body modes, or a `.f06`, `.f04`, `.log` or `.bdf` to inspect | `skills/nastran-diagnostics/SKILL.md` |

When a question spans stages (for example, "my run fails with UFM 9050 and I
don't know how to constrain this bracket"), start with the skill that matches
the immediate problem and hand off when you reach the other half.

## Rules every skill follows

- **Cite the documentation.** Quote it and give the page or entry you took it
  from.
- **Label everything else.** Anything that goes beyond the documentation must
  be marked:

  > **Not found in the documentation — general engineering knowledge:** …

  The Apex and Nastran documentation contain very little engineering theory,
  so most "why" answers are reasoning. The reader must always be able to tell
  which part of an answer is documented and which part is reasoned.
- **Do not invent** Apex API signatures, Nastran field meanings, defaults or
  message texts. If a lookup finds nothing, say so.

## Running the Python helpers

Each skill's `SKILL.md` shows its commands as `python tools/<script>.py …`,
relative to the skill's own folder. Either `cd` into that folder first or call
the script by its full path, for example:

```sh
python skills/apex-docs/tools/fetch_page.py <id>
python skills/nastran-diagnostics/tools/fetch_message.py 9050
python skills/nastran-diagnostics/tools/run_digest.py --f06 RUN.f06 --log RUN.log -o OUT
```

The scripts find their data relative to their own location, so either form
works. They need Python 3 and only the standard library. The documentation
fetchers need network access to the Hexagon documentation backend and cache
pages under each skill's `cache/` folder.

## Maintaining the skills

Do not edit the generated indexes by hand. Each skill's `SKILL.md` names its
build and `validate.py` scripts. Rerun them after changing a source and make
sure validation exits 0.
