"""colony board: the GitHub Project the cards live on, with five fields per card: Status, Lead, Helper, Size and
Last update.

`colony board init` makes the project from the repo's owner, titled `Colony: <project name>`, links it to the repo
and adds the five fields, keeping every field and option already there. `colony board set <card> field=value ...` adds
the card's issue to the board, sets the fields and stamps Last update; it refuses any other field, such as an old
board's State. `[board] number` in colony.toml names another project. The lead's wait reads the board for stale cards
through `cycle.stale_lines`, and `colony tidy` counts, closes and archives cards through `items`. Every computer's gh
login needs the project scope: `gh auth refresh -s project`.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone

from colony import cli, wait

STATUS = ("To do", "In progress", "In review", "Done")
SIZES = ("S", "M", "L")
DONE = "Done"
# The only fields the board holds, with their options, or None for a text field. The lead sets Status, Lead, Helper
# and Size, and every `colony board set` stamps Last update, so a helper's progress is a stamp that wakes no one.
FIELDS = {"Status": STATUS, "Lead": None, "Helper": None, "Size": SIZES, "Last update": None}
LAST_UPDATE = "Last update"
UPDATE_FORMAT = "%Y-%m-%d %H:%M UTC"
READ_FORMATS = (UPDATE_FORMAT, "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ")
COLORS = ("GRAY", "BLUE", "YELLOW", "GREEN", "ORANGE", "RED", "PINK", "PURPLE")
SCOPE_HINT = " (the gh login needs the project scope: gh auth refresh -s project)"

FIELDS_QUERY = """query($id: ID!) { node(id: $id) { ... on ProjectV2 { fields(first: 50) { nodes {
  ... on ProjectV2FieldCommon { id name dataType }
  ... on ProjectV2SingleSelectField { options { id name color description } }
} } } } }"""

ITEMS_QUERY = """query($id: ID!, $cursor: String) { node(id: $id) { ... on ProjectV2 {
  items(first: 100, after: $cursor) { pageInfo { hasNextPage endCursor } nodes { id
    content { ... on Issue { number url state title updatedAt closedAt }
              ... on PullRequest { number url state title updatedAt closedAt } }
    fieldValues(first: 30) { nodes {
      ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
      ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
    } } } } } } }"""


def utcnow() -> datetime:
    """The time now, in UTC; tests replace it."""
    return datetime.now(timezone.utc)


def squash(text: str) -> str:
    """A field or option name compared loosely: lowercase, without spaces, dashes or underscores, so `last_update`
    names Last update and `Todo` matches To do."""
    return re.sub(r"[\s_-]+", "", text.lower())


def stamp(at: datetime) -> str:
    """A Last update value, such as `2026-11-05 14:05 UTC`."""
    return at.astimezone(timezone.utc).strftime(UPDATE_FORMAT)


def read_stamp(text: str) -> datetime | None:
    """A Last update value as a UTC time, or None when it is empty or unreadable."""
    for form in READ_FORMATS:
        try:
            return datetime.strptime(text.strip(), form).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def title(config: dict) -> str:
    """The board's title: `[board] title`, else `Colony: <project name>`."""
    own = config.get("board", {}).get("title")
    return own if isinstance(own, str) and own.strip() else f"{cli.NAME.capitalize()}: {config['project']['name']}"


def owner(config: dict) -> str:
    """The login that owns the repo, and so the board."""
    return config["project"]["repo"].split("/")[0]


def _gh(*args: str) -> str:
    """One gh call for the board, whose error names the project scope it needs."""
    try:
        return wait.gh(*args)
    except cli.ColonyError as e:
        raise cli.ColonyError(f"{e}{SCOPE_HINT}") from None


def graphql(query: str, **variables: str) -> dict:
    """Run one GraphQL query or mutation through gh and return its data."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        args += ["-f", f"{name}={value}"]
    answer = json.loads(_gh(*args) or "{}")
    if not isinstance(answer, dict) or answer.get("errors") or "data" not in answer:
        raise cli.ColonyError(f"GitHub refused a board query: {json.dumps(answer)[:200]}{SCOPE_HINT}")
    return answer["data"]


def find_board(config: dict) -> dict | None:
    """The board as {number, id, url}: the project `[board] number` names, else the owner's open project with the
    board's title, else None."""
    login, number = owner(config), config.get("board", {}).get("number")
    if number:
        found = json.loads(_gh("project", "view", str(number), "--owner", login, "--format", "json"))
        return {"number": found["number"], "id": found["id"], "url": found.get("url", "")}
    listed = json.loads(_gh("project", "list", "--owner", login, "--format", "json", "--limit", "200") or "{}")
    for project in listed.get("projects", []):
        if project.get("title") == title(config) and not project.get("closed"):
            return {"number": project["number"], "id": project["id"], "url": project.get("url", "")}
    return None


