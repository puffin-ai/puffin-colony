"""colony step: the steps only a person can take, tested before they're handed over, kept on the code host, and
saying who does each one.

Some steps need a person: a cloud sign-in, applying infrastructure, a payment, a setting only an owner can change.
`colony step add "<what>" --run "<command>" --who <person>` hands one over:

1. It tests the step first, where it can. `--check <command>` runs a command that shows the step will work, such as a
   plan or a version check. Without one, it runs the dry-run form of the step's own command when Colony knows one
   (dry_run_of: DRY_RUNS, plus `[steps] dry_runs`), such as `terraform plan` for `terraform apply`. It never runs the
   step's own command. A failing test stops the hand-over and shows the test's output, unless `--anyway`; a step with
   no test says so plainly.
2. It keeps the step on the code host, as one comment on the issue `Colony: person steps` (`[steps] issue` names
   another), so every computer and every person reads the same list, never a file on one computer.
3. It says who does the step: a person, mentioned by their login so the code host tells them, `anyone`, or `agent`.

`colony step list` prints the open steps, `--who <person>` one person's, and `colony step done <n>` marks one done
by editing its comment. A step never holds a secret: text that looks like one is refused.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import time

from colony import cli, portable, wait

TITLE = f"{cli.NAME.capitalize()}: person steps"
NOTE = f"{cli.NAME}-step"
NOTE_TEXT = re.compile(rf"<!--\s*{NOTE}\s+(\{{.*?\}})\s*-->", re.S)
STATUS_LINE = re.compile(r"^Status: .*$", re.M)
COMMAND = re.compile(r"^(`{3,})sh\n(.*?)\n\1$", re.M | re.S)
EVERYONE = ("anyone", "agent")
CHECK_SECONDS = 120  # a test that runs longer than this counts as failed
COMPOUND = re.compile(r"[;&|<>`$\n]")  # a command with these has no dry-run form Colony can work out
# The step's command start, the dry-run command start it becomes, and the flags added after it. The flags in DROP
# go: a dry run never takes an approval flag.
DRY_RUNS = (
    ("terraform apply", "terraform plan", ""),
    ("tofu apply", "tofu plan", ""),
    ("pulumi up", "pulumi preview", ""),
    ("kubectl apply", "kubectl apply", "--dry-run=server"),
    ("kubectl delete", "kubectl delete", "--dry-run=server"),
    ("helm upgrade", "helm upgrade", "--dry-run"),
    ("helm install", "helm install", "--dry-run"),
    ("npm publish", "npm publish", "--dry-run"),
    ("pnpm publish", "pnpm publish", "--dry-run"),
    ("cargo publish", "cargo publish", "--dry-run"),
    ("ansible-playbook", "ansible-playbook", "--check"),
    ("rsync", "rsync", "--dry-run"),
    ("git push", "git push", "--dry-run"),
    ("aws ec2", "aws ec2", "--dry-run"),
    ("make", "make -n", ""),
)
DROP = {"-auto-approve", "--auto-approve", "--yes", "-y"}


def settings(config: dict) -> dict:
    """`[steps]`, each key with its default."""
    table = config.get("steps") or {}
    issue = table.get("issue", 0)
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 0:
        raise cli.ColonyError("[steps] issue is the number of the issue that holds the person steps, or 0 to let "
                              "Colony open one")
    dry_runs = table.get("dry_runs") or {}
    if not isinstance(dry_runs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in dry_runs.items()):
        raise cli.ColonyError('[steps] dry_runs is a table of command starts and their dry runs, such as '
                              '{ "./deploy.sh" = "./deploy.sh --check" }')
    return {"issue": issue, "dry_runs": dry_runs}


def dry_run_of(config: dict, command: str) -> str:
    """The dry-run form of a step's command, or "" when Colony knows none: the repo's `[steps] dry_runs` first, then
    DRY_RUNS. A compound command, with pipes, `;`, `&&` or redirects, gets none."""
    command = command.strip()
    if not command or COMPOUND.search(command):
        return ""
    try:
        words = shlex.split(command)
    except ValueError:
        return ""
    own = [(start, dry, "") for start, dry in settings(config)["dry_runs"].items()]
    for start, dry, flag in [*own, *DRY_RUNS]:
        try:
            head, swap = shlex.split(start), shlex.split(dry)
        except ValueError:  # a [steps] dry_runs entry with unclosed quotes matches nothing
            continue
        if not head or words[:len(head)] != head:
            continue
        rest = [word for word in words[len(head):] if word not in DROP]
        found = swap + rest + ([flag] if flag and flag not in rest else [])
        return shlex.join(found)
    return ""


def run_test(command: str) -> tuple[bool, str]:
    """Run a step's test, and say whether it passed, with its last line of output (a secret-shaped one stays out)."""
    from colony import merge

    shell_cmd, shell, env = portable.shell(command, None)
    try:
        where = cli.repo_root()  # the step's command runs from the repo's top, as the person runs it
    except cli.ColonyError:
        where = None
    try:
        run = subprocess.run(shell_cmd, shell=shell, env=env, cwd=where, capture_output=True, text=True,
                             timeout=CHECK_SECONDS)
    except subprocess.TimeoutExpired:
        return False, f"it ran past {CHECK_SECONDS} seconds"
    except OSError as e:
        return False, str(e)
    lines = merge.readable(f"{run.stdout}\n{run.stderr}")
    return run.returncode == 0, merge.safe((lines[-1] if lines else "no output")[:200], "last line")


