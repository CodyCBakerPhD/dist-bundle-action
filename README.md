# Distributed bundle action

A general action for distributing single-file compressed content (`dist`) of a particular branch of a GitHub repository.

This ephemeral branch only ever holds one commit, so it never grows, and anything can fetch the whole bundle in one request.

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

      - uses: CodyCBakerPhD/dist-bundle-action@v2
        with:
          paths: data
```

The action outputs `content.tar.gz`, holding everything under the `data/` directory.

We strongly recommend to fetch or serve from the raw content GitHub CDN:
- `https://raw.githubusercontent.com/OWNER/REPOSITORY/dist/content.tar.gz`

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `paths` | yes | | Newline-separated files, directories or glob patterns, relative to `root`. |
| `root` | no | `.` | Directory the `paths` are relative to, and the root of what is published. It may be outside the repository, such as a directory under `runner.temp`. |
| `format` | no | `tar.gz` | `tar.gz`, `json.gz` or `files`. See [Formats](#formats). |
| `filename` | no | `content.` + format | Name of the bundle on the branch. Not used by `files`. |
| `branch` | no | `dist` | Orphan branch the bundle is force-pushed to. |
| `commit-message` | no | `update dist bundle [skip ci]` | Message for the branch's commit. |
| `push` | no | `true` | Set to `false` to only build the bundle and report its `path`. |

## Formats

**`tar.gz`** archives the files as they are, under their paths relative to the repository root.

**`json.gz`** suits a repository of JSON files read by a browser or a script, which then needs no archive library.
It is one minified JSON object mapping each file's path to that file's parsed content.

```json
{"results/a.json":{"value":1},"results/b.json":{"value":2}}
```

**`files`** publishes the files themselves rather than one bundle of them.
Each keeps its path relative to `root`, so a consumer fetches one file without downloading the rest.
It suits content already in the form its consumers read, such as files compressed one by one.
The branch still holds a single commit, and a file no longer named by `paths` leaves the branch with the next run.

```yaml
      - uses: CodyCBakerPhD/dist-bundle-action@v2
        with:
          root: ${{ runner.temp }}/publish
          paths: .
          format: files
```

Each file is then at `https://raw.githubusercontent.com/OWNER/REPOSITORY/dist/<path>`.

## Notes

**It pushes with the checkout's credentials.**
`actions/checkout` persists its token for later git commands, and this uses it to push.
The job therefore needs `contents: write`, and the checkout must keep the default `persist-credentials: true`.

**It commits as the repository's configured identity.**
Without one, the default is `github-actions[bot]`.
