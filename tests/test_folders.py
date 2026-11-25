"""Tests for folders.py: one lead registry every worktree and computer reads, loans and borrows of folders, one owner
for the rest of the repo, silent and long-gone leads, and worktrees kept inside the repo's worktrees folder."""
import argparse
import json
import subprocess
import time

import pytest

from colony import cli, folders, presence, wait
from test_hi import CONFIG, GitHub, config, github, home, host, lead  # noqa: F401  (fixtures)

HOURS = 3600


def commit_all(repo, message="setup"):
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message],
                   check=True)


def as_lead(monkeypatch, name):
    monkeypatch.setenv(cli.SESSION_ENV, "lead")
    monkeypatch.setenv(wait.LEAD_ENV, name)
    monkeypatch.setenv(cli.PERSON_ENV, name.split("-", 1)[0])


def as_helper(monkeypatch, name, of):
    monkeypatch.setenv(cli.SESSION_ENV, name)
    monkeypatch.setenv(wait.LEAD_ENV, of)


def card_says(monkeypatch, github, body):
    """The card's body, as `gh issue view` gives it."""
    real = github.gh

    def gh(*args):
        if args[:2] == ("issue", "view"):
            github.calls.append(args)
            return json.dumps({"body": body})
        return real(*args)
    monkeypatch.setattr(wait, "gh", gh)


def posted(github) -> list[str]:
    return [call[-1] for call in github.calls if call[:2] == ("issue", "comment")]


def take(config, card):
    return cli.take(config, argparse.Namespace(card=card))


@pytest.fixture
def board(monkeypatch):
    from colony import board as cards

    taken = []
    monkeypatch.setattr(cards, "set_fields", lambda config, card, pairs: taken.append(card))
    return taken


# One registry for every copy of the repo


def test_a_claim_in_the_main_checkout_is_what_every_worktree_reads_with_no_commit(home, host, config, github,
                                                                                  capsys, monkeypatch):
    commit_all(host)
    assert cli.claim(config, argparse.Namespace(stream="web", folders=["apps/web"], person=None)) == 0
    assert "needs no commit" in capsys.readouterr().out
    tree = folders.worktree_path(config, "builder-1-12")
    subprocess.run(["git", "-C", str(host), "worktree", "add", "-q", "-b", "b/12", str(tree)], check=True)
    monkeypatch.chdir(tree)
    assert presence.registry()["ana-web-lead"]["folders"] == ["apps/web/"]
    assert not (tree / ".colony" / "leads.toml").exists() and not (host / ".colony" / "leads.toml").exists()
    status = subprocess.run(["git", "-C", str(host), "status", "--porcelain"], capture_output=True, text=True)
    assert status.stdout == ""  # neither the registry nor the worktree is an uncommitted change


def test_the_registry_from_before_is_read_once_from_the_main_checkout(home, host, config):
    (host / ".colony" / "leads.toml").write_text('[leads."ana-api-lead"]\nperson = "ana"\nfolders = ["api/"]\n')
    assert presence.registry() == {"ana-api-lead": {"person": "ana", "folders": ["api/"]}}
    presence.write_registry({**presence.registry(), "ana-web-lead": {"person": "ana", "folders": ["web/"]}})
    (host / ".colony" / "leads.toml").unlink()
    assert set(presence.registry()) == {"ana-api-lead", "ana-web-lead"}  # the shared file holds both now


def test_a_helper_on_another_computer_reads_its_leads_folders_from_the_leads_status(home, config, github, board,
                                                                                    monkeypatch):
    github.add(lead(name="ana-engine-lead", folders=["apps/api/"], computer="PC-2"))
    as_helper(monkeypatch, "builder-1", "ana-engine-lead")
    card_says(monkeypatch, github, "Folders: apps/web/")
    with pytest.raises(cli.ColonyError, match="touches apps/web/, outside ana-engine-lead's folders"):
        take(config, 12)  # before, an empty registry here made it the rest of the repo, and it took the card
    card_says(monkeypatch, github, "Folders: apps/api/db/")
    assert take(config, 12) == 0 and board == [12]


