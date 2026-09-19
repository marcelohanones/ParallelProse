# Learning ladder — design doc (altitude levels)

Goal: replace Claude's guessing about "how deep should this answer go" with an explicit,
shared ladder of altitude levels, so progression is driven by the user's cues instead of
Claude's inference. This formalizes the gradient that grow mode, the 5-line summaries, and
the notebook intro staircase all already express informally.

## Draft ladder (to refine)

- **L0 — Contact.** A bridge only: one anchor to something the user already knows, or the
  user's own "testology:" analogy validated/relocated. No definition yet. Success = the user
  can say what the new thing is *like*.
- **L1 — Concept.** What it is and what it trades against. ~5 lines, no mechanics, no file
  names/signatures. This is the default opening altitude for any topic that appears new.
  Success = the user can say what it's *for* and when they'd reach for it.
- **L2 — Mechanics.** How it works: the moving parts, their relationships, worked example,
  real code anchors (files, line numbers). Success = the user can *use* it on their own case.
- **L3 — Precision.** Edge cases, exact semantics, boundary behavior, where the L0 analogies
  break. This is also where consolidation lives: flags paid, analogies retired. Success = the
  user can *defend/debug* it.

## Rules to pin down

- [ ] Ascent is always user-initiated ("down", "explain again", direct questions). Claude never
      bundles a level into the previous one.
- [ ] Map each cue to a ladder transition explicitly (e.g. "down" = +1 level on current thread;
      "zoom out" = back to L1 of the parent topic; "explain again" = same level, more concrete
      anchor; "consolidate" = jump to L3 closing pass).
- [ ] Entry rule per mode: default mode opens at L1 when topic appears new; grow mode opens at
      L0 and may not skip levels; free mode = no ladder constraint.
- [ ] Decide how Claude *signals* current level, if at all (probably not — the named check
      already scopes the step; explicit "we are at L2" labels may be ceremony. Revisit after
      trying).
- [ ] Decide inverted-check placement relative to the ladder (candidate: mandatory before any
      L1→L2 descent; optional elsewhere).
- [ ] Decide whether L3/consolidation is mandatory before "free" exits grow mode when flags are
      pending (current agreement: offer it, user decides).

## Open questions

- [ ] Does the ladder need a per-topic memory within a session (topic A at L2 while topic B is
      parked at L0)? Likely yes — "park" implies a parking lot; decide whether Claude should
      keep and show a small parked-topics list at consolidation time.
- [ ] Calibration data: after a few grow-mode sessions under the new memory, review which cues
      got used and which never did; prune the vocabulary that didn't earn its place (state cues
      stay regardless — they are load-bearing).

## Lifecycle of this file

This is a design doc, not memory and not a skill. Memory holds settled interaction rules; this
file still holds open decisions. Once the checkboxes above are resolved, fold the settled rules
into the "Learning protocol" section of the global `CLAUDE.md` (they extend it) and archive
this file.