def need_board(config: dict) -> dict:
    """The board, or an error that says to make it."""
    board = find_board(config)
    if board is None:
        raise cli.ColonyError(f"this repo has no board yet: run `{cli.NAME} board init`")
    return board


def fields(board: dict) -> dict[str, dict]:
    """The board's fields by squashed name, each with its id, name, dataType and, for a single select, its options."""
    nodes = graphql(FIELDS_QUERY, id=board["id"])["node"]["fields"]["nodes"]
    return {squash(node["name"]): node for node in nodes if node and node.get("name")}


def _option(opt: dict) -> str:
    """One single-select option as a GraphQL input literal."""
    known = f"id: {json.dumps(opt['id'])}, " if opt.get("id") else ""
    return (f"{{{known}name: {json.dumps(opt['name'])}, color: {opt['color']}, "
            f"description: {json.dumps(opt.get('description') or '')}}}")


def ensure_options(field: dict, wanted: tuple[str, ...]) -> bool:
    """Give a single-select field each wanted option, in order and spelled as wanted, and return whether it changed.

    An option already there keeps its id, color and description, so no card loses its value, and an option the
    list doesn't name stays at the end.
    """
    have = field.get("options") or []
    if [opt["name"] for opt in have[:len(wanted)]] == list(wanted):
        return False
    options, used = [], set()
    for i, name in enumerate(wanted):
        old = next((opt for opt in have if squash(opt["name"]) == squash(name) and opt["id"] not in used), None)
        if old:
            used.add(old["id"])
        options.append({**(old or {"color": COLORS[i % len(COLORS)], "description": ""}), "name": name})
    options += [opt for opt in have if opt["id"] not in used]
    mutation = ("mutation($field: ID!) { updateProjectV2Field(input: {fieldId: $field, singleSelectOptions: ["
                + ", ".join(_option(opt) for opt in options) + "]}) { projectV2Field { ... on ProjectV2FieldCommon "
                "{ id } } } }")
    graphql(mutation, field=field["id"])
    return True


def items(board: dict) -> list[dict]:
    """Every item on the board: its id, issue number, url, state (OPEN or CLOSED), title, updatedAt and closedAt, and
    its fields by squashed name."""
    found, cursor = [], None
    while True:
        page = graphql(ITEMS_QUERY, id=board["id"], **({"cursor": cursor} if cursor else {}))["node"]["items"]
        for node in page["nodes"]:
            content = node.get("content") or {}
            values = {squash(value["field"]["name"]): value.get("text", value.get("name")) or ""
                      for value in (node.get("fieldValues") or {}).get("nodes") or []
                      if value and (value.get("field") or {}).get("name")}
            found.append({"id": node["id"], "number": content.get("number"), "url": content.get("url", ""),
                          "state": content.get("state", ""), "title": content.get("title", ""),
                          "updatedAt": content.get("updatedAt", ""), "closedAt": content.get("closedAt", ""),
                          "fields": values})
        if not page["pageInfo"]["hasNextPage"]:
            return found
        cursor = page["pageInfo"]["endCursor"]


def init(config: dict, args) -> int:
    """`colony board init`: make the board, or find it, and give it every field with its options."""
    login, name, repo = owner(config), title(config), config["project"]["repo"]
    board = find_board(config)
    made = board is None
    if made:
        created = json.loads(_gh("project", "create", "--owner", login, "--title", name, "--format", "json"))
        board = {"number": created["number"], "id": created["id"], "url": created.get("url", "")}
        _gh("project", "link", str(board["number"]), "--owner", login, "--repo", repo.split("/", 1)[-1])
    have, added, changed = fields(board), [], []
    for field, options in FIELDS.items():
        found = have.get(squash(field))
        if found is None:
            cmd = ["project", "field-create", str(board["number"]), "--owner", login, "--name", field,
                   "--data-type", "SINGLE_SELECT" if options else "TEXT"]
            _gh(*cmd, *(["--single-select-options", ",".join(options)] if options else []))
            added.append(field)
        elif options and found.get("dataType") == "SINGLE_SELECT" and ensure_options(found, options):
            changed.append(field)
    print(f"{'made' if made else 'found'} the board {name}: {board['url']}")
    print(f"fields added: {', '.join(added) or 'none'}; options added: {', '.join(changed) or 'none'}")
    return 0


def parse_pairs(pairs: list[str]) -> list[tuple[str, str]]:
    """Read `field=value` arguments as (field, value) pairs; an empty value clears the field."""
    parsed = []
    for pair in pairs:
        field, sep, value = pair.partition("=")
        if not sep or not field.strip():
            raise cli.ColonyError(f"{pair!r} is not field=value, such as Helper=builder-2")
        parsed.append((field.strip(), " ".join(value.split())))
    return parsed