# Loans and borrows


def test_a_lead_lends_folders_for_named_cards_and_only_those_cards(home, config, github, board, monkeypatch, capsys):
    presence.write_registry({"ana-api-lead": {"person": "ana", "folders": ["apps/api/"]},
                             "ana-web-lead": {"person": "ana", "folders": ["apps/web/"]}})
    as_lead(monkeypatch, "ana-api-lead")
    with pytest.raises(cli.ColonyError, match="doesn't hold apps/web/"):
        folders.lend(config, argparse.Namespace(to="ana-web-lead", paths=["apps/web/"], card=[12], end=False))
    assert folders.lend(config, argparse.Namespace(to="ana-web-lead", paths=["apps/api/db"], card=[12],
                                                   end=False)) == 0
    assert "ana-api-lead lends apps/api/db/ to ana-web-lead for #12." in capsys.readouterr().out
    assert any(line.startswith("for ana-web-lead: lent: ana-api-lead lends apps/api/db/ for #12") for line in posted(github))
    assert presence.parse(github.comments[-1]["body"]).lent == [{"to": "ana-web-lead", "paths": ["apps/api/db/"],
                                                                 "cards": [12]}]
    as_helper(monkeypatch, "builder-2", "ana-web-lead")
    card_says(monkeypatch, github, "Folders: apps/web/, apps/api/db/")
    assert take(config, 12) == 0
    with pytest.raises(cli.ColonyError, match="touches apps/api/db/, outside ana-web-lead's folders"):
        take(config, 13)
    as_lead(monkeypatch, "ana-api-lead")
    assert folders.lend(config, argparse.Namespace(to="ana-web-lead", paths=[], card=[12], end=True)) == 0
    as_helper(monkeypatch, "builder-2", "ana-web-lead")
    with pytest.raises(cli.ColonyError, match="outside ana-web-lead's folders"):
        take(config, 12)


def test_borrowing_from_a_silent_lead_is_granted_at_once_and_tells_it(home, config, github, board, monkeypatch,
                                                                      capsys):
    quiet = lead(name="sam-api-lead", person="sam", folders=["apps/api/"])
    quiet.active = time.time() - 3 * HOURS  # its wait keeps the status fresh, but its session has done nothing
    github.add(quiet)
    presence.write_registry({"ana-web-lead": {"person": "ana", "folders": ["apps/web/"]}})
    as_lead(monkeypatch, "ana-web-lead")
    assert folders.borrow(config, argparse.Namespace(paths=["apps/api/"], card=[7], check=False,
                                                     give_back=False)) == 0
    assert "Borrowed apps/api/ from sam-api-lead for #7, since sam-api-lead has been silent for 180 minutes" in \
        capsys.readouterr().out
    assert any(line.startswith("for sam-api-lead: borrowed: ana-web-lead uses apps/api/ for #7") for line in posted(github))
    as_helper(monkeypatch, "builder-1", "ana-web-lead")
    card_says(monkeypatch, github, "Folders: apps/api/")
    assert take(config, 7) == 0
    as_lead(monkeypatch, "ana-web-lead")
    assert folders.borrow(config, argparse.Namespace(paths=[], card=[], check=False, give_back=True)) == 0
    as_helper(monkeypatch, "builder-1", "ana-web-lead")
    with pytest.raises(cli.ColonyError, match="outside ana-web-lead's folders"):
        take(config, 7)