def who_of(config: dict, who: str) -> tuple[str, str]:
    """Who does a step, as stored, and how the comment names them: a person with their login mentioned, so the code
    host tells them, or `anyone` or `agent`. A person with a known login is stored as that login, so `Ana` and
    `@ana-gh` are the same person to `colony step list --who`."""
    who = who.strip()
    if who.lower() in EVERYONE:
        return who.lower(), who.lower()
    login = who[1:] if who.startswith("@") else ""
    person = login or who
    logins = sorted(wait.person_logins(config, person)) or ([login.lower()] if login else [])
    if not logins:
        return person.lower(), person
    name = wait.display_name(config, logins[0])
    return logins[0], f"@{logins[0]} ({name})" if name.lower() != logins[0] else f"@{logins[0]}"


def team(config: dict) -> frozenset[str]:
    """The team's logins, `[people] logins`, lowercased, as presence.by_team reads them."""
    return frozenset(str(login).lower() for login in config.get("people", {}).get("logins", []))


def steps_issue(config: dict) -> int:
    """The issue that holds the person steps: `[steps] issue`, else the open `Colony: person steps` one of the team's
    logins opened (with none configured, the login gh runs as here), else a new one. On a public repo anyone can open
    an issue with that title, and theirs never holds the team's steps."""
    from colony import merge

    number = settings(config)["issue"]
    if number:
        return number
    repo = config["project"]["repo"]
    listed = json.loads(wait.gh("issue", "list", "--repo", repo, "--state", "open", "--search", f'"{TITLE}" in:title',
                                "--json", "number,title,author", "--limit", "20") or "[]")
    trusted = team(config) or {merge.terminal_login().lower()}
    found = sorted(issue["number"] for issue in listed if issue.get("title") == TITLE
                   and str((issue.get("author") or {}).get("login") or "").lower() in trusted)
    if found:
        return found[0]
    url = wait.gh("issue", "create", "--repo", repo, "--title", TITLE, "--body",
                  "The steps only a person can take, one comment each, with who does it and how it was tested. "
                  f"`{cli.NAME} step list` prints the open ones.")
    return int(url.strip().rstrip("/").rsplit("/", 1)[-1])


def comments(config: dict, number: int) -> list[dict]:
    """The steps issue's comments, each with its id, body, link, author and the author's standing on the repo."""
    out = wait.gh("api", f"repos/{config['project']['repo']}/issues/{number}/comments?per_page=100", "--paginate",
                  "--jq", ".[] | {id, body, html_url, author_association, user: {login: .user.login}} | @json")
    found = []
    for line in out.splitlines():
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def read_steps(config: dict, number: int) -> list[dict]:
    """The steps on the issue, oldest first: each note in a comment the team wrote (presence.by_team), with the
    comment's id, body and link. On a public repo anyone can comment, and their comment is never a step."""
    from colony import presence

    found, logins = [], team(config)
    for comment in comments(config, number):
        if not presence.by_team(comment, logins):
            continue
        notes = list(NOTE_TEXT.finditer(comment.get("body") or ""))
        if not notes:
            continue
        note = notes[-1]  # the note Colony wrote comes last, after every word a person wrote
        try:
            data = json.loads(note[1])
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("n"), int):
            found.append({**data, "id": comment.get("id"), "body": comment.get("body") or "",
                          "url": comment.get("html_url") or ""})
    return sorted(found, key=lambda step: step["n"])


