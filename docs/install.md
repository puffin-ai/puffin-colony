# Install

You need [Claude Code](https://code.claude.com) (signed in), `git`, and the GitHub CLI `gh` (signed in). Your repo must be on GitHub. Colony itself is a Python 3.11+ tool with no dependencies; every way below gets you the same `colony` command.

## Every way to install

| Way | Command | What you get |
| --- | --- | --- |
| uvx | `uvx puffin-colony` | Runs the latest release once, with no install. |
| npx | `npx puffin-colony` | The same, for people with Node. It runs `uvx puffin-colony`, or `python3 -m colony` when uv is missing and the package is installed, and says how to install uv when neither works. |
| uv tool | `uv tool install puffin-colony` | `colony` and `puffin-colony` on your PATH for good. Update with `uv tool upgrade puffin-colony`. |
| npm | `npm install -g puffin-colony` | `colony` and `puffin-colony` on your PATH, through the same wrapper as npx. |
| curl installer | `curl -LsSf https://raw.githubusercontent.com/puffin-ai/puffin-colony/main/install.sh \| sh` | Installs uv first when it is missing (it says so before it does, with Astral's official installer), then runs `uv tool install puffin-colony`. |
| pipx | `pipx install puffin-colony` | The same as uv tool, with pipx. |
| From source | `git clone https://github.com/puffin-ai/puffin-colony && cd puffin-colony && uv tool install --editable .` | The command runs your clone, so your edits take effect at once. |

The sessions Colony opens run `colony` commands themselves (`colony hi`, `colony wait`, `colony open`), so for everyday use install it for good, with uv tool, npm, the curl installer or pipx. `uvx` and `npx` are for a first try.

## Then `colony` does everything

Run `colony` in your repo. The first time, it sets the repo up; every time after, it opens the lead. `colony --help` lists the rest, and [commands.md](commands.md) explains each one.

The first time `colony` runs on a computer, it also installs the `colony-setup` skill into your Claude settings folder (`~/.claude`, or the one `CLAUDE_CONFIG_DIR` names), as `colony skill-install` does. After that, opening Claude Code in any repo and saying hi is enough: the session sets Colony up, with no extra command. It happens once; a marker file, `.colony-first-run` in that folder, records it, so a skill you remove stays removed.

## Publishing a release (maintainers)

The workflow `.github/workflows/release.yml` runs on a pushed tag `v*`. It checks that the tag matches `colony/__init__.py` and `npm/package.json`, runs the tests, builds the sdist and the wheel, publishes them to PyPI with trusted publishing (no token), and then publishes `npm/` to npm with the `NPM_TOKEN` secret.

### One-time setup

1. **PyPI: create the project with a trusted publisher.**
   1. Create an account at <https://pypi.org/account/register/>, verify the email, and turn on two-factor authentication (PyPI requires it to publish).
   2. Open <https://pypi.org/manage/account/publishing/>. Under "Add a new pending publisher", choose GitHub and fill in:
      - PyPI Project Name: `puffin-colony`
      - Owner: `puffin-ai`
      - Repository name: `puffin-colony`
      - Workflow name: `release.yml`
      - Environment name: `pypi`
   3. Click "Add". The first release creates the project, and the pending publisher becomes its trusted publisher.
2. **GitHub: create the `pypi` environment.** In the repo, Settings → Environments → New environment, name it `pypi`. Optionally add yourself under "Required reviewers", so each PyPI release waits for your approval.
3. **npm: create the account, and the org if you want one.**
   1. Create an account at <https://www.npmjs.com/signup> and turn on two-factor authentication.
   2. The package name is the unscoped `puffin-colony`, so no org is needed; npm creates the package on the first publish. To share it with teammates, create the org at <https://www.npmjs.com/org/create> (for example `puffin-ai`), and after the first release add the package to the org's team under the package's Settings.
4. **npm: create a token and add the `NPM_TOKEN` secret.**
   1. On npmjs.com: your avatar → Access Tokens → Generate New Token → Granular Access Token. Give it read and write access to packages, scoped to `puffin-colony` (before the first publish, choose "All packages", then narrow it after), and turn on "Bypass two-factor authentication" so CI can publish.
   2. In the GitHub repo: Settings → Secrets and variables → Actions → New repository secret. Name `NPM_TOKEN`, value the token.
5. **Release.** With the version in `colony/__init__.py` and `npm/package.json` both at `0.2.0`, on the main branch:

   ```sh
   git tag v0.2.0 && git push --tags
   ```

   Watch the run under the repo's Actions tab. Then check `uvx puffin-colony --help` and `npx puffin-colony --help`.

For each later release, raise the version in both files, commit, and tag `v<version>`.

### Checking a build locally

```sh
uv build
uvx --from ./dist/puffin_colony-0.2.0-py3-none-any.whl puffin-colony --help
cd npm && npm pack --dry-run
```
