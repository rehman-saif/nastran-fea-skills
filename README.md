# Nastran FEA Skills

**An AI assistant for structural FEA in MSC Apex and MSC Nastran. Every answer is cited from the official documentation.**

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Works with](https://img.shields.io/badge/works%20with-Claude%20%7C%20Codex%20%7C%20Gemini%20%7C%20Cursor%20%7C%20Copilot-6f42c1)

General-purpose AI models guess about Apex and Nastran. They invent API calls,
misread bulk data fields and give vague advice about fatal errors. The Hexagon
documentation can't be searched, and Apex's step-by-step tool procedures aren't
published online at all.

This plugin gives your AI assistant those indexes and procedures, plus tools
that fetch the exact documentation page, Nastran entry or error message it
needs. Answers come with citations, and anything that is engineering judgement
rather than documented fact is labelled as such.

## What you can ask

| | Skill | Example |
|---|---|---|
| 🧭 **Plan** | `fea-modelling-strategy` | *"Shell or solid for this bracket? How should I model the bolts?"* |
| 🛠️ **Build** | `apex-docs` | *"How do I create a cross section in Apex?"* |
| 🐍 **Automate** | `apex-scripting` | *"Write a script that meshes every part and assigns materials."* |
| 📖 **Solve** | `nastran-reference` | *"What does field 5 of PSHELL mean? RBE2 or RBE3?"* |
| 🩺 **Debug** | `nastran-diagnostics` | *"My run failed with UFM 9050. Here's the .f06."* |

`nastran-diagnostics` can digest a large `.f06`, `.log` or `.bdf` and check the
deck for problems the solver reports late or not at all, such as unconstrained
parts, floating masses, unmerged grids and missing references.

---

## Install

| Platform | Support |
|---|---|
| [Claude Code](#claude-code) | ✅ Full, as a plugin |
| [Claude.ai and Claude Desktop](#claudeai-and-claude-desktop) | ✅ Full, as uploaded skills |
| [Gemini CLI](#gemini-cli) | ✅ Full, as an extension |
| [OpenAI Codex CLI](#openai-codex-cli) | ✅ Full |
| [Cursor](#cursor) | ✅ Full |
| [GitHub Copilot (VS Code)](#github-copilot-vs-code) | ✅ Full, in agent mode |
| [ChatGPT and Gemini web apps](#chatgpt-and-gemini-web-apps) | ⚠️ Partial, no live lookups |

"Full" means the assistant can read the skill files and run the bundled Python
helpers. Those helpers need Python 3 (standard library only) and internet
access to the Hexagon documentation site.

### Claude Code

Run this inside Claude Code:

```
/plugin install fea-structural-help --marketplace rehman-saif/nastran-fea-skills
```

On older versions, add the marketplace first and then install:

```
/plugin marketplace add rehman-saif/nastran-fea-skills
/plugin install fea-structural-help@nastran-fea-skills
```

The skills then work in every project. Claude picks the right one
automatically, or you can call one directly, for example
`/fea-structural-help:nastran-diagnostics`. To get updates, run
`/plugin marketplace update nastran-fea-skills`.

### Claude.ai and Claude Desktop

1. Download this repository as a ZIP and extract it.
2. Zip each folder inside `skills/` separately, for example `nastran-reference.zip`.
3. In Claude, go to **Settings → Capabilities**, turn on code execution, and
   upload each ZIP under **Skills**.

Upload only the skills you need. They work independently.

### Gemini CLI

```
gemini extensions install https://github.com/rehman-saif/nastran-fea-skills
```

The skills then work in every Gemini CLI session. To get updates, run
`gemini extensions update fea-structural-help`.

### OpenAI Codex CLI

```
git clone https://github.com/rehman-saif/nastran-fea-skills
cd nastran-fea-skills
codex
```

Codex reads [`AGENTS.md`](AGENTS.md), which tells it which skill to use for
each question. To work from another folder, copy your model files into this
folder, or point Codex at them with their full paths.

### Cursor

Clone the repository and open the folder in Cursor (**File → Open Folder**).
Cursor loads the project rule in `.cursor/rules/` and `AGENTS.md`
automatically. Ask your questions in Agent mode.

To use the skills alongside your own project, add this folder to the same
workspace (**File → Add Folder to Workspace**).

### GitHub Copilot (VS Code)

Clone the repository and open it in VS Code. Copilot reads
`.github/copilot-instructions.md` and `AGENTS.md`. Use Copilot Chat in **Agent**
mode so it can open files and run the helpers.

### ChatGPT and Gemini web apps

Custom GPTs and Gemini Gems can't run the bundled tools, and their upload
limits are too small for the full API reference. You can still get the
documentation rules and procedures:

1. Create a Custom GPT (ChatGPT) or a Gem (Gemini).
2. Paste the contents of [`AGENTS.md`](AGENTS.md) into its instructions.
3. Upload the `SKILL.md` files for the skills you need, along with their
   `references/` and `index/` files, as knowledge.
4. Turn on web browsing.

If you want full support in the OpenAI or Google ecosystem, use Codex CLI or
Gemini CLI instead.

---

## How answers are grounded

Documented facts are quoted with a citation. Anything else is marked:

> **Not found in the documentation — general engineering knowledge:** …

The Apex and Nastran manuals contain almost no engineering theory, so this label
lets you see which parts of an answer are documented and which are reasoning.

Sources: Apex Help (current), MSC Nastran 2025.2 Quick Reference and Reference
Guides, MSC Nastran 2025.1 error messages, and the Apex Python API (Iberian Lynx
FP2).

## Contributing

To rebuild the indexes, run the validators, learn how content is fetched, or
read the known limits, see [`docs/MAINTAINING.md`](docs/MAINTAINING.md).

## License

[MIT](LICENSE) © Saif ur Rehman. MSC Apex and MSC Nastran are trademarks of
their respective owners. This project is not affiliated with or endorsed by
them.
