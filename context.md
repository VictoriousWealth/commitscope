# 🧠 1. What this project *is* (crystal clear)

## Project Name

**CommitScope: Codebase Evolution Analytics Pipeline**

## One-line definition

> A Python + AWS data pipeline that analyzes a repository’s commit history, extracts code-quality metrics per commit, stores structured results in a data lake, and produces queryable insights and reports on how code health evolves over time.

---

# 🎯 2. What the system actually does

## Inputs

* Repository (GitHub URL or local repo)
* Config:

  * commit range or limit
  * branch
  * analysis scope (folders, file types)

---

## Outputs

* Raw data (per commit)
* Processed datasets (tables)
* Queryable analytics (Athena)
* Dashboard / charts (QuickSight or exported)
* Written findings report

---

## Core idea

You are turning:

👉 **Git history → data → insights**

---

# 🔁 3. End-to-end system flow (THIS is your logic)

```text
[1] Input repo
        ↓
[2] Extract commit history
        ↓
[3] For each commit:
        ↓
    checkout commit
        ↓
    run static analysis (AST)
        ↓
    compute metrics
        ↓
    store raw results in S3
        ↓
    transform into structured tables
        ↓
[4] Aggregate across commits
        ↓
[5] Register schema (Glue)
        ↓
[6] Query with Athena
        ↓
[7] Visualize + report (QuickSight / Python)
```

---

# ⚙️ 4. System components (clean architecture)

## 🧩 Component 1 — Ingestion Layer

### What it does

* pulls commit history
* selects commits

### Tools

* Python
* Git CLI / GitPython

---

## 🧩 Component 2 — Processing Layer

### What it does

For each commit:

* checkout repo state
* parse Python files
* run AST analysis
* compute metrics

### Tools

* Python `ast`
* your existing analyzers
* pandas

---

## 🧩 Component 3 — Storage Layer (DATA LAKE)

### What it does

Stores:

* raw outputs
* processed datasets

### Tool

* **S3**

### Structure

```text
s3://bucket/
  raw/
    repo/
      commit_hash/
        raw_metrics.json
  processed/
    class_metrics/
    method_metrics/
    commit_summary/
```

---

## 🧩 Component 4 — Transformation Layer (ETL)

### What it does

* converts raw JSON → structured tables

### Tools

* Python (MVP)
* OR Glue ETL (optional upgrade)

---

## 🧩 Component 5 — Catalog Layer

### What it does

* defines schema for data in S3

### Tools

* Glue Data Catalog
* Glue Crawler

---

## 🧩 Component 6 — Query Layer

### What it does

* run SQL on S3 data

### Tool

* Athena

---

## 🧩 Component 7 — Orchestration Layer

### What it does

* controls execution flow

### Tool

* Step Functions

---

## 🧩 Component 8 — Compute Units

### What it does

* executes processing tasks

### Tool

* Lambda (for bounded tasks)

---

## 🧩 Component 9 — Reporting Layer

### What it does

* visualizes + communicates insights

### Tools

* QuickSight OR Plotly
* Markdown reports

---

# 🔥 5. Where EACH AWS tool fits (no confusion)

## S3

👉 stores ALL data

* raw commit outputs
* processed tables

---

## Lambda

👉 runs **small units of work**

Examples:

* process one commit
* parse metrics
* write results

---

## Step Functions

👉 controls the pipeline

```text
Start
 → get commits
 → process commit batch
 → transform data
 → update tables
 → finish
```

---

## Glue Crawler

👉 scans S3 and detects schema

---

## Glue Data Catalog

👉 stores table definitions

---

## Athena

👉 SQL queries on your data

---

## QuickSight

👉 dashboard

---

# 📊 6. Data model (VERY important for agents)

## Table 1 — commits

```text
commit_hash
timestamp
author
message
files_changed
insertions
deletions
```

---

## Table 2 — class_metrics

```text
commit_hash
class_name
wmc
lcom
fanin
fanout
cbo
rfc
```

---

## Table 3 — method_metrics

```text
commit_hash
class_name
method_name
cc
loc
lloc
parameters
fanin
fanout
```

---

## Table 4 — commit_summary

```text
commit_hash
total_classes
total_methods
avg_wmc
avg_lcom
max_cc
total_loc
```

---

# 🧠 7. Key analytics the system produces

This is what makes the project strong.

## Trends

* complexity over time
* LOC growth
* coupling evolution

## Hotspots

* high complexity + high churn
* risky classes

## Spikes

* commits that caused large changes

## Risk insights

* deteriorating maintainability
* unstable modules

---

# 📈 8. ETL logic (simplified)

## Extract

* git commits
* AST metrics

## Transform

* normalize data
* compute summaries

## Load

* write to S3

---

# 🧱 9. Real execution logic (VERY clear)

## Step Functions flow

```text
1. Get commit list
2. For each commit:
    → Lambda: checkout + analyze
    → Lambda: parse + store raw
3. Lambda: normalize datasets
4. Glue Crawler: update schema
5. Athena queries ready
6. Reporting step
```

---

# 🧩 10. What YOU actually need to build

## MUST BUILD

* commit extractor
* commit processor
* AST metric engine (you already have this)
* data normalization
* S3 storage integration
* basic reporting

---

## SHOULD BUILD

* Step Functions orchestration
* Glue crawler setup
* Athena queries

---

## OPTIONAL

* QuickSight dashboard
* Lambda full integration

---

# 📦 11. Folder structure (for agent use)

```text
commitscope/
  src/
    main.py
    config.py
    git/
    analysis/
    pipeline/
    storage/
  data/
  outputs/
  infrastructure/
  docs/
```

---

# 📄 12. README-level explanation

You should describe it like this:

> CommitScope is a data-driven analytics pipeline that transforms Git commit history into structured datasets describing code quality over time. The system performs per-commit static analysis using Python AST parsing, stores raw and processed outputs in an S3-backed data lake, and enables querying and reporting through AWS services such as Athena and QuickSight.

---

# 🧠 13. How Agentic AI will use this

Now your agents can:

* generate modules:

  * git extractor
  * AST analyzers (reuse your code)
  * S3 upload logic
  * normalization scripts

* generate infra:

  * Step Functions JSON
  * Lambda handlers
  * Glue crawler config

* generate docs:

  * PRD
  * README
  * architecture diagram

---

# 🚨 14. Most important mindset shift

Do NOT think:

> “Where do I force AWS in?”

Think:

> “Where does each responsibility live in the pipeline?”

Then AWS naturally maps:

* storage → S3
* compute → Lambda
* orchestration → Step Functions
* schema → Glue
* querying → Athena

---

# ✅ Final clarity

Your project is:

👉 a **data pipeline over git history**

NOT:

* just static analysis
* just AWS infra
* just a dashboard

It is the combination.

---