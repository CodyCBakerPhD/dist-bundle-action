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

      - uses: CodyCBakerPhD/dist-bundle-action@v1
        with:
          paths: data
```

The action outputs `content.tar.gz`, holding everything under the `data/` directory.

We strongly recommend to fetch or serve from the raw content GitHub CDN:
- `https://raw.githubusercontent.com/OWNER/REPOSITORY/dist/content.tar.gz`

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `paths` | yes | | Newline-separated files, directories or glob patterns, relative to the repository root. |
| `format` | no | `tar.gz` | `tar.gz` or `json.gz`. See [Formats](#formats). |
| `filename` | no | `content.` + format | Name of the bundle on the branch. |
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

## Notes

**It keeps only the latest bundle.**
Each run replaces the branch's one commit, so earlier bundles are not kept.
That is what keeps the branch from growing, and it makes the bundle a way to share current data rather than an archive.
For a citable, versioned snapshot, archive a release with a DOI service such as Zenodo instead.

**It pushes with the checkout's credentials.**
`actions/checkout` persists its token for later git commands, and this uses it to push.
The job therefore needs `contents: write`, and the checkout must keep the default `persist-credentials: true`.

**It commits as the repository's configured identity.**
Without one, the default is `github-actions[bot]`.