def edit_args(board: dict, item: str, field: dict, value: str) -> list[str]:
    """The `gh project item-edit` arguments that set one field of one item, or clear it for an empty value."""
    cmd = ["project", "item-edit", "--project-id", board["id"], "--id", item, "--field-id", field["id"]]
    if not value:
        return [*cmd, "--clear"]
    if field.get("dataType") == "SINGLE_SELECT":
        options = field.get("options") or []
        match = next((opt for opt in options if squash(opt["name"]) == squash(value)), None)
        if match is None:
            names = ", ".join(opt["name"] for opt in options)
            raise cli.ColonyError(f"{field['name']} has no option {value!r}: choose from {names}")
        return [*cmd, "--single-select-option-id", match["id"]]
    if field.get("dataType") == "TEXT":
        return [*cmd, "--text", value]
    raise cli.ColonyError(f"{field['name']} is a {field.get('dataType')} field; {cli.NAME} sets text and options")


def set_fields(config: dict, card: int, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Add the card's issue to the board and set each field, Last update to now unless given; return what was set.

    Every name and value is checked before the first write, so a typo changes nothing.
    """
    now = utcnow()
    pairs = [(field, stamp(now) if squash(field) == squash(LAST_UPDATE) and value == "now" else value)
             for field, value in pairs]
    if not any(squash(field) == squash(LAST_UPDATE) for field, _ in pairs):
        pairs.append((LAST_UPDATE, stamp(now)))
    known = {squash(field) for field in FIELDS}
    unknown = [field for field, _ in pairs if squash(field) not in known]
    if unknown:
        raise cli.ColonyError(f"the board has no field {unknown[0]!r}: choose from {', '.join(FIELDS)}")
    board = need_board(config)
    have = fields(board)
    missing = [field for field, _ in pairs if squash(field) not in have]
    if missing:
        raise cli.ColonyError(f"the board lacks the field {missing[0]!r}: run `{cli.NAME} board init`")
    url = f"https://github.com/{config['project']['repo']}/issues/{card}"
    checked = [(have[squash(field)], value) for field, value in pairs]
    for field, value in checked:
        edit_args(board, "", field, value)
    item = json.loads(_gh("project", "item-add", str(board["number"]), "--owner", owner(config), "--url", url,
                          "--format", "json"))["id"]
    for field, value in checked:
        _gh(*edit_args(board, item, field, value))
    return [(field["name"], value) for field, value in checked]


def set_command(config: dict, args) -> int:
    """`colony board set <card> field=value ...`: set a card's fields on the board."""
    done = set_fields(config, args.card, parse_pairs(args.pairs))
    print(f"#{args.card} " + ", ".join(f"{field}={value or '(cleared)'}" for field, value in done))
    return 0


def field_value(item: dict, field: str) -> str:
    """One field's value on a board item, or "" when it has none."""
    return item["fields"].get(squash(field), "")


def is_open_card(item: dict) -> bool:
    """Whether a board item is an open card: its issue is open and its Status is not Done."""
    return item.get("state") in ("", "OPEN") and squash(field_value(item, "Status")) != squash(DONE)


def last_touched(item: dict) -> datetime | None:
    """When a card last changed: its Last update, else its issue's own last change, else None."""
    stamped = read_stamp(field_value(item, LAST_UPDATE))
    if stamped is not None:
        return stamped
    try:
        return datetime.fromisoformat(item["updatedAt"].replace("Z", "+00:00")) if item.get("updatedAt") else None
    except ValueError:
        return None


def archive(config: dict, board: dict, item: str) -> None:
    """Archive one item off the board. It stays in the project's archive, and its issue is untouched."""
    _gh("project", "item-archive", str(board["number"]), "--owner", owner(config), "--id", item)


def card_number(value: str) -> int:
    """A card's issue number, such as 12 or #12."""
    if not value.lstrip("#").isdigit():
        raise argparse.ArgumentTypeError(f"{value!r} is not a card number, such as 12")
    return int(value.lstrip("#"))


def add_commands(sub) -> None:
    """cli.py's route to this module: `colony board init` and `colony board set`."""
    p = sub.add_parser("board", help="the GitHub Project the cards live on: init, or set a card's fields")
    board_sub = p.add_subparsers(dest="board_command", metavar="board-command", required=True)
    q = board_sub.add_parser("init", help="make the board from the repo's owner, with its fields")
    q.set_defaults(run=init)
    q = board_sub.add_parser("set", help="set a card's fields, such as Helper=builder-2; it also stamps Last update")
    q.add_argument("card", type=card_number, help="the card's issue number")
    q.add_argument("pairs", nargs="+", metavar="field=value",
                   help=f"fields: {', '.join(FIELDS)}; an empty value clears one, and Last update=now stamps it")
    q.set_defaults(run=set_command)
