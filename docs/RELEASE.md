# Release procedure

This repository is private. Treat a release as a reviewed source snapshot; never include personal data, credentials, or runtime state.

## Cut a release later

1. Set the intended release version in the root VERSION file, for example 1.0.0.
2. Add the user-visible changes to CHANGELOG.md under that version.
3. Run the repository test entry point: ./run-tests.sh. Then run ./chatbot-ctl.sh repair and confirm its smoke checks pass.
4. Review the complete diff and tracked file list. Do not stage data/, secrets.env, session files, tokens, keys, or other private runtime output; release files must contain no secrets.
5. Commit the reviewed release changes.
6. Create an annotated local tag matching VERSION: git tag -a vVERSION -m Release-vVERSION. Verify it with git show vVERSION. Publishing a tag is a separate, explicitly approved step.

The current development snapshot is 0.0.0-dev; this procedure does not publish tags.