def stamp() -> str:
    """Now, as YYYY-MM-DD HH:MM UTC."""
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def shown_text(text: str) -> str:
    """A person's words as a comment shows them: `<!--` and `-->` written out, so no step's text can hide the rest of
    the comment or pass for its note."""
    return text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")


def fence(command: str) -> str:
    """A code fence longer than any run of backticks in the command, so the command can't close it."""
    return "`" * max([3, *(len(run) + 1 for run in re.findall(r"`{3,}", command))])


def comment_body(n: int, what: str, shown: str, command: str, why: str, tested: str, data: dict) -> str:
    """One step's comment. Its Status line and its note come last, after everything a person wrote."""
    lines = [f"**Step {n}, for {shown}:** {shown_text(what)}", ""]
    if command:
        lines += [f"{fence(command)}sh", shown_text(command), fence(command), ""]
    if why:
        lines += [f"Why a person: {shown_text(why)}", ""]
    lines += [shown_text(tested), "", "Status: open", "", f"<!-- {NOTE} {json.dumps(data, separators=(',', ':'))} -->"]
    return "\n".join(lines)


def add(config: dict, args) -> int:
    """`colony step add`: test the step where Colony can, then keep it on the steps issue."""
    from colony import plain, transport

    what = " ".join((args.what or "").split())
    command, why = (args.run or "").strip(), " ".join((args.why or "").split())
    if not what:
        raise cli.ColonyError("say what the step is, in one sentence")
    for text in (what, command, why, args.check or ""):
        found = transport.holds_secret(text)
        if found:
            raise cli.ColonyError(f"a step never holds a secret, and this one holds {found}: name where it is kept")
    who, shown = who_of(config, args.who or cli.person_of(config, args))
    test = (args.check or "").strip() or dry_run_of(config, command)
    if args.no_check:
        test = ""
    if args.dry_run:
        print(f"{cli.NAME} step add: dry run, nothing runs.\n  for {shown}: {what}"
              + (f"\n  test first: $ {test}" if test else "\n  no test: Colony knows no dry run for it")
              + f"\n  then post it on the issue {TITLE!r} of {config['project']['repo']}")
        return 0
    if test:
        passed, last = run_test(test)
        if not passed and not args.anyway:
            print(f"not handed over: its test failed, so the step would fail too: $ {test}\n  {last}\nFix it and add "
                  "the step again, or pass --anyway to hand it over with the failure noted.")
            return 1
        tested = (f"Tested: `{test}` passed at {stamp()}." if passed else
                  f"Its test failed, and it was handed over anyway: `{test}` said: {last}")
        said = ("tested first, and the test passed" if passed else
                "tested first, and the test failed, so read the note on it before you run it")
    else:
        tested = ("Not tested: " + ("its test was skipped on purpose." if args.no_check else
                                    "Colony knows no dry run for this command, so read it before you run it."))
        said = "not tested, so read it before you run it"
    number = steps_issue(config)
    taken = read_steps(config, number)
    n = max([step["n"] for step in taken] or [0]) + 1
    data = {"n": n, "who": who, "status": "open", "tested": tested.startswith("Tested")}
    text = comment_body(n, what, shown, command, why, tested, data)
    url = wait.gh("issue", "comment", str(number), "--repo", config["project"]["repo"], "--body", text).strip()
    url = url.splitlines()[-1] if url else f"#{number}"
    print(f"step {n} for {shown} is on #{number}: {url}")
    named = wait.display_name(config, who) if who not in EVERYONE else who
    # "Apply the change" reads as "apply the change" mid-sentence; a first word in capitals, such as AWS, stays.
    told = what[0].lower() + what[1:] if what[1:2].islower() else what
    print("Tell them: " + plain.fill("person_step", who=named, what=told, tested=said, link=url))
    return 0


