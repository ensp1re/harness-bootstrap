# Discovery: from an idea to a project definition

Read this when the product is not defined yet: an empty repository, a request that is only an idea, or a change that breaks an earlier decision or assumption. The output is `docs/PROJECT.md` (always) and `docs/RESEARCH.md` (tier 1 and above), from `assets/templates/`.

## 1. Choose the tier

Use the highest tier whose trigger matches, and write the tier and trigger at the top of PROJECT.md. Budgets are upper limits; never extend one silently.

| Tier | Trigger (any one) | Budget |
|---|---|---|
| 0 Confirm | The request or existing docs already name the users, the behavior, the interface, and a checkable result | no searches |
| 1 Scan | Known kind of product, used by the requester or their own team; no other people's data, no money, no physical risk | 5 searches, 8 pages |
| 2 Map | Outside users; two or more roles; content posted by users; personal data; meeting in person; or you cannot name 3 alternatives | 15 searches, 25 pages, 2 rounds |
| 3 Deep | Money moves; health, children, legal or safety domain; regulator approval; or a core assumption was proven wrong | 40 searches, 60 pages; up to 3 researchers on separate topics, one writer |

## 2. Investigate in this order

1. **Users and jobs.** Roles; for each main role a job story ("when …, I want to …, so I can …"); what they do today and what goes wrong.
2. **Alternatives.** Products, open-source projects, workarounds (group chats, spreadsheets, doing nothing), and similar products that shut down, with the reason. Note what each lacks for the job.
3. **Domain language.** Terms, entities, relations, states, rules, exceptions. Every noun in a requirement is in the glossary, and code uses the same names.
4. **Constraints.** Integrations and data sources with their limits and prices, hosting, laws in the user's jurisdiction, safety.
5. **Assumptions that could end the idea.** "We believe that …" rows, ranked by impact and by how little evidence exists. The top three get a test with a pass threshold chosen before the test.
6. **Smallest useful product.** The least that completes the main job once for one group of users, and how to test its value before or during the first build.

Prefer primary sources: official docs, laws, pricing pages, repositories, the product itself. Every claim a decision relies on becomes a V- row with URL, published date, and checked date.

## 3. Stop

- **Decision test.** Before each search, name the requirement, decision, or architecture choice it could change. If there is none, skip it.
- **Saturation.** On one topic, after 5 pages, stop when 3 pages in a row add no new alternative, term, rule, constraint, or pain.
- **User-only facts.** If the answer depends on something only the user knows (city, budget, audience they can reach), write a Q- row and stop that branch.
- **Budget spent.** Unresolved items become A- or Q- rows. Skipped topics go under "Not researched".

## 4. Ask the user once

After the first broad round, ask at most 3 questions, in this priority: scope, then legal, privacy or safety, then user experience, then technical. Each question gives 2–4 options, marks one as recommended, and says what each option changes. Ask before researching only when the idea could mean two different products. Do not ask about the stack unless the user has a constraint: choose it and record it as an `agent default` decision.

If there is no answer, or you run unattended: a non-blocking question uses its default, recorded as a D- row. A blocking question becomes a task "Answer Q-n" that you `block` with the reason, and the tasks that need the answer list it in `--after`.

## 5. Turn findings into the definition

- **Scope.** First-release items are R- rows. Every exclusion cites the ID that justifies it.
- **Requirements.** One observable behavior each, with Given/When/Then acceptance using concrete values, the check that proves it (unit, e2e, or "manual: who"), and the IDs it is based on. Words like fast, easy, or useful need a number or an example.
- **Architecture.** Keep an existing stack. For a new project pick the most common, well-supported stack that meets the R- rows and constraints, and record it as a D- row naming the alternatives.
- **Tasks.** Each task carries `--ref` with its R- (or A-) IDs, and its acceptance lines come from those rows. A value test that needs no code (a manual pilot, a shared landing page) goes into the report and an A- row owned by the user, not into the queue, unless code tasks wait for its result.

## 6. Reopen

Reopen discovery when an A- row fails, the user changes a decision, implementation contradicts a V- row, or a legal or price fact is older than 6 months at release. Mark the row (`invalid`, or a new D- row that replaces the old one), `grep -rn` the ID in `docs/`, and update the affected R- rows and tasks as the harness block in AGENTS.md describes. Research only the changed topic, with one round of the original tier's budget.
