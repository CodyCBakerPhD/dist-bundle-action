# dist-bundle-action

A general action for distributing single-file compressed content for a GitHub repository.

It compresses the files you name into one file and force-pushes that file, alone, to an orphan branch.
The branch only ever holds one commit, so it never grows, and anything can fetch the whole bundle in one request.

```yaml
name: Publish the dist bundle

on:
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * *"

jobs:
  Bundle:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v7

      - uses: CodyCBakerPhD/dist-bundle-action@v1
        with:
          paths: data
```

That publishes `content.tar.gz` holding everything under `data/` to the `dist` branch.
It is then served at the usual raw content URLs.

- `https://raw.githubusercontent.com/OWNER/REPOSITORY/dist/content.tar.gz`
- `https://cdn.jsdelivr.net/gh/OWNER/REPOSITORY@dist/content.tar.gz`

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `paths` | yes | | Newline-separated files, directories or glob patterns, relative to the repository root. |
| `format` | no | `tar.gz` | `tar.gz` or `json.gz`. See [Formats](#formats). |
| `filename` | no | `content.` + format | Name of the bundle on the branch. |
| `branch` | no | `dist` | Orphan branch the bundle is force-pushed to. |
| `commit-message` | no | `update dist bundle [skip ci]` | Message for the branch's commit. |
| `push` | no | `true` | Set to `false` to only build the bundle and report its `path`. |

A path that matches nothing fails the step.
That catches a typo rather than quietly publishing less than was asked for.
Nothing inside `.git` is ever bundled.

## Outputs

| Output | Description |
| --- | --- |
| `path` | Local path of the built bundle, for uploading as an artifact or a release asset as well. |
| `pushed` | `true` when a new commit was pushed. `false` when the branch already held this exact bundle. |
| `commit` | The commit pushed to the branch. Empty when nothing was pushed. |

## Formats

**`tar.gz`** archives the files as they are, under their paths relative to the repository root.

**`json.gz`** suits a repository of JSON files read by a browser or a script, which then needs no archive library.
It is one minified JSON object mapping each file's path to that file's parsed content.

```json
{"results/a.json":{"value":1},"results/b.json":{"value":2}}
```

A directory contributes only its `.json` files to it.
A file that is not valid JSON is skipped with a warning rather than failing the run.

## Behavior

**The checkout is left alone.**
The commit is assembled with git plumbing rather than by checking the branch out.
Your working tree, index and current branch are exactly as they were, so any step may follow this one.

**An unchanged bundle is not pushed again.**
The bundle is reproducible, since file times and owners are dropped from it.
When the branch already holds an identical file, nothing is pushed and `pushed` is `false`.

**It pushes with the checkout's credentials.**
`actions/checkout` persists its token for later git commands, and this uses it to push.
The job therefore needs `contents: write`, and the checkout must keep the default `persist-credentials: true`.

**It commits as the repository's configured identity.**
Without one, it commits as `github-actions[bot]`.

**The default commit message carries `[skip ci]`.**
That keeps a push to the branch from starting the repository's own workflows.

It runs on the runner's `python3`, using only the standard library, on Linux and macOS runners.
