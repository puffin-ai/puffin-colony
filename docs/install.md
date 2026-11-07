# Install

You need [Claude Code](https://code.claude.com) (signed in), `git`, and the GitHub CLI `gh` (signed in). Your repo must be on GitHub. Colony itself is a Python 3.11+ tool with no dependencies; every way below gets you the same `colony` command.

## Every way to install

| Way | Command | What you get |
| --- | --- | --- |
| uvx | `uvx puffin-colony` | Runs the latest release, and on the first run installs it for good with `uv tool install puffin-colony`, so `colony` is on your PATH after. |
| npx | `npx puffin-colony` | The same, for people with Node. It runs `uvx puffin-colony`, or `python3 -m colony` when uv is missing and the package is installed, and says how to install uv when neither works. |
| uv tool | `uv tool install puffin-colony` | `colony` and `puffin-colony` on your PATH for good. Update with `uv tool upgrade puffin-colony`. |
| npm | `npm install -g puffin-colony` | `colony` and `puffin-colony` on your PATH, through the same wrapper as npx. |
| curl installer | `curl -LsSf https://raw.githubusercontent.com/puffin-ai/puffin-colony/main/install.sh \| sh` | Installs uv first when it is missing (it says so before it does, with Astral's official installer), then runs `uv tool install puffin-colony`. |
| pipx | `pipx install puffin-colony` | The same as uv tool, with pipx. |
| From source | `git clone https://github.com/puffin-ai/puffin-colony && cd puffin-colony && uv tool install --editable .` | The command runs your clone, so your edits take effect at once. |

The sessions Colony opens run `colony` commands themselves (`colony`, `colony wait`, `colony helpers`), so Colony must be on PATH. A first `uvx` or `npx` run takes care of that: it installs Colony for good with `uv tool install puffin-colony`, once, and says so. uv tool, npm, the curl installer and pipx install it for good directly.

### The walker's browser

A batch's walker drives a browser. By default it uses the Playwright MCP, which setup offers. With `[walk] browser = "agent-browser"` in `.colony/colony.toml`, it runs the [agent-browser](https://github.com/vercel-labs/agent-browser) CLI instead, which needs Node and one install on each computer that runs batches. The second command downloads the Chrome it drives:

```sh
npm install -g agent-browser && agent-browser install
```

`agent-browser doctor` then checks the install.

## The repo carries Colony

A repo that runs Colony pins it the way a package file pins a dependency, so a teammate's setup is to clone the repo, open it in Claude Code, and log in. They need no plugin, no click and no command.

- **The launcher.** `.colony/bin/colony` is a short shell script that names one Colony version, its pin. `colony setup` writes it through `colony hooks install`, and so does every later `colony hooks install`, pinned to the version that ran. The first time it runs on a computer, it installs that version from its tag on GitHub (`git+https://github.com/puffin-ai/puffin-colony@v<pin>`) through uv, into `~/.cache/puffin-colony/v<pin>/`. Every run after that starts Colony from there, so a run costs one Python start. If the computer has no uv, the launcher installs it first with Astral's official installer and says so.
- **The PATH.** The repo's `.claude/settings.json` carries a SessionStart hook that adds `export PATH="<repo>/.colony/bin:$PATH"` to the `CLAUDE_ENV_FILE` Claude Code runs before each Bash command. So a plain `colony` in any session in the repo runs the pinned version. Colony's other hooks run `"$CLAUDE_PROJECT_DIR/.colony/bin/colony"` directly, because a hook doesn't read that file.
- **A newer release.** At most once a day, the lead's session shows one line when a newer Colony tag than the pin exists, with a link to its CHANGELOG. `colony upgrade` creates a branch, `colony/upgrade-v<new>`, and moves the pin. Then, running under the new version, it rewrites the files Colony copied into the repo: the launcher, the wait guard, the hooks, and the role skills the repo has. It commits all of that, ready for you to push and open a PR. `colony upgrade --to v<version>` pins a release other than the newest.

The plugin and a `colony` you installed yourself still work beside the launcher. In a repo that carries Colony, the plugin's `colony` hands over to the repo's launcher, and the plugin's hooks step aside, so each hook runs once.

## As a Claude Code plugin

The plugin is the way to try Colony in a repo that hasn't adopted it yet. The Colony repo is also a Claude Code plugin marketplace, from GitHub alone. `.claude-plugin/marketplace.json` names one plugin, `puffin-colony`, whose skills are Colony's own (`colony/skills/`) and whose hooks are the ones `colony hooks install` writes (`colony/hooks/hooks.json`). The wait guard runs from the plugin's own copy.

To have every teammate's Claude Code offer it in your repo, name the marketplace and turn the plugin on in the repo's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "puffin-colony": {
      "source": { "source": "github", "repo": "puffin-ai/puffin-colony" }
    }
  },
  "enabledPlugins": {
    "puffin-colony@puffin-colony": true
  }
}
```

When a teammate trusts the repo's folder, Claude Code asks them to install it. One person can also install it alone with `/plugin marketplace add puffin-ai/puffin-colony`, then `/plugin install puffin-colony@puffin-colony`.

The plugin also gives sessions the `colony` command. Claude Code puts the plugin's `bin/` on the Bash tool's PATH, and `bin/colony` runs Colony from the plugin's own copy through uv, on Python 3.11 or later, which uv fetches when the computer has none. The plugin's hooks run that same `bin/colony`. A `colony` you installed yourself comes first on PATH and wins.

uv is the one thing the plugin needs. When the computer has none, the plugin's first hook of the session installs it with Astral's official installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`, which puts it in `~/.local/bin`) and says so in one line. When that fails, it says so and points to [uv's install page](https://docs.astral.sh/uv/).

The manual route still works: `uv tool install git+https://github.com/puffin-ai/puffin-colony@v<version>` puts `colony` on your own terminal's PATH as well. A repo that runs the plugin doesn't also need `colony hooks install`. With both, each hook still runs once: a plugin hook steps aside where the repo's settings carry the same hook and it can run, which for the wait guard means its copied script is there, and for the others the repo's launcher. Claude Code on claude.ai and Cowork don't install a plugin with a top-level `bin/`, so there Colony takes the manual route.

## On Windows

Colony runs on Windows with [Git for Windows](https://gitforwindows.org), which Claude Code needs there too.

- It runs your repo's commands, such as `checks` and `fast_check`, through Git's bash, so a `colony.toml` written on a Mac works unchanged.
- It restarts itself once in Python's UTF-8 mode, so it reads gh's output and your files as UTF-8.
- Its hooks run `python3`. Put `%USERPROFILE%\.local\bin`, where `uv tool install` and `uv python install --default` write, before `%LOCALAPPDATA%\Microsoft\WindowsApps` on your PATH. Or turn off the python and python3 aliases under Settings > Apps > Advanced app settings > App execution aliases, which only open the Microsoft Store.
- cmux is macOS only, so helpers open in this terminal or as background sessions.
- To run the tests: `uv run --with pytest python -X utf8 -m pytest tests`.

## Then `colony` does everything

Run `colony` in your repo. The first time, it sets the repo up; every time after, it opens the lead. `colony --help` lists the rest, and [commands.md](commands.md) explains each one.

The first time `colony` runs on a computer, it also installs the `colony-setup` skill into your Claude settings folder (`~/.claude`, or the one `CLAUDE_CONFIG_DIR` names), as `colony skill-install` does. After that, opening Claude Code in any repo and saying hi is enough: the session sets Colony up, with no extra command. It happens once; a marker file, `.colony-first-run` in that folder, records it, so a skill you remove stays removed.

## Publishing a release (maintainers)

A pushed tag `v*` publishes nothing by itself: the plugin and `uv tool install git+...@v<version>` install from the tag on GitHub, and the tag is the release. The workflow `.github/workflows/release.yml` publishes to PyPI and npm only when a maintainer runs it by hand, under Actions → release → Run workflow, with the tag to publish. It checks that the tag matches `colony/__init__.py`, `npm/package.json` and `.claude-plugin/plugin.json`, runs the tests, builds the sdist and the wheel, publishes them to PyPI with trusted publishing (no token), and then publishes `npm/` to npm with the `NPM_TOKEN` secret.

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
5. **Release.** With the version in `colony/__init__.py`, `npm/package.json` and `.claude-plugin/` all at `0.3.0`, on the main branch:

   ```sh
   git tag v0.3.0 && git push --tags
   ```

   That releases it on GitHub. To publish it to PyPI and npm too, run the workflow: Actions → release → Run workflow, with tag `v0.3.0`, or `gh workflow run release.yml -f tag=v0.3.0`. Watch the run under the repo's Actions tab. Then check `uvx puffin-colony --help` and `npx puffin-colony --help`.

For each later release, raise the version in `colony/__init__.py`, `npm/package.json`, `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, regenerate `colony/hooks/hooks.json` from `guards.plugin_hooks()`, add a CHANGELOG.md entry, commit, and tag `v<version>`.

### Checking a build locally

```sh
uv build
uvx --from ./dist/puffin_colony-0.3.0-py3-none-any.whl puffin-colony --help
cd npm && npm pack --dry-run
```