def test_an_ask_waits_for_a_lending_lead_and_is_granted_once_it_goes_silent(home, config, github, monkeypatch,
                                                                            capsys):
    busy = lead(name="sam-api-lead", person="sam", folders=["apps/api/"])
    busy.active = time.time()
    github.add(busy)
    presence.write_registry({"ana-web-lead": {"person": "ana", "folders": ["apps/web/"]}})
    as_lead(monkeypatch, "ana-web-lead")
    folders.borrow(config, argparse.Namespace(paths=["apps/api/x.py"], card=[9], check=False, give_back=False))
    assert "Asked sam-api-lead for apps/api/x.py for #9" in capsys.readouterr().out
    ask = next(line for line in posted(github) if "borrow: ana-web-lead asks" in line)
    assert "`colony lend ana-web-lead apps/api/x.py --card 9` says yes" in ask
    alive, _, _ = presence.everyone(config)
    assert folders.settle(config, "ana-web-lead", alive) == []  # it acts, so the ask waits
    later = time.time() + 3 * HOURS
    assert folders.settle(config, "ana-web-lead", alive, now=later)[0].startswith("borrowed apps/api/x.py for #9")
    assert folders.mine("ana-web-lead")["borrowed"][0]["from"] == "sam-api-lead"
    assert not folders.mine("ana-web-lead")["asks"]


def test_an_ask_the_holder_lent_drops(home, config, github, monkeypatch):
    holder = lead(name="sam-api-lead", person="sam", folders=["apps/api/"])
    holder.active = time.time()
    github.add(holder)
    presence.write_registry({"ana-web-lead": {"person": "ana", "folders": ["apps/web/"]}})
    as_lead(monkeypatch, "ana-web-lead")
    folders.borrow(config, argparse.Namespace(paths=["apps/api/"], card=[9], check=False, give_back=False))
    holder.lent = [{"to": "ana-web-lead", "paths": ["apps/api/"], "cards": [9]}]
    assert folders.settle(config, "ana-web-lead", [holder]) == ["sam-api-lead lent apps/api/ for #9"]
    assert not folders.mine("ana-web-lead")["asks"] and not folders.mine("ana-web-lead")["borrowed"]


def test_a_status_comment_keeps_only_well_formed_loans():
    status = lead(name="ana-api-lead")
    status.lent = [{"to": "ana-web-lead", "paths": ["apps/api/"], "cards": [3]}]
    text = presence.body(status).replace('"cards":[3]', '"cards":[3,"x",true]')
    parsed = presence.parse(text)
    assert parsed.lent == [{"to": "ana-web-lead", "paths": ["apps/api/"], "cards": [3]}]
    bad = presence.body(status).replace('"to":"ana-web-lead"', '"to":"Not A Name!"')
    assert presence.parse(bad).lent == []
    assert "- lends apps/api/ to ana-web-lead for #3" in presence.body(status)


# One owner for the rest of the repo


def test_one_lead_holds_the_rest_and_a_second_with_no_folders_is_refused(home, config, github, monkeypatch):
    owner = lead(name="sam-main-lead", person="sam")
    owner.active = time.time()
    github.add(owner)
    with pytest.raises(cli.ColonyError, match="sam-main-lead holds the rest of the repo, and one lead holds it"):
        cli.claim(config, argparse.Namespace(stream="launch", folders=[], person=None))
    assert cli.claim(config, argparse.Namespace(stream="launch", folders=["apps/site"], person=None)) == 0


def test_a_silent_rest_owner_hands_the_rest_to_the_next_claim_with_a_line(home, config, github, capsys):
    owner = lead(name="sam-main-lead", person="sam")
    owner.active = time.time() - 3 * HOURS
    github.add(owner)
    assert cli.claim(config, argparse.Namespace(stream="launch", folders=[], person=None)) == 0
    assert "over the rest of the repo" in capsys.readouterr().out
    assert any(line.startswith("for sam-main-lead: claimed: ana-launch-lead took the rest of the repo")
               for line in posted(github))
    alive, _, _ = presence.everyone(config)
    assert folders.rest_owner(config, alive) == "ana-launch-lead"  # the one that acts wins over the silent one


