# Security and privacy

Applies to every model call that reads outside text, every token and secret the product holds, the workflows that build it, and every route, table, and page that reads, keeps, or describes a user's data, in `{service}`, `{web_app}`, and `.github/workflows/`, and to every person and agent who writes or reviews one. The reviewer checks each line against the diff. Outside text is any text that reaches the product from someone other than the user, such as a mail, a calendar invitation, a shared document, or a web page.

## Model calls and outside text

- The implementer must give a model call that reads outside text no tool that writes, sends, or deletes.
- The implementer must count only that missing tool as the control that stops an injected action, because a prompt instruction or a classifier can be talked around.
- The implementer must hand the model outside text only inside a tool result that carries its source label.
- The implementer must strip hidden styling, comments, script and style blocks, and off-screen text from outside HTML before a model reads it.
- The implementer must build a model's instructions only from text in one prompt module, and give an agent its prompt through the framework's instructions setting.
- The implementer must read a conversation's past, and resume a paused tool call, only from what the store holds for that conversation.
- The implementer must check the account's permission and the record's revision again when a paused or queued action runs.
- The implementer must build an approval card's words from the command's fields alone, and must make a preview send no write and no outside call.
- The implementer must write a fact about the user to a model's memory only through a typed proposal the user approves.
- The implementer must write a value that drives the product's automatic decisions only from its own job or the user's own control, never from a model that read outside text.
- The implementer must fetch an address that a user or a message supplied only through one guarded fetch helper that refuses inside addresses and redirects to them.
- The implementer must register every path that carries a user's text out of the product in one register, with its gate, before that path opens.
- The implementer must import the agent framework and the provider client only inside one boundary package, and keep every framework class inside it.
- The implementer must call a model provider only through the endpoints its data retention terms cover, when the product promises those terms to users.
- The implementer must change a model setting only in one versioned configuration object, which sets caching and every call's output cap.
- The implementer must pass a usage limit to every agent run, and must set each tool's retry budget from one constant.
- The implementer must record a model call's usage when its stream stops early, and must not leave a started call without a usage row.
- The implementer must commit a finished turn to the store before the stream sends its last event.
- The implementer must keep the tool definitions, the instructions, and the per-user block byte-identical between two requests of one conversation, so the provider's prompt cache holds.
- The implementer who changes an agent's settings, tools, or instructions must assert the bytes of the provider request in a test.
- The implementer of a change to a model's prompts or tools must run the direct and indirect prompt injection cases of the evaluation set, each case repeated.

## Tokens and secrets

- The implementer must store every provider token sealed under a credential key, and keep it out of every log line and job argument.
- The implementer must seal every health, credential, and mail field under a key the key service holds, and keep every data key wrapped.
- The implementer must make every session or bearer value the product hands out at least 32 random bytes from a secure source, such as Python's `secrets` module, and must keep only its SHA-256 hash in the store.
- The implementer must keep every provider token and every session value out of browser storage and out of every answer body the browser reads.
- The implementer must start every provider connection's authorization with a PKCE challenge of method S256.
- The implementer must verify a webhook's sender and signature before the handler parses, decrypts, or stores its body.
- The implementer must accept an authenticator code only for the current or the previous 30-second step, and only once per enrollment.
- The implementer must start the error reporter with its logging integration off, so no log record reaches it.
- Every person and agent must keep `.env` values, keys, tokens, and passwords out of all output, files, and commits.

## Workflows

- The implementer must set a workflow's top-level `permissions` to read, and grant a write only on the job that needs it, because every step of a job holds its token.
- The implementer must not trigger a workflow on `pull_request_target` or `workflow_run`, and must pass event text to a `run` step only through an environment variable, because such a job holds the repository's secrets.
- The implementer must pin every action a workflow uses to a full commit SHA with its version in a comment.
- The implementer must install dependencies in a workflow only from the lockfile, such as with `uv sync --locked` or `npm ci`.
- The implementer must reach a cloud account from a workflow only through OIDC and a role to assume, never a stored key.
- The implementer must give every workflow job a `timeout-minutes` limit.

## Account data

- The implementer must give every table that holds an account's rows an `account_id` foreign key with `ON DELETE CASCADE` and an index that leads with it, and delete an account's rows only through that cascade.
- The implementer must enable and force row security with one account policy on every table that holds an account's rows.
- The implementer must check the caller's right to act inside every route and every `SECURITY DEFINER` function.
- The implementer must read the user's switch for a kind of data, and the account's AI permission, again inside the transaction that keeps that data or sends it out.
- The implementer must keep every record of a class the product promises to keep from models out of every model call, its title among them.
- The implementer must derive a health status, a condition, or a mood only from data the user declared as health data.
- The implementer must trust a forwarded client address only from the networks the settings name, never from every address.
- The implementer must add only a column that a feature reads, and record its purpose and its retention period in the data map in the same change.
- The implementer must declare a retention pass beside every store whose data map row states a period.
- The implementer must write an access log entry in the same transaction as every staff read of a user's data, and refuse the read when the entry fails.
- The implementer must let a person read data that a provider's terms restrict, such as Google user data, only through a support grant and its access log entry.
- Every person and agent must keep data that a provider's terms restrict inside the product, and train no model on it.
- The implementer must request only the scopes the scope register lists for a connection, and add a scope to the register only with the person's approval.
- The implementer must show the data a connection reads and its use right before the consent button, and keep that disclosure in place until the user acts.
- The implementer must build every tool schema and output schema from code alone.
- The implementer must fit every learned value from one account's own records inside that account's transaction.
- The implementer must check an uploaded file's type and size against the stored bytes before a parser or a model reads it.
- The implementer must not describe the product as end-to-end encrypted, zero-knowledge, on-device, private by design, or federated on any page or in any message unless it is, as the code shows.

## Why it exists

A product that reads mail, invitations, and web pages that strangers wrote acts with the user's authority when one injected instruction reaches a tool which writes, sends, or deletes. A provider token in a plain column, a log line, or browser storage exposes every account it connects, and a weak or stored-in-the-clear session value lets anyone sign in as the user. An account table that misses its key, its forced row security, its retention pass, or its access log entry leaks one user's rows to another, keeps them after deletion, or breaks a provider's terms for its data. A workflow with an unpinned action or a stored cloud key hands the repository's secrets to whoever controls that action or reads that key.

## What is exempt

- Code that already broke a line before the line arrived, until the change that fixes it lands. A change to that code must not add a second instance of the same break.
