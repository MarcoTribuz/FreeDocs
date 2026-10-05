# The term list

A term list is an encrypted file of values that FreeDocs removes on every scrub
that uses it: client names, matter numbers, the code names of projects that do
not exist yet. These are strings no detector can be expected to find, because
they look like ordinary words, and a firm already has them written down.

It is the persistent form of the window's "add a value" control, and like that
control it can only **remove**. There is no way to write "never remove X" into
the list, and there will not be one: a standing exemption would apply to
documents nobody has read yet. The preview is still where a single occurrence is
kept.

```bash
cd engine
uv sync --extra restore          # the cipher; the same extra the key file needs
export FREEDOCS_TERMS_PASSPHRASE='a long passphrase'   # or --passphrase-file, or a prompt

uv run freedocs terms create firm.fdterms
uv run freedocs terms add firm.fdterms "Nordwind Holding" --entity ORGANISATION
uv run freedocs terms import firm.fdterms clients.csv   # then delete clients.csv
uv run freedocs scrub contract.docx -o out/ --terms firm.fdterms
```

## What it protects, and what it does not

| Protects against | Does not protect against |
|---|---|
| The file reaching a cloud sync folder, a backup or a shared drive | Malware running as you: it can read the passphrase as you type it, or read the unlocked list from the engine's memory |
| Another account on the same machine | Someone who has the passphrase |
| A stolen or discarded disk, with or without full-disk encryption | A plaintext export you made and kept (see [Export](#export)) |
| The file being attached to an e-mail by mistake | A weak passphrase: the minimum length and scrypt raise the cost of guessing, but they cannot make "12345678" strong |

Encrypted at rest, unlocked once per session. That is the whole claim, and
nothing else in this project should claim more.

The reason it is encrypted at all: owner-only permissions protect against
another account on the machine, and that is not where a firm's files go. They go
to OneDrive, SharePoint, iCloud and Dropbox, and to backups on disks nobody
encrypted. A plaintext client register in a synced folder is on somebody else's
servers whatever the file mode said.

## The file

`.fdterms`, recognisable in a listing and easy to put in `.gitignore`. It uses
the same envelope as the [key file](restore.md) — scrypt, AES-256-GCM, the
cleartext header bound as associated data — and it is not readable as one. Each
kind refuses the other by name ("is a key file, not a term list").

What someone without the passphrase can read from it: that it is a FreeDocs term
list, and the key-derivation parameters. **Not how many entries it holds**: the
header has no count, no name and no date, and the encrypted payload is padded to
blocks of 4 KiB, so the file size narrows the number down to about a hundred
entries at a time.

Every save is atomic: the new file is written beside the old one and renamed
over it, so a crash or a full disk leaves the previous list intact rather than
half of the new one.

## Entries

- An entry is matched **literally and case-sensitively**, as a substring:
  `Acme` also removes the `Acme` inside `Acmegraph`, and does not remove `ACME`.
  The preview shows exactly what an entry took out. Case-insensitive matching is
  deliberately not built yet; it needs a decision about which spelling the
  placeholder stands for.
- When two entries nest (`Acme` and `Acme Corp`), the longer one wins, whatever
  order they are in.
- Each entry has an entity type, `OTHER` by default. The type decides the
  placeholder family: `ORGANISATION` gives `[ORGANISATION_1]`, `OTHER` gives
  `[REDACTED_1]`.
- 2 to 500 characters, no line breaks or tabs, at most 10 000 entries. The last
  limit is measured: 10 000 entries against a 200-page document is 1.3 seconds a
  preview, and 500 entries is 65 ms.

A finding that came from the list is marked `terms` in the preview and in
`inspect`, so "the list removed this" can be told apart from "I removed this
just now" (`human`).

## Import

A one-way door. `terms import` (or Import… in the window) reads:

- **Plaintext**: one value per line, `#` starts a comment, and an optional
  `ENTITY<TAB>` prefix: `PERSON<TAB>Giulia Verdi`.
- **CSV** (by the `.csv` suffix): the value in the first column, an optional
  entity in the second, and a header row starting with `value` is skipped.

Afterwards FreeDocs tells you to delete the source file. **It never deletes the
file itself.** A plaintext copy beside the encrypted list undoes the encryption,
and deleting your file is not this tool's decision.

## Export

`terms export FILE OUTPUT` writes the list back out in the plaintext format
above, owner-only, and it imports back unchanged. It asks for confirmation (or
`--yes` where no terminal can ask), and it refuses to write over the list
itself. The exported file is not encrypted.

## In the report

The report carries two counts and no values:

```json
"terms": {"loaded": 50, "matched": 3}
```

`matched` counts entries that removed at least one occurrence. The entries that
did not match are **not** listed anywhere, not even among
`requested_values_not_found`: nearly every entry of a client register is absent
from nearly every document, and naming the absent ones would write the register
into every report. The section is absent when no list was used, so "not used"
cannot be read as "used and matched nothing".

## Command line

| Command | What it does |
|---|---|
| `freedocs terms create FILE` | a new, empty list; refused if `FILE` exists |
| `freedocs terms list FILE [--query Q]` | the entries, `ENTITY<TAB>value`, filtered ignoring case and accents |
| `freedocs terms add FILE VALUE... [--entity E]` | add and save; duplicates are skipped |
| `freedocs terms remove FILE VALUE...` | remove by exact value and save |
| `freedocs terms import FILE SOURCE` | add every entry of a plaintext or CSV file |
| `freedocs terms export FILE OUTPUT [--yes]` | write the list out **unencrypted** |
| `freedocs terms rekey FILE` | change the passphrase |
| `freedocs scrub ... --terms FILE` / `freedocs inspect ... --terms FILE` | use the list |

The passphrase comes from `--passphrase-file`, then `FREEDOCS_TERMS_PASSPHRASE`,
then a prompt. The key file has its own variable, so one cannot be used for the
other by accident. Where no terminal can prompt and neither is set, the command
stops with a usage error rather than scrubbing without the list. There is no
`--passphrase` argument, because a command-line argument ends up in the shell
history and in `ps`. `rekey` reads the new passphrase from
`--new-passphrase-file`, `FREEDOCS_TERMS_NEW_PASSPHRASE` or a prompt.

## Over the pipe

For the desktop app. Values travel in both directions over the local pipe, the
channel that already carries every matched value. No error carries a term or a
passphrase.

| Method | Params | Answer |
|---|---|---|
| `terms_create` | `path`, `passphrase` | `{path, count}`; refused if `path` exists |
| `terms_unlock` | `path`, `passphrase` | `{path, count}`; the terms stay in the engine |
| `terms_lock` | — | `{locked, was_unlocked}` |
| `terms_list` | `query?` | `{path, count, terms: [{value, entity}]}` |
| `terms_update` | `add?`, `remove?`, `passphrase` | `{path, count, added, removed}` |
| `terms_import` | `source`, `passphrase` | `{path, count, added, skipped, delete_source, notice}` |
| `terms_export` | `output` | `{output, count, warning}` |
| `terms_rekey` | `old`, `new` | `{path, count}` |

`inspect` and `scrub` take `use_terms: true`. With the list locked, that is an
`INVALID_REQUEST` and nothing is scrubbed: a scrub that quietly skipped the list
would produce a document you believe had the firm's names taken out.

The engine holds the unlocked list until `terms_lock`, `forget` with
`terms: true`, or the end of the session. A plain `forget` does not lock it: the
window forgets its documents after every batch, and locking the list then would
ask for the passphrase after every batch.

`terms_update` and `terms_import` re-read the file from disk with the passphrase
they are given before saving. That checks the passphrase belongs to this list (a
save under a mistyped one would re-key the list to a passphrase nobody knows),
and it merges changes another window saved in the meantime instead of
overwriting them.

## In the window

A term-list card on the file and review steps: Open… or New…, the passphrase
once, then search, add, remove, Import…, Export… and Change passphrase…. The toggle "remove these on
every scrub" is on as soon as the list is unlocked. The window keeps the
passphrase until you lock the list, because every save needs it; it never stores
it or the entries. See [the desktop app](desktop-app.md#the-term-list-in-the-window).

## Later, not now

The passphrase in the macOS Keychain or the Windows Credential Manager, so it is
never typed. The code is different on each platform, and the Windows build has
never been launched.
