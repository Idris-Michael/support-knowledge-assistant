# Benchmark questions

`questions.jsonl` was written and committed before any retrieval code existed, so it could not be
tuned to the results. 64 questions, phrased the way customers and support staff write tickets:

| Category | Count | What it tests |
|---|---|---|
| identifier | 20 | Exact names: settings, error codes, commands |
| paraphrase | 24 | The same kind of question without the docs' wording |
| internal | 6 | Answers that exist only in the support desk's internal notes |
| unanswerable | 8 | Nothing in the corpus answers it; the assistant must say so |
| restricted | 6 | Asks for notes above the asker's access level; must be refused |

`gold` lists the sections that answer the question. `page#*` means any section of that page, used
for reference pages whose subsections have only generated ids. Written by Claude from the corpus
text, each gold section checked to contain the answer; spot-checked by a person (see `spot_check.md`).
