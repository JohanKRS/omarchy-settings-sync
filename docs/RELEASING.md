# Release and marketplace preparation

Keep the release description centered on synchronizing configuration across
Omarchy installations using the user's own repository.

The owner's release convention is to publish every version with an annotated
`vX.Y.Z` tag and a GitHub Release whose notes come from its dated changelog entry.
Tags are optional for marketplace submission, but required by this repository's
release workflow. Never move an existing published tag; use a new version.

## Prepare a version

1. Keep the manifest version and Codex client information in sync. Update the
   changelog and agent compatibility notes with evidence from the tested build.
2. Run the portable checks in CONTRIBUTING.md, the Omarchy manifest validator,
   QML lint and the isolated graphical smoke test.
3. Check live shell open/hide/toggle, disable/re-enable, question indication,
   terminal access, theme behavior and reopening. Finish real tasks before
   updating or removing an installed copy.
4. Generate previews with `tools/capture_preview.py`. Inspect them for private
   information; the repository name and questions must be synthetic.
5. Scan the working tree and full Git history for credentials with a trusted
   secret scanner, such as Gitleaks. Review the Git author/committer identities,
   files, logs and screenshots that will become public. Do not put scan reports
   containing secret values into this repository.
6. Commit the reviewed tree. Run CI on the same commit that will be published.
   A local check is not marketplace approval or a security certification.

## Make the repository public

Review the complete prepared change before changing visibility. Publishing a
previously private repository exposes its reachable Git history as well as its
current files. Preserve the MIT license and the plugin's permanent ID.

After the owner authorizes publication:

- Merge the prepared change into the default branch and confirm CI passes.
- Change this plugin repository to public visibility; personal configuration
  repositories stay separate and keep their existing visibility.
- Enable GitHub private vulnerability reporting if available, and confirm the
  report link shown in SECURITY.md works.
- After CI passes for the exact commit, create and push its annotated `vX.Y.Z`
  tag. Create a GitHub Release with that version's `CHANGELOG.md` entry as the
  notes (use `gh release create --verify-tag --notes-file` with a prepared file).
  Mark the changelog entry with the actual release date before committing.
- Test installation from the public URL and updates through Omarchy's updater.

No automation in this repository changes visibility, publishes releases,
merges changes, or submits the plugin to the marketplace.

## Submit the plugin

Use the [official submission form](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml).
A prepared body is in [MARKETPLACE_SUBMISSION.md](MARKETPLACE_SUBMISSION.md).
Suggested title: `[Plugin]: Omarchy Settings Sync`. Category: `System`.
Tags: `ai`, `bar`, `system`.

The draft checkboxes remain unchecked until the owner confirms them and the
repository is public. Show the final title and body to the owner before creating
the issue. The marketplace requires the owner's explicit approval, a current
validation/scan and a maintainer decision before listing the exact commit.
Capabilities such as package installation can require manual review even when
no unsafe-pattern finding is present. Do not describe a local scan as an
approved marketplace review.

For later releases, use the marketplace's plugin verification form to request
publication of the new full commit SHA. Marketplace snapshot approval and the
current Git branch are separate: Omarchy's updater follows upstream HEAD.
