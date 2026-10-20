# Publishing plugin versions

When the owner authorizes publishing an updated plugin version:

- Keep `manifest.json` and the Codex client version in `plugin/core.py` aligned.
- Add a dated entry to `CHANGELOG.md` describing the user-visible changes.
- Complete the checks in `CONTRIBUTING.md` and `docs/RELEASING.md` before publishing.
- Create an annotated `vX.Y.Z` tag on the validated commit and publish a GitHub
  Release using that version's changelog entry as its release notes. This is the
  owner's default release convention, even though the marketplace does not
  require tags.
- Never move or replace a published version tag. Make a new version for fixes.

Follow this convention for future releases of this plugin. Ordinary local edits
do not require publishing a release.
