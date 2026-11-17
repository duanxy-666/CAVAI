# CIVA v1.0.2 — CATIA Intelligent Verification Agent

**Offline research prototype** for verifying structured evidence of CAD models produced using AI / Vibe Coding tools, with budgeted tabular Q-learning for check-family scheduling.

> **NOT a native CATIA verifier.** Examples and the reinforcement learning benchmark are **entirely synthetic**. The available optional CATIA V5 adapter can only attempt basic metadata collection. No trustworthy native geometry extraction, model semantics understanding, proven root-cause diagnosis, or CAD editing is implemented.

## Research workflow

1. Load **explicitly authored** design requirements and a model evidence snapshot.
2. Apply deterministic rules in four check families: **parameter, geometry, feature, constraint**.
3. Report `PASS`, `FAIL`, or `UNVERIFIED`, with evidence and rule-based candidate causes.
4. Trace available feature-tree parent/child relationships to show possible change impact.
5. Under a family budget, let a **synthetically trained Q-learning policy** choose which family to check next.
6. Compare to fixed-order and visible-profile heuristic baselines on separately seeded synthetic holdout cases.

The RL policy only schedules checks. It **never changes** deterministic check results. Budget counts check **families** (which can contain multiple rules), not individual rule invocations.

## Quick start

Requires Python 3.10+. Windows users may double-click `RUN_DEMO_WINDOWS.bat`. Alternatively:

```bash
python -m pip install -e .
python -m civa demo
python -m unittest discover -s tests -v
```

View `runs/demo/full_report.html`, `runs/demo/rl_triage_report.html` and `runs/demo/benchmark.json`.

```bash
# Train with default reward +6 TP, -8 FN, -10 FP, -0.5 per family.
python -m civa train --episodes 10000 --budget 2 --out runs/q_policy.json
# Customize reward if desired (retrain afterwards).
python -m civa train --episodes 10000 --budget 2 --tp 8 --fn -10 --fp -12 --cost -1 --out runs/custom_q_policy.json
python -m civa inspect-policy --policy runs/q_policy.json
python -m civa evaluate --policy runs/q_policy.json --cases 500
python -m civa verify --mode full --snapshot examples/bracket_bad.json --requirements examples/requirements.json --out runs/full_report.html
python -m civa verify --mode budgeted --policy runs/q_policy.json --snapshot examples/bracket_bad.json --requirements examples/requirements.json --out runs/rl_report.html
```

## Reward and state

At *offline labelled training/evaluation time*:

`R = 6 × TP − 8 × FN − 10 × FP − 0.5 × number_of_selected_check_families`

TP, FP, FN are **family-level** counts derived from synthetic hidden fault truth. During real/snapshot inference, there is **no fault oracle and no calculated reward**. The observable Q-state contains only visible `risk_profile`, previous family `PASS/FAIL/UNVERIFIED` observations, and remaining budget. Actions are `parameter`, `geometry`, `feature`, `constraint`, and `STOP`.

Policy file format changed from `civa-tabular-q-v1` to **`civa-tabular-q-v2`**. Retrain old Q-tables. Synthetic reward metrics must not be presented as real-CATIA validation results.

## Source tour

| File | Purpose |
| --- | --- |
| `examples/requirements.json` | Explicit design intent and 5 sample rules |
| `examples/bracket_bad.json` | Invented measurements, feature tree and failures |
| `src/civa/core.py` | Rule validation, read-only evidence checks, dependency context, repair proposals, reports |
| `src/civa/rl.py` | Synthetic environment, hidden training labels, Q-table, update and benchmark |
| `src/civa/cli.py` | Train/evaluate/verify/demo/inspect-policy/capture-catia entrypoints |
| `src/civa/adapters/catia_v5.py` | Optional experimental metadata-only read adapter |
| `tests/` | Pure Python tests (no CATIA required) |
| `docs/读代码入门.zh-CN.md` | Beginner reading guide |
| `docs/上传GitHub.zh-CN.md` | GitHub publishing guide |

The `feature_tree` is structured evidence, **not computed from B-Rep geometry**. `feature_tree_complete` should only be `true` if the extractor explicitly guarantees complete tree coverage. Rules can validate direct parent relationships and `min`/`max` engineering limits. Dependency-based repair proposals are **hypotheses**, never confirmed causal explanations. No edits are made to CATIA files.

For the detailed Chinese tutorial see [README.zh-CN.md](README.zh-CN.md), and for method details see [docs/reinforcement_learning.md](docs/reinforcement_learning.md).

MIT license applies to original project code. Do not publish proprietary CAD documents, secrets, license data, or passwords. Unaffiliated with Dassault Systèmes.