def listed(config: dict, args) -> int:
    """`colony step list`: the open steps, or every step with --all, or one person's with --who."""
    number = steps_issue(config)
    found = read_steps(config, number)
    if args.who:
        who = who_of(config, args.who)[0]
        found = [step for step in found if step.get("who") == who]
    if not args.all:
        found = [step for step in found if step.get("status") == "open"]
    if not found:
        print(f"no {'' if args.all else 'open '}person steps on #{number}")
        return 0
    for step in found:
        first = step["body"].splitlines()[0].replace("**", "")
        command = COMMAND.search(step["body"])
        shown = command[2].replace("&lt;!--", "<!--").replace("--&gt;", "-->") if command else ""
        print(f"{first} [{step.get('status')}{', tested' if step.get('tested') else ', not tested'}]"
              + (f"\n    $ {shown}" if command else "") + f"\n    {step['url']}")
    return 0


def last_replaced(text: str, pattern: re.Pattern, new: str) -> str:
    """The text with the last match of the pattern replaced: the Status line and note Colony wrote come after any
    line of a person's command that looks like one. The new text goes in as it is, never read as a regex."""
    found = list(pattern.finditer(text))
    return text if not found else text[:found[-1].start()] + new + text[found[-1].end():]


def done(config: dict, args) -> int:
    """`colony step done <n>`: mark a step done, by editing its comment."""
    from colony import merge

    number = steps_issue(config)
    step = next((s for s in read_steps(config, number) if s["n"] == args.n), None)
    if step is None:
        raise cli.ColonyError(f"#{number} holds no step {args.n}: `{cli.NAME} step list --all` lists them")
    if step.get("status") == "done":
        print(f"step {args.n} is already done")
        return 0
    note = shown_text(" ".join((args.note or "").split()))
    by = merge.terminal_login()
    status = f"Status: done by @{by} at {stamp()}" + (f": {note}" if note else "") if by != "someone" else \
        f"Status: done at {stamp()}" + (f": {note}" if note else "")
    data = {key: step[key] for key in ("n", "who", "tested") if key in step} | {"status": "done"}
    note_text = f"<!-- {NOTE} {json.dumps(data, separators=(',', ':'))} -->"
    text = last_replaced(last_replaced(step["body"], STATUS_LINE, status), NOTE_TEXT, note_text)
    wait.gh("api", "-X", "PATCH", f"repos/{config['project']['repo']}/issues/comments/{step['id']}", "-f",
            f"body={text}")
    print(f"step {args.n} is done: {step['url']}")
    return 0


def run(config: dict, args) -> int:
    """`colony step add|list|done`."""
    return {"add": add, "list": listed, "done": done}[args.action](config, args)


def register(sub) -> None:
    """The `step` command and its actions."""
    p = sub.add_parser("step", help="hand a step only a person can take over, tested first, kept on the code host, "
                                    "and saying who does it; list them, or mark one done")
    actions = p.add_subparsers(dest="action", metavar="action", required=True)
    a = actions.add_parser("add", help="test a step where Colony can, then post it on the person steps issue")
    a.add_argument("what", help="what the step is, in one sentence")
    a.add_argument("--run", help="the command the person runs, if any")
    a.add_argument("--who", help="who does it: a person, @login, anyone or agent; you by default")
    a.add_argument("--why", help="why a person must do it, such as whose sign-in it needs")
    a.add_argument("--check", help="a command that shows the step will work, run before it is handed over")
    a.add_argument("--no-check", action="store_true", help="hand it over untested, and say so")
    a.add_argument("--anyway", action="store_true", help="hand it over even though its test failed, and say so")
    a.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    a.set_defaults(run=run, action="add")
    a = actions.add_parser("list", help="the open person steps")
    a.add_argument("--who", help="one person's steps")
    a.add_argument("--all", action="store_true", help="the done ones too")
    a.set_defaults(run=run, action="list")
    a = actions.add_parser("done", help="mark a step done")
    a.add_argument("n", type=int, help="the step's number")
    a.add_argument("--note", help="what was done, in a few words")
    a.set_defaults(run=run, action="done")
