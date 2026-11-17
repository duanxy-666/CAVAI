# Changelog

## v1.0.2 — Four-domain checks, feature context, RL decision traces (synthetic)

- Extended the rule engine from three to four scheduling families: parameter, geometry, feature, and **engineering constraint**.
- Added numeric lower/upper-bound operators, explicit feature-tree direct-parent/existence checks and conservative handling of partial graph evidence.
- Added supplied-graph upstream/downstream tracing and **unconfirmed**, proposed-only root-cause hypotheses and repair investigations.
- Expanded synthetic training labels, cases, rewards, Q-state and actions to four families plus STOP.
- Exposed CLI reward controls (`--tp`, `--fn`, `--fp`, `--cost`), `inspect-policy`, and Q-action decision traces in JSON/HTML reports.
- Added a visible-risk heuristic baseline alongside fixed-order scheduling; comparative results are measured on synthetic holdout data, not guaranteed.
- Added Chinese beginner's code-reading guide and GitHub publishing guide, new sample data and 39 offline tests.
- Bumped Q-policy format to `civa-tabular-q-v2` (**old policies must be retrained**).
- Preserved the experimental CATIA V5 **metadata-only** adapter and the read-only / non-certification limitations.

**Migration:** re-run `python -m civa train ...` on v1.0.2, as the old v1.0.1 three-family Q-table is incompatible. The examples now provide five rules across four families. Generated `runs/` artifacts are intentionally not part of the source distribution.

## v1.0.1 — Reinforcement-learning research prototype

- Added pure-Python tabular Q-learning for synthetic budgeted check scheduling.
- Added offline hidden-label reward, Q-table serialization, a fixed-order benchmark, and budgeted triage reports.
- Added deterministic checks and a Windows-only experimental metadata adapter.

**Continuing limitations:** no trusted CATIA geometry extraction/verification, real labelled dataset, automatic root-cause proof, or native CAD editing.
