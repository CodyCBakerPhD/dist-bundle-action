# Agent instructions

## What this repository is

A single composite GitHub Action, published on the Marketplace, that compresses repository content into one file and
force-pushes it alone to an orphan branch. The work is done by `dist_bundle.py`, which uses only the Python standard
library so that it runs on the runner's own `python3` with no setup step.

## Versioning

- The action is versioned by its own interface, the inputs and outputs in `action.yml`.
- `VERSION` holds the tag this tree is meant to be published under, and is the only place that tag is decided. Bump it
  in the same commit that rewrites the README's references. The tests read it rather than a literal, so a reference
  left on the previous tag fails before the commit lands.
- Release by publishing the draft that `Prepare release draft` keeps on every merge to `main`. Its tag name comes from
  `VERSION` and its target from that commit, so the tag is never typed. It prepares nothing when the tag already
  exists, since moving a published tag is a deliberate act rather than a release.
- Cut a new major tag when the inputs, outputs or requirements change incompatibly.
- The `action-versions-agree` pre-commit hook runs the tests that catch the README drifting from `VERSION`.

## Writing the action

- Never interpolate an input into a `run:` body. Pass it through `env:` so no value can be read as shell syntax. The
  tests reject an expression in any `run:` body.
- Keep `dist_bundle.py` to the standard library.
- Never check out or switch branches. Callers rely on their checkout being untouched.

## Code style

- Avoid excessive em-dashes, colons, and semicolons in written text such as documentation. Prefer
  breaking into separate, shorter sentences instead.
- Keep inline comments sparse. Only explain non-obvious "why", not "what" the code does.

## Tests

- Run `pytest` before pushing, and `pre-commit run --all-files`.
- Follow assertion style: actual on left, expected on right.
- Always mark AI-generated tests with the `ai_generated` pytest marker.
