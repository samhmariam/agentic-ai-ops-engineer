# RealThor

Listing Supply Intelligence agent for Ciudaty PropTech — v0.1, the reproducible prototype.

## Setup

```bash
uv sync
cp .env.example .env   # set LLM_PROVIDER + its key (Vocareum by default)
```

Then launch Jupyter:

```bash
uv run jupyter notebook
```

## What This Is

RealThor v0.1 is a notebook prototype. It answers one question for the Demand Intelligence team:

> Given demand and supply signals for a region and property type, should we prioritize new listings there?

The output is free-form text — a recommendation with priority (high/medium/low), reasoning, recommended action, and confidence. v0.2 will upgrade this to structured output; for now the goal is a working, reproducible system.

## What Makes It Reproducible

This version establishes three conventions that carry forward through the entire course:

**1. Project managed by uv** — `pyproject.toml` pins dependencies and the Python version. Anyone who runs `uv sync` gets an identical environment.

**2. Data files in `data/`** — the CSVs are part of the project, not loose files next to the notebook. Paths are relative to the project root.

**3. System prompt in `prompts/`** — `system_prompt.md` is a versioned file, not an inline string. When the prompt changes, `git diff prompts/system_prompt.md` shows exactly what changed and why.

These three conventions — reproducible environment, versioned data, versioned prompts — are what separates a prototype from a system you can trust.

## Running the Notebook

Open `realthor_v01.ipynb` and run all cells. The notebook loads the prompt from `prompts/system_prompt.md`, reads demand and supply data from `data/`, and calls the OpenAI API.

Expected output: a free-form recommendation for the queried segment.

## Project Structure

```
realthor/
├── pyproject.toml          ← deps: openai, pandas, python-dotenv, ipykernel
├── uv.lock                 ← locked dependency versions
├── .python-version         ← Python 3.12
├── .env.example            ← copy to .env, set LLM_PROVIDER + its key
├── data/
│   ├── demand_signals.csv  ← demand index per region/type/bedrooms
│   └── supply_snapshot.csv ← active listing counts per segment
├── prompts/
│   └── system_prompt.md    ← v1 baseline prompt (extracted from notebook)
└── realthor_v01.ipynb      ← the agent notebook
```

## Git History

Three commits establish the project:

```bash
git log --oneline
# 3f9a1b2 feat: add realthor v0.1 notebook with versioned prompt
# c4e72d0 data: add demand and supply datasets
# a1b3c9e scaffold: initialize realthor with uv
```

Each commit is a deliberate unit: environment first, data second, agent logic third. This commit discipline carries forward through every module.

## Committing Your Work

```bash
git add prompts/system_prompt.md realthor_v01.ipynb
git commit -m "feat: add realthor v0.1 notebook with versioned prompt"
git log --oneline
```

### GITLOG.txt

`GITLOG.txt` is a plain-text snapshot of your commit history — a portable record that doesn't require running `git log`. Each module adds its commits on top; the file accumulates across the entire course.

Create it after your final commit:

```bash
git log --oneline > GITLOG.txt
git add GITLOG.txt
git commit -m "docs: add GITLOG.txt"
```

To update it in a later module after adding more commits:

```bash
git log --oneline > GITLOG.txt   # overwrites with the full accumulated history
git add GITLOG.txt && git commit -m "docs: update GITLOG.txt"
```
