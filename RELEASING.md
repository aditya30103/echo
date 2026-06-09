# Releasing echo-archaeology to PyPI

Echo publishes via GitHub Actions + PyPI **Trusted Publishing** (OIDC) — no API
tokens or secrets are stored anywhere. The workflow is
`.github/workflows/publish.yml`.

There are two paths: a **TestPyPI rehearsal** (manual, do this first) and a
**production release** (triggered by pushing a `v*` tag).

---

## One-time setup (do this once, before the first release)

You register this repo as a trusted publisher on both TestPyPI and PyPI, then
create the matching GitHub Environments. **This is the part only you can do.**

### 1. PyPI (production)
1. Log in at <https://pypi.org>.
2. Go to <https://pypi.org/manage/account/publishing/> → **Add a new pending publisher**:
   - PyPI Project Name: `echo-archaeology`
   - Owner: `aditya30103`
   - Repository name: `echo`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

   (A "pending publisher" reserves the name and lets the first workflow run create
   the project — no manual `twine upload` needed.)

### 2. TestPyPI (rehearsal)
Repeat the same at <https://test.pypi.org/manage/account/publishing/> with
**Environment name: `testpypi`**. TestPyPI is a separate account/registration
from PyPI.

### 3. GitHub Environments
In the repo: **Settings → Environments** → create two environments:
- `pypi` — optionally add yourself as a **Required reviewer** (a human approval
  gate before every production publish).
- `testpypi`

---

## Rehearse on TestPyPI (before the first real release)

1. GitHub → **Actions → "Publish to PyPI" → Run workflow** → `target = testpypi`.
2. The build job rebuilds the UI, builds the wheel + sdist, and **boot-tests the
   wheel in a clean venv**. If that fails, nothing publishes — fix and retry.
3. On success it publishes to TestPyPI. Verify a clean install from there:
   ```bash
   python -m venv /tmp/echo-test
   /tmp/echo-test/bin/pip install \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     echo-archaeology
   /tmp/echo-test/bin/echo --help
   ```
   The `--extra-index-url` lets real dependencies resolve from PyPI while
   `echo-archaeology` itself comes from TestPyPI.

---

## Cut a real release

1. Bump `version` in `pyproject.toml` (semver) and add a `CHANGELOG.md` entry.
2. `git commit -am "release: vX.Y.Z"`
3. `git tag vX.Y.Z`
4. `git push origin master && git push origin vX.Y.Z`
5. The tag push triggers `publish.yml` → build → **boot-check** → publish to PyPI.
   (If you set a Required reviewer on the `pypi` environment, approve the run.)
6. Verify in a clean environment:
   ```bash
   pip install echo-archaeology
   echo --help
   ```

---

## Notes

- **Version is single-sourced** in `pyproject.toml`. The git tag must match it
  (tag `v0.1.0` ↔ `version = "0.1.0"`). PyPI rejects re-uploading an existing
  version, so bump before every release.
- The **boot-check gate** means a wheel that builds but can't import (the
  `api/`-outside-package class of bug) aborts the publish instead of shipping
  broken. The same check runs on every PR via `smoke.yml`.
- No secrets to rotate: trusted publishing uses short-lived OIDC tokens minted
  per run.