def test_a_lead_with_no_folders_that_does_not_hold_the_rest_takes_no_card(home, config, github, board, monkeypatch):
    for name, since in (("ana-launch-lead", 100.0), ("ana-walkfix-lead", 200.0)):
        status = lead(name=name)
        status.rest, status.since = True, since  # two from a race: the first claim holds the rest
        github.add(status)
    as_helper(monkeypatch, "builder-1", "ana-walkfix-lead")
    card_says(monkeypatch, github, "Folders: apps/web/")
    with pytest.raises(cli.ColonyError, match="ana-walkfix-lead holds no folders, and ana-launch-lead holds the rest"):
        take(config, 12)
    as_helper(monkeypatch, "builder-1", "ana-launch-lead")
    assert take(config, 12) == 0


def test_a_claim_may_take_a_silent_leads_folders_and_tells_it(home, config, github, capsys):
    quiet = lead(name="sam-api-lead", person="sam", folders=["apps/api/"])
    quiet.active = time.time() - 3 * HOURS
    github.add(quiet)
    assert cli.claim(config, argparse.Namespace(stream="api", folders=["apps/api/"], person=None)) == 0
    assert any("claimed: ana-api-lead took apps/api/, since you were silent" in line for line in posted(github))


def test_who_marks_a_silent_lead_and_its_loans(home, config, github, capsys):
    quiet = lead(name="sam-api-lead", person="sam", folders=["apps/api/"])
    quiet.active, quiet.lent = time.time() - 3 * HOURS, [{"to": "ana-web-lead", "paths": ["apps/api/"], "cards": [4]}]
    github.add(quiet)
    assert cli.main(["who"]) == 0
    out = capsys.readouterr().out
    assert "Folders: apps/api/; lends apps/api/ to ana-web-lead for #4. Silent for 180 minutes" in out


# Leads gone for days


def test_leads_gone_past_drop_after_hours_leave_the_registry_and_who(home, host, config, github, capsys):
    (host / ".colony" / "colony.toml").write_text(CONFIG + "\n[leads]\ndrop_after_hours = 24\n")
    config = cli.load_config()
    presence.write_registry({"ana-old-lead": {"person": "ana", "folders": ["apps/old/"]},
                             "ana-web-lead": {"person": "ana", "folders": ["apps/web/"]}})
    github.add(lead(name="ana-web-lead", folders=["apps/web/"]))
    github.add(lead(name="ana-old-lead", folders=["apps/old/"], at=time.time() - 30 * HOURS))
    github.add(lead(name="ana-api-lead", folders=["apps/api/"], at=time.time() - 2 * HOURS))
    with folders.changing() as data:
        data["seen"]["ana-old-lead"] = time.time() - 30 * HOURS
    assert folders.leads_command(config, argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "Dropped, gone for 24 hours or more: ana-old-lead." in out
    assert set(presence.registry()) == {"ana-web-lead"}
    assert cli.main(["who"]) == 0
    out = capsys.readouterr().out
    assert "Gone, no status in 15 minutes: ana-api-lead" in out and "ana-old-lead" not in out
    assert "And 1 gone for 24 hours or more, no longer listed." in out


def test_the_leads_settings_refuse_an_unknown_key_and_a_bad_value(home, host, config):
    for table, message in (("[leads]\nsilence = 5\n", "has no key 'silence'"),
                           ("[leads]\nsilent_minutes = 0\n", "silent_minutes is a number above 0")):
        (host / ".colony" / "colony.toml").write_text(CONFIG + "\n" + table)
        with pytest.raises(cli.ColonyError, match=message):
            cli.load_config()


# Worktrees inside the repo


def test_worktrees_default_to_a_folder_inside_the_main_checkout_from_any_worktree(home, host, monkeypatch):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG.replace('worktrees = "~/trees"\n', ""))
    commit_all(host)
    config = cli.load_config()
    assert config["project"]["worktrees"] == str(host / ".worktrees")
    folders.ready(config)  # as `colony worktree add` does: it makes the folder and keeps it out of `git status`
    tree = host / ".worktrees" / "demo-builder-1-3"
    subprocess.run(["git", "-C", str(host), "worktree", "add", "-q", "-b", "b/3", str(tree)], check=True)
    monkeypatch.chdir(tree)
    assert cli.load_config()["project"]["worktrees"] == str(host / ".worktrees")  # never nested in the worktree
    assert "/.worktrees/" in (host / ".git" / "info" / "exclude").read_text().splitlines()
    status = subprocess.run(["git", "-C", str(host), "status", "--porcelain"], capture_output=True, text=True)
    assert status.stdout == ""


