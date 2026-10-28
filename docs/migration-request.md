# Starting a run from an issue

`migration-request.yml` lets you start **ThoughtSpot Migration** without opening the Actions tab,
for example from the migration console app. It is additive: `ts-migration.yml`,
`org-migration.yml`, the scripts and the run UI are unchanged, and the run it starts is the same
as *Actions -> ThoughtSpot Migration -> Run workflow*.

## How to use it

Open an issue whose title starts with `[migration-request]` and whose body contains:

```
org: github
dry_run: true
```

`org` is an org key from `config/orgs/` or `all`; `dry_run` is `true` or `false`.

## What happens

1. The workflow runs only for issues with that title prefix; other issues are skipped.
2. The issue author must have write, maintain or admin access to the repository. Anyone else
   gets a `status: rejected` reply.
3. `org` must match a config whose filename equals its `org_key` (the same rule as the setup
   job), and `dry_run` must be `true` or `false`.
4. It dispatches `ts-migration.yml` on `ts-prod` with those inputs. From there the run behaves
   exactly as usual: a promote PR that a person merges (merging is the approval), the merge
   wait, snapshot, import, reports and the restore-point tag.
5. It appends a status block to the issue body and adds a comment, then closes the issue:

```
status: started
org: github
dry_run: false
requested_by: <login>
run: https://github.com/<owner>/<repo>/actions/runs/<id>
```

Requests are handled one at a time so each is matched to the run it started. The workflow needs
only `actions: write` and `issues: write`; it uses no ThoughtSpot secrets. The issue text is read
as data inside the script and never placed into a shell command.

## Turning it off

Delete `.github/workflows/migration-request.yml`, or disable **Migration Request** in the Actions
tab. Nothing else depends on it.
