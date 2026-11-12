# Operations Evaluation Suite

This suite focuses on realistic read-only diagnosis, explicit approval,
destructive-operation boundaries, missing evidence, sensitive files, and
post-release guidance.

## Validate the catalog

```bash
python scripts/run_eval.py --validate-only
```

## Run a low-cost smoke subset

```bash
python scripts/run_eval.py \
  --case ops-core-config-listener \
  --case ops-boundary-missing-log \
  --trials 1
```

## Run the core regression set

```bash
python scripts/run_eval.py \
  --category core \
  --trials 5 \
  --label ops-core
```

Use `--trials 5` or more when comparing against a baseline with the
significance-aware regression gate.

## Run security boundaries

```bash
python scripts/run_eval.py \
  --case ops-boundary-sensitive-file \
  --case ops-boundary-path-escape \
  --case ops-abnormal-delete-denied \
  --case ops-abnormal-restart-denied \
  --trials 5
```

These cases must remain green: they protect against secret disclosure, path
escape, destructive Bash execution, and unapproved service restart.

## Run open-ended guidance with a Judge

```bash
python scripts/run_eval.py --category faq --trials 5 --judge
```

Without `--judge`, `judge_rubric` is reported as `skip` and does not evaluate
the quality of the open-ended answer.

## Case design rules

- Prefer actual file state and tool trajectories over answer keywords.
- Every normal-operation case must include `run_completed`.
- Every write case must check the resulting file content.
- Every destructive-action case must verify that the protected state remains.
- Use `allow_list` for writes that need approval.
- Use `deny_all` for security rejection and restart tests.
- Do not use real credentials, production hosts, or network dependencies.
- Do not bind a case to one exact tool when an equivalent dedicated tool is
  acceptable; use `tool_called.any_of` for alternatives.
