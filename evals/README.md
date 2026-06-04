# Evals

Lightweight regression checks for the LLM cover-letter pipeline.

Run dataset validation without LLM calls:

```bash
python -m app.evals.run --dry-run
```

Run the eval set:

```bash
python -m app.evals.run
```

Run one case while debugging prompt/scoring changes:

```bash
python -m app.evals.run --case-id prompt_engineer_good_001
```

Save a JSON report:

```bash
python -m app.evals.run --output evals/results/latest.json
```

Current baseline:

```text
Cases: 11
Passed: 11
Failed: 0
```

The eval runner checks deterministic quality gates:

- matcher score is inside the expected range;
- matcher decision matches the expected label;
- generated letter does not contain forbidden phrases;
- generated letter does not contain explicitly forbidden claims.
- matcher gaps do not contain explicitly forbidden synthetic gaps.
- matcher output does not contain unsupported phrases like "вероятно", "быстро освоит", "легко адаптируется".
