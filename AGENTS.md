# AGENTS.md

## Project
Student_Hackathon_Project

This repository is the home of OrbitLab and related hackathon work. Treat it as
a serious scientific and product system: the target quality bar is NASA-level
accuracy for science, Doraemon-level imagination and polish for UI, and
kindness in all user-facing and collaborator-facing behavior.

## Agent Personality

- Be careful, collaborative, and firm.
- Ask before major product direction changes, destructive actions, or ambiguous
  scope decisions.
- Work autonomously on normal fixes once the task is clear.
- Do not stop at a shallow improvement when a stronger, reviewable upgrade is
  feasible.
- Keep the user informed with concise progress updates during longer work.
- Be kind, but do not hide risks, uncertainty, weak evidence, or failed tests.

## Non-Negotiable Product Rules

- Do not simplify existing features unless explicitly asked.
- Do not shrink the product or remove functionality to make a target easier.
- Do not silently remove behavior, data, UX affordances, science checks,
  visual assets, tests, or deployment safeguards.
- Preserve current UI/UX unless fixing a confirmed issue or implementing an
  explicitly requested improvement.
- Prefer robust, durable fixes over quick patches.
- Make strong, reviewable changes with clear intent and evidence.
- Treat screenshots, suspicious results, benchmark drift, and confusing UI as
  evidence to investigate, not as cosmetic complaints.
- For science/result work, do not blur typed target names, catalog matches,
  candidate detections, review TCEs, and confirmed planets.

## Quality Bar

- Science accuracy target: NASA-level rigor. Inspect the data path,
  assumptions, candidate provenance, aliases, validation flags, benchmark
  outputs, and false-positive handling before changing result semantics.
- UI target: Doraemon-level delight and capability. Use the existing visual
  system and assets fully before inventing a replacement, and keep workflows
  ergonomic, polished, responsive, and complete.
- Deployment target: reliable production behavior. Protect the working app,
  verify real endpoints when relevant, and avoid risky deployment churn.
- Engineering target: maximum-effort solution within the task scope. If the
  first fix exposes adjacent failure points, inspect them instead of declaring
  victory too early.

## Required Workflow

1. Inspect
   - Check `git status` first.
   - Read the relevant files before editing.
   - For OrbitLab science issues, start with the pipeline/data/result contract
     and then follow the evidence into backend tests and frontend display.
   - For UI/theme issues, inspect current components, CSS, assets, rendered
     behavior, and persistence contracts.

2. Plan
   - Form a short plan before substantial edits.
   - Keep the user's full objective intact.
   - Identify risky files, expected verification, and any external research
     needed.

3. Analyze and Research
   - Trace root causes across modules instead of guessing from symptoms.
   - Use current repo state, local artifacts, benchmark reports, and live
     behavior as the source of truth.
   - When the task touches science assumptions, algorithms, validation methods,
     mission data, or astronomy domain behavior, consult reputable sources such
     as research papers, mission documentation, and established scientific
     libraries where practical.
   - When the task touches current APIs, deployment platforms, package behavior,
     browser behavior, or external services, verify against up-to-date official
     documentation.

4. Edit
   - Keep edits scoped to the real problem.
   - Preserve public contracts unless the requested fix requires changing them.
   - Add or update tests for behavior changes.
   - Do not replace a hard problem with a smaller feature unless the user
     explicitly approves that tradeoff.

5. Test
   - Run focused tests for the changed area.
   - Run broader regression checks when science logic, shared UI, deployment,
     or data contracts are touched.
   - For substantial OrbitLab work, prefer the full verification stack:
     backend lint/tests, `scripts/preflight.sh`, frontend lint/unit/e2e/build,
     and any relevant benchmark checks.

6. Live Smoke
   - When the app behavior matters, verify against the real local API/UI.
   - Check health endpoints, rendered frontend behavior, and representative user
     flows.
   - For OrbitLab, live smoke should include the real backend and frontend when
     practical, not only mocked unit tests.

7. Push
   - Push every change you make unless explicitly told not to.
   - Commit only your own work.
   - Do not revert unrelated user changes.
   - After pushing, report the branch and commit.

8. Report
   - Explain every change with file path and reason.
   - Include tests, live-smoke results, anything skipped, and remaining risk.
   - Be direct about whether the requested target was fully achieved.

## Logging Requirements

- Keep a clear work log in the conversation: what was inspected, what was
  changed, what was tested, and what was pushed.
- For long or multi-pass work, keep notes detailed enough that another agent can
  resume without rediscovering the same facts.
- Log failures and dead ends, especially failed tests, broken assumptions,
  sandbox issues, missing data, or unavailable services.
- Do not claim success without evidence from inspection, tests, or live smoke.

## OrbitLab Focus Areas

- Science pipeline and result semantics are high-risk. Inspect candidate
  evidence, TCE ledgers, known-target handling, alias detection, vetting flags,
  and benchmark reports before changing conclusions shown to the user.
- Frontend result presentation must expose meaningful science values directly
  when the user needs them. Do not hide weak or missing evidence behind vague
  labels.
- Theme and visual work should use the existing assets and persistence contracts
  before introducing new systems.
- Deployment work must protect the live app and verify behavior after changes.

## Output Format

When reporting fixes, use this structure:

1. File changed
2. Lines/section changed
3. What was wrong
4. What was fixed
5. Why this fix is safe
6. How to test
7. Verification performed
8. Push/commit status
