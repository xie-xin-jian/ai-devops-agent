# Evaluation Regression CI

The regression workflow compares two evaluation reports without committing
case data, answers, or API keys to the repository.

## Required artifacts

The calling workflow must upload two JSON reports before invoking the gate:

| Artifact name | Content |
|---|---|
| `evaluation-baseline` | Report produced by the accepted baseline version |
| `evaluation-candidate` | Report produced by the current commit |

Each artifact may contain one or more files. The gate compares the first
`.json` report it finds.

## Call the reusable workflow

```yaml
jobs:
  evaluation:
    runs-on: ubuntu-latest
    steps:
      # Run the Agent suite here, then upload the reports.
      - uses: actions/upload-artifact@v4
        with:
          name: evaluation-baseline
          path: eval/reports/baseline.json

      - uses: actions/upload-artifact@v4
        with:
          name: evaluation-candidate
          path: eval/reports/current.json

  regression-gate:
    needs: evaluation
    uses: ./.github/workflows/evaluation-regression.yml
    with:
      baseline_artifact: evaluation-baseline
      current_artifact: evaluation-candidate
      tolerance: "0"
      fail_on_missing: true
```

The reusable workflow fails when:

- any shared case has a lower pass rate than the baseline;
- `fail_on_missing` is enabled and a baseline case is absent;
- either artifact contains no JSON report.

New cases and lower cost or latency are reported but do not fail the gate.
