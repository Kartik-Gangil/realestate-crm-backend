# Purge sensitive files from Git history

## Who and when

Only the repository owner runs this procedure. Coding agents must not rewrite history or
force-push. Run it only after all work is committed and pushed, and after open pull requests are
merged or closed. The force-push cannot be undone.

## What is affected

- Backend: `db.sqlite3` and `media/` on both GitHub branches: `main` and
  `codex-implementation/completing-half-implemented-phase`.
- Frontend: `.env` on `main`.

## Backup

Run `git clone --mirror <repo-url>` for each repository. The mirror backups still contain the
sensitive data, so keep them offline and delete them securely once cleanup is confirmed.

## Tool

Install `git-filter-repo` 2.47 or later, which supports `--sensitive-data-removal`:

```powershell
python -m pip install git-filter-repo
```

This is an owner-machine tool, not a project dependency.

## Rewrite in fresh clones

In a fresh clone of each repository, run the appropriate command:

```powershell
# Backend
git-filter-repo --sensitive-data-removal --invert-paths --path db.sqlite3 --path media

# Frontend
git-filter-repo --sensitive-data-removal --invert-paths --path .env
```

Keep the console output. It prints the `First Changed Commit(s)` that GitHub Support requires.

## Verify and count affected pull requests

These commands must print nothing for the affected paths:

```powershell
# Backend
git log --all --oneline -- db.sqlite3 media

# Frontend
git log --all --oneline -- .env
```

Count affected pull requests from each rewritten repository:

```powershell
(Select-String -Path .git\filter-repo\changed-refs -Pattern '^refs/pull/.*/head$').Count
```

## Push

Push the rewritten refs:

```powershell
git push --force --mirror origin
```

Only `refs/pull/*` refs may fail. If anything else fails, branch protection is enabled: switch it
off temporarily and push again.

## GitHub Support

For each repository, open a request in the GitHub Support portal with the owner/repository name,
the affected pull-request count, and the `First Changed Commit(s)` from the rewrite output. GitHub
will remove cached views and pull-request references and run garbage collection.

## Replace old clones

Every collaborator must delete the old clone and re-clone. A `git pull` followed by `git push` from
an old clone can upload the sensitive data again.

This includes the owner’s copies in `f:\projects\realestate_CRM\Backend` and
`f:\projects\realestate_CRM\Frontend`:

1. Rename the old folders and re-clone into the same paths.
2. Move the ignored local files across: `.env`, `db.sqlite3`, `Backend\media\`, `Backend\private_media\`,
   `Backend\backups\`, `Backend\.venv\`, and the Frontend `.env`.
3. Reinstall frontend packages with `pnpm install`.

## Rotate credentials

- Rotate every user password stored in the committed database; ask those users to reset it.
- Revoke API tokens in any other environment with `manage.py revoke_all_tokens --yes`.
- Treat the old Django secret key as public and give every environment its own new
  `DJANGO_SECRET_KEY`.
- Rotate the SMTP password if the old `.env.example` ever contained a real one.

## Finish

Check forks and CI caches, then securely delete the mirror backups after cleanup is confirmed.

Do not run this runbook as part of normal task implementation.
