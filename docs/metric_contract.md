# Metric Contract

CommitScope preserves the notebook-style metrics as explicit approximations rather than claiming language-agnostic precision.

## AST-Backed Languages

CommitScope now performs structural parsing for these languages:

- Python: built-in `ast`
- Java: `JavaParser`
- JavaScript: `@babel/parser`
- TypeScript: `ts-morph`

These analyzers extract classes, methods, constructors, and method bodies from language-native syntax trees rather than from regex-only text scans. The metrics still follow notebook-style intent, but they are not full compiler or type-checker implementations.

## Class And Method Metrics

- `CC`: cyclomatic complexity approximation. Starts at `1` and increments for branch and control-flow nodes discovered in the language parser.
- `LOC`: method lines of code derived from structural source ranges where available.
- `WMC`: weighted methods per class, implemented as the sum of method `CC` values for the class.
- `LCOM`: cohesion approximation based on whether method pairs share instance-field access patterns.
- `FANIN`: static approximation of how many analysed classes or methods call into the target.
- `FANOUT`: static approximation of outgoing calls observed in the parsed method body.
- `CBO`: coupling approximation based on references to other known classes or types.
- `RFC`: response-for-class approximation based on public methods plus directly called methods.
- `parameters`: count of declared method parameters, excluding implicit receiver parameters where relevant.

## Precision Notes

AST-backed parsing improves robustness for unusual formatting, annotations, generics, decorators, constructors, and class-field arrow functions. It does not mean the project performs full semantic resolution.

These metrics remain approximations:

- `FANIN`
- `FANOUT`
- `LCOM`
- `CBO`
- `RFC`

They are intended for hotspot detection and trend analysis, not for compiler-grade proof of architectural dependency structure.

## Other Languages

For HTML, CSS, and other mainstream text-based languages outside the AST-backed set above, CommitScope currently produces:

- language-aware file counts
- LOC
- churn-ready file metadata
- heuristic branch and call signals via token scans

These results are intentionally lighter than the class and method metrics. The pipeline still includes them in commit summaries, file-level datasets, and cross-language reporting so the repository is not reduced to only the fully parsed languages.

## Reporting Guidance

QuickSight-ready datasets should be interpreted as trend and hotspot indicators, not ground-truth formal verification. The value of the MVP is consistency over time across commits rather than perfect semantic precision for every language feature.