def test_loading_the_config_writes_nothing_and_the_exclude_line_is_only_ever_appended(home, host, monkeypatch):
    """Regression: every config load could rewrite .git/info/exclude whole, which first empties it, so two commands
    starting at once could lose the person's own lines. Loading the config now writes nothing; folders.ready and
    `colony hooks install` add the line, appending it when it is missing and never rewriting the file."""
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG.replace('worktrees = "~/trees"\n', ""))
    commit_all(host)
    exclude = host / ".git" / "info" / "exclude"
    exclude.write_text("# the person's own\n*.local\nbuild/")  # no newline at its end
    config = cli.load_config()
    assert exclude.read_text() == "# the person's own\n*.local\nbuild/"
    monkeypatch.setattr(folders.Path, "write_text", lambda *args, **kwargs: pytest.fail("the file was rewritten"))
    folders.ready(config)
    assert exclude.read_text() == "# the person's own\n*.local\nbuild/\n/.worktrees/\n"
    folders.ready(config)
    assert exclude.read_text().count("/.worktrees/") == 1


def test_hooks_install_keeps_the_worktrees_folder_out_of_git_status(home, host):
    from colony import guards

    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG.replace('worktrees = "~/trees"\n', ""))
    commit_all(host)
    assert guards.install(cli.load_config(), argparse.Namespace(dry_run=False)) == 0
    assert "/.worktrees/" in (host / ".git" / "info" / "exclude").read_text().splitlines()


def test_worktree_add_makes_one_inside_the_folder_and_refuses_a_name_that_leaves_it(home, host, capsys):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG.replace('worktrees = "~/trees"\n', ""))
    commit_all(host)
    config = cli.load_config()
    assert cli.main(["worktree", "add", "next-1", "HEAD", "--detach"]) == 0
    assert capsys.readouterr().out.strip() == (host / ".worktrees" / "demo-next-1").as_posix()
    with pytest.raises(cli.ColonyError, match="is not a worktree name"):
        folders.worktree_path(config, "../escape")
    assert cli.main(["worktree", "path", "builder-2-9"]) == 0
    assert capsys.readouterr().out.strip() == (host / ".worktrees" / "demo-builder-2-9").as_posix()


def test_worktree_check_names_each_worktree_outside_the_folder_and_how_to_move_it(home, host, capsys):
    (host / ".colony").mkdir()
    (host / ".colony" / "colony.toml").write_text(CONFIG.replace('worktrees = "~/trees"\n', ""))
    commit_all(host)
    stray = home / "Desktop" / "demo-builder-1-5"
    subprocess.run(["git", "-C", str(host), "worktree", "add", "-q", "-b", "b/5", str(stray)], check=True)
    assert cli.main(["worktree", "check"]) == 1
    out = capsys.readouterr().out
    assert "1 worktree sits outside" in out and f"git worktree move {stray.resolve()}" in out
    config = cli.load_config()
    assert any("1 worktree sits outside" in line for line in folders.notes(config))


def test_a_worktrees_folder_outside_the_repo_is_named_once_a_day_when_the_lead_starts(home, config, github, capsys):
    from test_hi import hi

    out = hi(capsys)
    assert "[project] worktrees is" in out and 'set it to ".worktrees", inside the repo' in out
    assert "[project] worktrees is" not in hi(capsys)  # once a day
