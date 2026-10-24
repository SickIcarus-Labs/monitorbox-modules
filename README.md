# monitorbox-modules

Dependencies for [MonitorBox](https://github.com/SickIcarus-Labs/monitorbox): the built archives (the App and its modules) and the channel pointers that say which build each channel gets. No source code lives here, and nothing secret ever should. MonitorBox checks this repository for updates and checks every download against its recorded `sha256`.

MIT licence, see [LICENSE](LICENSE).

## How channels work

A channel is **one file** in `channels/`:

| File | Who moves it |
| --- | --- |
| `channels/dev.json` | CI, automatically, when the source repo's `main` builds |
| `channels/beta.json` | The **Promote channel** workflow, after you accept dev |
| `channels/stable.json` | The **Promote channel** workflow, after you accept beta |

Each file lists the exact App and module versions for that channel: version, download URL and `sha256`. An install on a channel downloads those files and checks each checksum. A `signature` field is reserved so signing can be added later without changing the format.

## Moving a channel

GitHub → Actions → **Promote channel** → Run workflow.

- **Promote:** source `dev`, target `beta` (or `beta` → `stable`). The one pointer file is copied in one commit. Nothing is rebuilt. Other directions are refused, including skipping beta.
- **Roll back:** source and target the same channel, and `ref` set to an earlier commit. That commit's pointer is restored.
- Every move is a commit, so the history is the audit trail and any move can be reverted.

## Checks

`python tools/pointer.py channels/*.json` validates the pointer files, and `python -m unittest discover -s tests` runs the tests. Both use only the Python standard library and finish in seconds. The `validate.yml` workflow runs them when a pointer or tool changes.

## Layout

```
channels/   the three pointer files
tools/      pointer.py (validate, promote, roll back), promote.py (command line)
tests/      unit tests, including a real promote against a throwaway git repo
.github/    validate.yml and promote.yml
```

Built archives are attached to GitHub Releases in this repo, not committed to git.

## Catalog

`catalog.json` lists every released version of the App and each module and which channels it has reached (`dev`, then `beta`, then `stable`). A new version enters as `dev`. **Promote channel** adds `beta` or `stable` to the versions it moves. The App's version picker offers only the versions that have reached the channel you follow: stable shows stable, beta shows beta and stable, dev shows all.
