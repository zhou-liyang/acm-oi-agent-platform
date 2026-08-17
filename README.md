# ACM/OI Verifier Agent

An evidence-driven verification pipeline for ACM/OI problem packages.

The project is not intended to treat an LLM as an answer key. Its purpose is to combine deterministic package checks, independent solver evidence, local judge replay, cross-provider disagreement analysis, and bounded strong-model adjudication into an auditable verification workflow.

## Why this project exists

Problem setting has several failure modes that are difficult to catch with ordinary sample testing alone:

- statement / metadata / test-package inconsistencies;
- incorrect expected outputs;
- weak or incomplete standard solutions;
- hidden boundary cases that a single solver misses;
- false confidence caused by several correlated model attempts making the same mistake.

The verifier therefore separates **evidence generation** from **final judgment**. Official `.out` files are not automatically trusted, and model agreement is not automatically treated as ground truth.

## Verification pipeline

```text
Problem package
    |
    v
[Package Check] deterministic package checks
    |
    +-- mechanical failure ----------------------> PACKAGE_FAIL
    |
    v
[Solve Check] two independent whole-problem solves
     DeepSeek V4 Flash / non-thinking
     Qwen 3.7 Flash / non-thinking
    |
    +-- both candidates AC ----------------------> TESTS_CORROBORATED
    |
    v
[Case Compare] run both candidates case by case
     compare candidate outputs case by case
    |
    +-- no substantive case disagreement --------> INCONCLUSIVE
    |
    v
[Case Review] two strong independent case reviews
     DeepSeek V4 Pro / low reasoning
     Qwen 3.7 Plus / bounded low thinking
    |
    v
Four-opinion case decision
    3:1 / 4:0 supports expected output ----------> TESTS_SUPPORTED_AFTER_ADJUDICATION
    3:1 / 4:0 contradicts expected output -------> REVIEW_REQUIRED
    2:2 / incomplete evidence -------------------> INCONCLUSIVE / TOOL_ERROR
```

The Agent never edits expected-output files automatically.

## Core design rules

1. Deterministic checks are preferred whenever they can answer the question.
2. DeepSeek and Qwen provide independent first-pass evidence; same-provider resampling is not used as a voting quorum.
3. A non-AC model candidate is evidence of solver uncertainty, not proof that the package is wrong.
4. Stronger and more expensive models are called only for case-level substantive disagreement.
5. The strong models receive only the statement and one concrete input for the disputed case; they do not see the official output, candidate source code, previous votes, or test purpose.
6. A 3:1 or 4:0 four-opinion majority determines the evidence direction. A 2:2 split stays inconclusive.
7. Even a strong majority against an existing `.out` produces `REVIEW_REQUIRED`; the Agent does not mutate problem data automatically.

## Repository structure

### Model routing

- `Code/model_providers.py`
  - Provider definitions and API-key / base-URL configuration.
- `Code/model_router.py`
  - Centralized initial and adjudication model policy.
- `Code/model_client.py`
  - OpenAI-compatible provider client for DeepSeek and Qwen.
  - Handles timeouts, retries, token usage, cache statistics, and provider-specific thinking-mode configuration.
- `Code/model_routing_test.py`
  - Prints the routing snapshot and key presence without an API call.
  - `--live` performs one tiny non-thinking connectivity request to each initial provider.

### Solver

- `Code/solve_once.py`
  - Performs one independent whole-problem solve and locally judges the generated C++17 program.
- `Code/solve_agent.py`
  - Earlier solver-oriented orchestration retained as a lower-level capability.

The Solver is a verifier component, not the final product.

### Judge

The project uses a local deterministic C++ compile / run / compare toolchain. Generated candidates are always evaluated locally rather than accepted from model text alone.

### Verifier

- `Code/package_check.py`
  - Deterministic package-level checks.
- `Code/solve_check.py`
  - Runs exactly one independent whole-problem candidate from DeepSeek and one from Qwen.
  - No repair feedback and no access to expected outputs during generation.
- `Code/case_compare.py`
  - Replays both candidates against every local case and builds a deterministic disagreement matrix.
- `Code/case_review.py`
  - Strong per-case review used only after a substantive disagreement is found.
- `Code/verifier_agent.py`
  - Unified verifier entry point and final evidence-state aggregation.

## Model policy

Initial evidence:

- DeepSeek: `deepseek-v4-flash`, thinking disabled, `max_tokens=3072`;
- Qwen: `qwen3.7-flash`, thinking disabled, `max_tokens=3072`.

Escalation evidence:

- DeepSeek: `deepseek-v4-pro`, low reasoning, `max_tokens=4096`;
- Qwen: `qwen3.7-plus`, bounded low thinking, `max_tokens=4096`, `thinking_budget=512`.

Strong review models return raw stdout directly rather than wrapping answers in JSON. This avoids schema drift and removes explanation-token overhead during adjudication.

The policy is centralized in `Code/model_router.py` so model changes do not need to be duplicated across verifier stages.

## Installation

Requirements:

- Python 3.10 or later;
- a C++17 compiler available as `g++`.

Create a virtual environment and install the Python dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and provide your own API keys:

```env
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
```

Optional provider endpoint overrides are also supported:

```env
DEEPSEEK_BASE_URL=https://api.deepseek.com
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Never commit the real `.env` file.

## Quick check

No API calls:

```powershell
.\.venv\Scripts\python.exe Code\verifier_agent.py --check
```

Routing-only check:

```powershell
.\.venv\Scripts\python.exe Code\model_routing_test.py
```

Tiny live connectivity check after both keys are configured:

```powershell
.\.venv\Scripts\python.exe Code\model_routing_test.py --live
```

## Run one verification

The repository includes `Problems/sum` as a minimal public problem package for reproducing the verifier workflow.

```powershell
.\.venv\Scripts\python.exe Code\verifier_agent.py `
    Problems `
    --names sum `
    --output Build\VerifierRun
```

This command makes live API calls to both configured providers. The output directory keeps stage reports, candidate sources, logs, usage information, disagreement evidence, and the final `summary.json`.

## Final states

- `PACKAGE_FAIL` — deterministic package checks failed;
- `TESTS_CORROBORATED` — both initial providers independently produced AC candidates;
- `TESTS_SUPPORTED_AFTER_ADJUDICATION` — every escalated case reached a 3:1 or 4:0 majority supporting the existing expected output;
- `REVIEW_REQUIRED` — at least one escalated case reached a 3:1 or 4:0 majority contradicting the existing expected output;
- `INCONCLUSIVE` — available evidence is insufficient or remains split;
- `TOOL_ERROR` — a required tool / API stage failed;
- `BLOCKED` — required local prerequisites are missing.

## Problem pools

- `Problems/sum` is a minimal public example package for reproducing the verifier workflow.
- `Problems/BenchmarkV3` is the controlled regression set used for policy and code comparisons.
- `Problems/Private` is a hidden local validation pool and is not intended to be published as part of the repository.

The automated workflow currently assumes the selected input set is suitable for ordinary text-based judging. The workflow deliberately does not try to guess and silently exclude image-dependent, special-judge, or interactive problems from names or package heuristics.

## Current scope

The current release focuses on making the complete verifier pipeline small, reproducible, cost-bounded, and explainable. Expanding to harder problem classes, richer special-judge support, or more providers is deliberately deferred until this baseline is stable.
