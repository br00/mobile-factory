# Design

How mobile-factory works and why. The README covers how to use it.

## The problem

A product with a native iOS app and a native Android app pays for every
feature twice: two implementations, two reviews, two releases. They drift,
too: one platform gets an empty state the other forgot, or a different
rounding rule. The factory goes after both problems. It files the feature
once, builds both sides in parallel against one contract, and checks that
the two match before anyone merges.

## Principles

1. **Scripts decide facts, agents make judgments.** Whether the build passes,
   whether a file says READY, whether a move is legal: `bin/mf`. Whether the
   feature is worth building, what the spec says, whether the code is good:
   agents.
2. **One decider.** The orchestrator doesn't pick the next stage. It reports
   events (`mf after build 004 ios`) and asks `mf next 004`. That keeps the
   pipeline in tested code instead of a prompt.
3. **State is files.** `jobs/<id>/job.json` plus one file per agent per round.
   A dead session resumes from them.
4. **One agent, one file, one line.** The orchestrator never reads agents'
   files, so its context lasts a long run.
5. **Parity is a contract, not a hope.** One spec, one set of accessibility
   ids, one acceptance flow for both apps.

## Topology

```
my-product-factory/          this repo: code, config, state, and (often) the issue backlog
  bin/mf  mf/                the CLI
  .claude/skills/mf/         the orchestrator
  .claude/agents/            12 agents
  targets/<t>/fast.sh        each app's checks, run by the gate
  jobs/<id>/                 state (gitignored)
  .worktrees/<id>/<t>/       a worktree of app <t> on branch factory/<id>
../app-ios                   your clones; the factory adds worktrees to them and never touches their checkouts
../app-android
```

A job opens at most one PR per app. Each PR says `Refs <issues repo>#<n>`;
the factory closes the issue itself once every PR has merged, because a PR
in one repo can't close an issue in another.

## Stages

```
job:    intake ─► spec ─► build ─► review ─► approve ─► merging ─► merged
          │                 │        │          │          │
          ▼                 ▼        ▼          ▼          ▼
     needs-info ◄──►    needs-human (approved and waiting for a go, a decision, blocked, rounds used up, merge stopped)
          │                           │
          ▼                           ▼
       rejected                   build (feedback) | merging (go) | rejected

track (per platform, inside build):
        waiting ─► build ─► gate ─► passed ─► merged
                     ▲        │
                     └─ fail ─┘ (up to max_gate_attempts per round, then blocked)
```

Both tables live in `mf/rules.py` (`JOB_MOVES`, `TRACK_MOVES`). The job
leaves `build` when no track is still building or gating: for `review` if
every track passed, for `needs-human` if any is blocked.

**Rounds.** A round is build → gate → review. Review CHANGES starts round
N+1 and rebuilds only the platforms named in `TARGETS`; a passed platform
keeps its verdict. After `max_rounds` the job asks a human. Feedback from the
operator starts a new round with a fresh budget.

**Staleness.** Every event checks that its file was written after the stage
or track began (by mtime), and build and decision files must carry the
current `ROUND: N`. A builder that rewrites `build-ios.md` without a new
commit after a failed gate is refused. That stops loops where nothing
actually changed.

## Agents

| agent | model | writes | notes |
|---|---|---|---|
| surveyor | opus | `profiles/<t>.md`, `profiles/<t>.suggestions.md` | run by `/mf survey`, not per job |
| surveyor-parity | opus | `profiles/parity.md`, `profiles/parity.suggestions.md` | after both profiles exist |
| intake | opus | `intake.md` | no shell; picks PLATFORMS, RISK, SURFACES |
| spec-writer | opus | `spec.md`, `flow.yaml` | platform-neutral behaviour + per-platform notes |
| builder-ios, builder-android | opus | code, `build-<t>.md` | resumed across rounds via SendMessage |
| reviewer-code-ios, -code-android | by risk | `review-code-<t>.md` | one per platform in the job |
| reviewer-parity | sonnet | `review-parity.md` | when the job has both platforms |
| reviewer-ui, -a11y | haiku, sonnet | | surface `ui` |
| reviewer-security | opus | | surface `security` |
| reviewer-store | sonnet | | surface `store` |
| approver | opus | `decision.md` | APPROVE or ESCALATE, plus "Try it" steps |

The reviewers share `docs/reviewing.md`, which covers how to work and the
file format. Each agent file covers only what that reviewer looks for.

**Write scopes.** Each agent has a PreToolUse hook, `bin/mf hook guard
<role>`, that blocks Edit and Write outside its scope (`WRITE_SCOPES` in
`mf/cli.py`). Builders may write in worktrees and their build file, but not
`flow.yaml`, the config, the checks, or your main clones. Bash isn't fenced;
the gate and the reviewers are the backstop.

## The contract

