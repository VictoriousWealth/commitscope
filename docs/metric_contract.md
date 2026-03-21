# Metric Contract

CommitScope preserves the notebook-style metrics as explicit approximations rather than claiming language-agnostic precision.

## Python Class And Method Metrics

These metrics are derived from the heuristics in [staticAnalysis.ipynb](/Users/efeon/week4-static-analysis-ug_13/staticAnalysis.ipynb).

- `CC`: cyclomatic complexity approximation. Starts at `1` and increments for `if`, `for`, `while`, and `except` branches discovered in the Python AST.
- `LOC`: method lines of code derived from `end_lineno - lineno + 1`.
- `WMC`: weighted methods per class, implemented as the sum of method `CC` values for the class.
- `LCOM`: cohesion approximation based on whether method pairs share `self.<attr>` accesses.
- `FANIN`: static approximation of how many analysed classes or methods call into the target.
- `FANOUT`: static approximation of outgoing calls observed in the AST or lightweight token scan.
- `CBO`: coupling approximation based on references to other known classes.
- `RFC`: response-for-class approximation based on public methods plus directly called methods.
- `parameters`: count of declared method parameters excluding `self`.

## Non-Python Files

For Java, JavaScript, TypeScript, HTML, CSS, and other mainstream text-based languages, CommitScope currently produces:

- language-aware file counts
- LOC
- churn-ready file metadata
- heuristic branch and call signals via token scans

These results are intentionally lighter than the Python AST metrics. The pipeline still includes them in commit summaries, file-level datasets, and cross-language reporting so the repository is not reduced to Python-only coverage.

## Reporting Guidance

QuickSight-ready datasets should be interpreted as trend and hotspot indicators, not ground-truth formal verification. The value of the MVP is consistency over time across commits rather than perfect semantic precision for every language feature.
