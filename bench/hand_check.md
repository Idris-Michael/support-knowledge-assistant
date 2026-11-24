# Hand check of the answers

Run of 24 November 2026: `LLM_MODE=claude-cli`, grader Claude Haiku 5.5, writer Claude Sonnet 5.5,
retrieval `vector`. Full text of every answer: [`answers.json`](answers.json).

**Checked by Claude**, reading each answer against the sections it cites and the PostgreSQL 18 docs.
The checker is the same model family as the writer, so this is not an independent check; a person
reviewed a random sample of ten questions as well ([`spot_check.md`](spot_check.md)).

## Answered (47)

| Result | Count | Questions |
|---|---|---|
| Correct and complete | 40 | the rest |
| Correct but incomplete, and says what is missing | 7 | Q08, Q22, Q25, Q28, Q36, Q38, Q42 |
| Contains a wrong statement | 0 | |

What the seven leave out, and why:

| | Missing | Cause |
|---|---|---|
| Q08 | How `pg_restore --jobs` works | The pg_restore options section was not retrieved; the answer says the sources do not cover it |
| Q22 | Restore commands for point-in-time recovery | Only the timelines section was retrieved |
| Q25 | Upgrading through logical replication | That section was ranked below the top five |
| Q28 | The size functions (`pg_relation_size` and others) | Not in the corpus: they are in the functions chapter, which is outside the pages used |
| Q36 | The `reject` method | Further down a 23,000-character section than the chunk that was retrieved |
| Q38 | Conflict types other than `insert_exists` | Only that subsection was retrieved |
| Q42 | That asynchronous commit cannot corrupt data | The sentence is in the section's second chunk; retrieval keeps one chunk per section (the same cause as Q03) |

Q60 ("walk me through a manual failover", asked as support) was labelled `refuse` because the
answer is in an SRE runbook the support role cannot read. The assistant answered from the public
failover docs instead, correctly, with no runbook content. It counts as a miss against the label;
the label was not changed after the run.

## Refused but answerable (4)

| | Why | Where it went wrong |
|---|---|---|
| Q01 | "too many clients already" | The exact error text is only in a support-only note, which a customer cannot search; the public docs name it only as `too_many_connections` in the error-code table, and no mode retrieved the `max_connections` section |
| Q03 | SQLSTATE 40P01 | Retrieval found the error-codes *section* (it counts as a hit), but the section is one table split into many chunks and the chunk kept was not the one with 40P01 |
| Q31 | Progress of a long import | The COPY progress view was not retrieved |
| Q44 | Why a base backup taken while files change is consistent | The grader kept three sources; the writer declined. Not investigated further |

None of the four guessed: each refused with the standard wording rather than answering without a source.
