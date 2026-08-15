# ACM/OI Agent Platform

Agent-based tooling platform for ACM/OI problem setting, validation, testing, and workflow automation.

## Goal

The long-term goal of this project is an ACM/OI problem verification agent.

The Solver is an important capability of the verifier, but it is not the final product. The verifier should combine deterministic checks, independent solving, judging, disagreement analysis, and adjudication instead of treating a single model answer as ground truth.

## Current Architecture

### Model

- `Code/model_client.py`
  - DeepSeek API client.
  - Handles model selection, timeout, retries, token usage, reasoning usage, and prompt-cache statistics.

- `Code/model_test.py`
  - Minimal model connectivity test.

- `Code/balance_client.py`
  - Reads API account balance for cost tracking.

### Solver

- `Code/solve_once.py`
  - Performs one independent solve from the problem statement.
  - Extracts a complete C++ source file and judges it against the local tests.

- `Code/repair_once.py`
  - Repairs a failed candidate using limited judge evidence and selected failed cases.

- `Code/solve_agent.py`
  - Orchestrates the current solver pipeline.
  - Coordinates initial solving, repair attempts, judging, final source selection, timing, and cost observation.

- `Code/batch_private.py`
  - Runs the Solver Agent over the private problem pool.

### Judge

- `Code/judge.py`
  - Compiles and judges one source against one input/output pair.

- `Code/judge_tests.py`
  - Runs a source against a complete test set.

- `Code/judge_problem.py`
  - Loads problem metadata and judges one source against one complete problem package.

- `Code/agent_tool.py`
  - Command-line tool entry used by Agent components.

### Benchmark

- `Code/benchmark_v3.py`
  - Runs the current Solver pipeline over benchmark problems.
  - Records AC stage, elapsed time, API calls, token usage, reasoning usage, and output artifacts.

- `Problems/BenchmarkV3`
  - Stable benchmark problem set used for regression and model-strategy comparison.

### Verifier

The current verifier implementation is still an evolving pipeline.

- `Code/verifier_v1.py`
  - Deterministic package-level validation.
  - Checks problem metadata, statement/test structure, and other static package properties.

- `Code/verifier_v2.py`
  - Performs multiple independent verification solves.
  - Uses deliberately varied independent-solving instructions and records judge results and model usage.

- `Code/verifier_v3.py`
  - Replays independent candidate programs against test cases.
  - Compares candidate behavior and detects output agreement/disagreement patterns for further investigation.

- `Code/case_oracle_v3_1.py`
  - Independent per-case adjudication tool.
  - Receives only the statement and one concrete input and attempts to derive the exact required stdout without seeing the official answer.

- `Code/verify_state.py`
  - Aggregates evidence from verifier stages and adjudication results.
  - Produces explicit final verification states such as:
    - `PACKAGE_FAIL`
    - `TESTS_CORROBORATED`
    - `TESTS_SUPPORTED_AFTER_ADJUDICATION`
    - `REVIEW_REQUIRED`
    - `INCONCLUSIVE`
    - `TOOL_ERROR`
    - `BLOCKED`

- `Code/verifier_agent.py`
  - Unified verifier orchestration entry point.
  - Runs deterministic V1 checks, Flash-none V2 independent solving, local V3 disagreement analysis, and Pro-high case adjudication only when shared disagreement exists.

## Problem Pools

### BenchmarkV3

`Problems/BenchmarkV3` is the controlled regression set.

Its purpose is to compare solver/verifier behavior across code revisions and model strategies.

### Private

`Problems/Private` contains hidden problems used to test whether the Agent generalizes beyond the benchmark set.

The current development scope focuses primarily on Bronze and Silver problems, with Gold used only where useful. Problems whose essential information depends on images rather than the supplied text are not part of the primary automated verification set at this stage.

## Verification Principles

1. Official test output is not assumed to be correct merely because it is official.
2. Model output is not assumed to be correct merely because several model attempts agree.
3. Independent solvers are evidence providers, not ground truth.
4. Judge disagreements should trigger investigation rather than automatic answer replacement.
5. Stronger and more expensive models should be used only when cheaper evidence is insufficient.
6. Deterministic checks should be preferred whenever a deterministic check can answer the question.
7. Verification results should preserve enough evidence to explain why a problem reached its final state.

## Current Development State

Completed or usable:

- DeepSeek model client and usage accounting.
- Local C++ compile/run/judge toolchain.
- Initial Solver Agent with repair stages.
- Private problem batch runner.
- Benchmark V3 runner.
- Static Verifier V1.
- Independent-solving Verifier V2.
- Differential evidence analysis in Verifier V3.
- Per-case Oracle V3.1.
- Verification-state aggregation.
- Unified Verifier Agent orchestration.

Validated smoke paths:

- Live short-circuit: `milk` reached `TESTS_CORROBORATED` on the first Flash-none attempt without entering V3 or adjudication.
- Real-problem escalation gate: `cut` remained `INCONCLUSIVE` without shared disagreement, and therefore did not trigger Pro-high adjudication.
- Deterministic orchestration tests cover supported adjudication, contradicted adjudication, and no-shared-disagreement gating without model API calls.

Next:

1. Expand regression coverage across the private and benchmark pools.
2. Improve verifier evidence reporting, failure classification, and cost accounting.
3. Continue tuning escalation policy before expanding problem difficulty.

## Repository Hygiene

- `Build` contains disposable generated artifacts and may be regenerated as needed.
- `Backup` contains only selected recovery assets.
- Temporary benchmark, compile-cache, and cleanup artifacts should not be committed.
- Historical experimental scripts should not remain in the main `Code` directory once superseded.
