# Project instructions

## Committing

- **Always push after committing.** A local `git commit` never touches the
  remote, so the commit will not appear on the GitHub commit page
  (`github.com/Singularity1178/irojhasda/commits`) until it is pushed. Finish
  every commit task with `git push origin main` and confirm with
  `git branch -vv` that the branch no longer reads `ahead N`. If the user asks
  for a commit, they expect it visible on GitHub.
- Report a commit as done only once the push has succeeded. Saying "committed"
  after a local-only commit is what caused the confusion this note exists to
  prevent.
- Stage only the files the change actually touched. Use explicit paths in
  `git add` rather than `git add .` / `git commit -a`.
- `multi_single_screen_pet_ba_settings.json` is written by the app at runtime
  (saved window positions). It is usually dirty between runs and is not part of
  most changes — leave it out unless the change is about it.