`spec.md` defines behaviour, acceptance criteria, an **accessibility id
table** and a **string key table**, plus short iOS and Android notes saying
where the change goes and which components to reuse. `flow.yaml` is a Maestro
flow that selects elements only by those ids. iOS sets them with
`.accessibilityIdentifier`, and Android with `Modifier.testTag` plus
`testTagsAsResourceId` at the root. The same file runs against both apps.

`flow.yaml` lives in the job folder, outside both branches, so builders can't
weaken their own acceptance test. Today builders run it themselves when
Maestro is installed. The full gate (roadmap) will run it as part of the
verdict.

## Survey

Without a survey, every agent works out "how does this app do things?" from
scratch on every job. That costs tokens and gives inconsistent answers.
`/mf survey` does that work once and writes it down:

```
bin/mf survey          detached worktrees of each base branch; prints spawn actions
  surveyor ×N          profiles/<t>.md (house rules + build facts) and profiles/<t>.suggestions.md
  surveyor-parity      profiles/parity.md (feature map, differences, shared vocabulary)
                       and profiles/parity.suggestions.md
bin/mf survey finish   validates, copies build facts into mf.config.json,
                       files suggestions as `mf:suggested` issues, removes the worktrees
```

- **Profiles are documents for people too.** They're plain markdown in
  `profiles/`, and the operator is expected to read and correct them. `brief()`
  adds their paths to every agent's prompt. Builders follow them, and
  reviewers treat breaking a house rule as a CHANGES finding. Builders can't
  edit them (the `surveyor` write scope is `profiles/*.md`).
- **Build facts** (`SCHEME`, `PROJECT`, `WORKSPACE`, `GRADLE_TASKS`) are
  header lines in the profile. The simulator isn't one: names are
  machine-specific and often ambiguous, so `bin/mf simulator` picks one on
  every run. `finish` copies any that
  aren't `none` into `targets.<t>.env`, and prints each change.
- **Suggestions are proposals, not work.** They're filed under a separate
  label and never enter the queue. Adding the queue label is the human
  decision that turns one into a job. A re-survey skips titles that are
  already open.
- `profiles/` is gitignored in the template, like `mf.config.json`. To share
  house rules with your team, remove it from `.gitignore` in your fork.

## Gate

`bin/mf gate <job> <target>` runs `targets/<t>/fast.sh` from the factory
repo, with the worktree as the working directory and `targets.<t>.env`
exported. It also fails the branch if it modified or deleted a file matching
`protected_paths`. The verdict and the last 60 lines of output go to
`round-N/gate-<t>-<attempt>.md`, with the full log beside it. The job lock is
released while the checks run, so the other platform and other jobs keep
moving.

Each job and platform gets a cache folder (`.cache/<job>/<t>`) for
DerivedData and Gradle's project cache, so concurrent builds don't share
mutable state. Gradle's global build cache stays shared, because it's safe
and fast.

## Approval and merge

The approver APPROVEs only what it would merge itself. It escalates
permissions, entitlements, new dependencies or SDKs, OS-version bumps,
payments, auth, push, analytics, deep links, data migrations, store items
flagged `HUMAN:`, and assumptions that are really product decisions.

With `auto_merge: false` (the default), APPROVE parks the job too. The
approver's "Try it" section goes on the issue, and you merge with
`/mf merge <n>`. Mobile changes reach users only through a store release and
can't be hot-fixed, so a human go is the sensible default.

`bin/mf merge` is a paired merge:

1. For every unmerged track: merge `origin/<base>` into the branch, run the
   checks again, push. Any conflict or failure parks the job with nothing
   merged.
2. Merge the PRs in `merge_order`. If a later one fails, the job parks with
   a note naming the app that's ahead. A retry merges only what's left.

## Guardrails

- The queue label is the trust boundary: only labeled issues run.
- Issue text reaches agents only as quoted data in `issue.md`, with comments
  only from the author and the operator.
- Agents push only `factory/<job>` branches. Only `bin/mf merge` merges. The
  factory never uploads to App Store Connect or the Play Console.

## Next

- **New-app mode**: from a written brief, create both repos with projects
  agents can edit safely (XcodeGen or Tuist, Gradle with a version catalog),
  shared design tokens, CI and passing checks; write the first profiles from
  that scaffold; then hand over to the normal pipeline.
- **Device pool** (`bin/mf device lease|release`): clone a base simulator per
  job with `simctl clone`; run read-only emulator instances on separate
  ports. Leases are recorded per job and released on every park or finish.
  This is what lets `concurrency` go above 1.
- **Full gate**: build and install on the leased device, then
  `maestro test flow.yaml`, keeping its screenshots per round for the
  reviewers and the dashboard.
- **Preview builds**: upload each approved job's apps to Firebase App
  Distribution (or TestFlight / Play internal testing) and link them on the
  issue, so "Try it" is one tap.
- **Dashboard** and **cost per job**.
- **KMP `shared` target**: a third target with a `consumers` edge. It builds
  and gates first, publishes locally (mavenLocal, a local XCFramework
  package), and merges first. Tracks are already per target, so the state
  machine doesn't change.
