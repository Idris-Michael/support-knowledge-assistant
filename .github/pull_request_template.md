## What and why

<!-- One or two sentences. Link the issue or decision record if there is one. -->

## Risk checklist

- [ ] Touches retrieval, the adapters or the role map? Which test shows a customer still cannot receive a support or SRE section?
- [ ] Changes a prompt, a model or the retrieval mode? Re-ran `bench/retrieval.py` and `bench/answers.py` and updated `bench/results.json` and the README?
- [ ] Edits `bench/questions.jsonl`? Say why: gold labels are not changed to fit results.
- [ ] Could a question, answer or document text reach a log or the console unredacted or unescaped?
- [ ] Could it put a token or a secret into logs, errors, the repo or Terraform state?
- [ ] Docs updated: README results, runbook, security questionnaire, ADRs

## How it was tested

<!-- Commands run and what they showed. Say which runs used Claude and which used the offline model. -->
