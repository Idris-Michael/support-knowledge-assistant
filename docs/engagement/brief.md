# Engagement brief

> **The customer is fictional.** "Larkspur Data" is an invented UK managed-PostgreSQL host, used to
> frame the work the way a solutions engagement would be framed. The documentation is the real
> PostgreSQL 18 manual; the internal notes are written for this project. The code, tests and
> measurements are real.

## The problem
Larkspur's support desk answers a steady stream of tickets that the PostgreSQL manual already
answers ("why doesn't DELETE free disk space?", "what does 40P01 mean?") plus questions only the
desk's own notes answer (plan limits, the pooler port, restore rules). New agents take weeks to learn
where things are. A pasted answer from a general chatbot is fast but sometimes invents a default or
a setting, and nobody can tell which sentence came from where.

They want an assistant the desk can trust, and later one customers can use in the portal, without
customers ever seeing the internal notes.

## Stakeholders
| Role | Cares about |
|---|---|
| Head of support (sponsor) | Faster first replies without wrong answers going to customers |
| Support agents (users) | An answer they can check in seconds: every sentence sourced |
| SRE lead | Runbooks and incident reviews never reach support staff or customers |
| Information security / DPO | Ticket text contains personal data; it must not be stored or sent on |
| Whoever maintains it | Something they can measure, run and change |

## Success criteria (agreed up front)
1. Every factual sentence carries a citation to a section the reader can open.
2. When the documents do not answer the question, it says so instead of guessing.
3. No one receives a note above their access level, however the question is phrased.
4. Personal data in a question is removed before it is searched, sent to a model or logged.
5. Retrieval quality is measured on a fixed question set, so changes can be compared.

## Out of scope for the pilot
Replying to customers directly, writing to the ticketing system, learning from agents' edits, and
any document set beyond the PostgreSQL manual and the desk's notes.
