# Output Resolution by Ledger - Design

**Status:** agreed 2026-08-06

**Goal:** Resolve "the current version of an output" from the ledger that already records it, instead of from the highest number on disk.

## Why

`latest_output_path` takes a filesystem path, globs `stem_v*`, and returns the highest N. It never opens the database. Every agent input in the system resolves through it.

The database already knows the answer. `insert_agent_output_sync` does this on **every** write:

```sql
UPDATE agent_outputs SET is_current=0 WHERE project_id=? AND output_type=?
INSERT INTO agent_outputs (..., file_path, version, is_current) VALUES (?,?,?,?,?,1)
```

The row stores the **versioned** path, and `is_current` moves with it. `revert_to_version` maintains the same invariant - its docstring says plainly *"Sets the target version as is_current=1"* - so reverting to an older version repoints the ledger even though newer files remain on disk. That is precisely the case a filename-ordering scheme cannot express.

**So the registry already exists, is already correct, and is already maintained on both write and revert. Nothing consults it.**

### What that has cost, four times

| Incident | Effect |
|---|---|
| Clean-baseline prune (5 Aug) | Deleting rows of one type demoted `value_chain_summary` v12 to v4 and `value_chain_tree` v13 to v9, because a filename family was split across output types |
| `value_chain_tree_v13` (6 Aug) | A 15 July file shadowed run 22's v10; the tree everyone read was three weeks stale |
| `value_chain_summary_v12` (6 Aug) | Maya read the 15 July summary on **every run since 15 July**. It names *"DXI (Fleet maintenance subcontractor)"* - the party the human review of 4 August explicitly corrected out in favour of Fraikin. The correction was applied to the model and never reached the agent that needed it. |
| Version counter reset | Deleting every row of a type resets `MAX(version)`, so the next write starts at v1 and renames over an existing file |

Each was diagnosed and patched individually. There is even a `scripts/repair_registry_current.py` whose comment begins *"latest_output_path already resolves to on disk"* - someone met this before and fixed the instance.

The pattern is one defect: **two namespaces that look like one.** `agent_outputs` rows and `stem_vN` filenames both claim to say which version is current, and only one of them is maintained.

## The change

A new resolver reads the ledger first:

```python
def current_output_path(slug: str, output_type: str) -> Path | None:
    """The file the ledger marks current for this output type.

    Falls back to the disk glob only when the ledger has nothing to say - a first write
    before its row exists, a hand-written file, or a project predating versioning.
    """
```

`latest_output_path` stays, as that fallback and for callers that genuinely have only a path. It is no longer the answer to "what should this agent read".

**Resolution order:**

1. `agent_outputs` where `output_type = ?` and `is_current = 1` - if the row's `file_path` exists on disk, that is the answer.
2. If the row exists but its file does not, that is a **dangling ledger entry**: return `None` and record it. Silently falling through to the disk glob is what turned a broken pointer into a wrong answer.
3. If no row exists, fall back to `latest_output_path` - genuinely a first write or a hand-written file.

Step 2 is the load-bearing one. The current behaviour has no way to distinguish "no current version" from "the current version's file is missing", and the difference decides whether an agent should proceed.

## The prerequisite: one output type per filename family

`DeriveRegistryTool` writes `value_chain_registry_vN.json` with `output_type="state"` (`derive_registry.py:153`). `SQLiteStateTool` writes the same filename family with `output_type="value_chain_registry"`. Two writers, one family, two types.

That is why `state` legitimately carries two `is_current` rows, why `state` could never be pruned, and why the clean-baseline demotion happened at all. A resolver keyed on `output_type` would look up `value_chain_registry`, find the `SQLiteStateTool` row, and miss every registry the derive tool wrote.

**`DeriveRegistryTool` must write `output_type="value_chain_registry"`.** After that the type-to-family relationship is one-to-one, which is the invariant the resolver depends on. Existing `state` rows whose `file_path` names a `value_chain_registry` file are re-typed by migration; `state` rows naming other files are left alone.

This is a prerequisite, not a nicety. Without it the resolver returns confidently wrong answers rather than approximately right ones, which is worse than what we have.

## Call sites

**Eight calls across four modules** - counted as calls, not mentions, so the implementer knows the real surface:

| Module | Calls | Lines | Note |
|---|---|---:|---|
| `agents/tools/sqlite_state.py` | 5 | 59, 87, 122, 190, 307 | The read path, three current-artefact reads, and the post-write resolve at 307. Line 190 is merge-on-write, which reads *during* a write |
| `agents/tools/derive_registry.py` | 1 | 26 | `_latest_registry` |
| `api/routers/projects.py` | 1 | 494 | `list_interview_scripts` |
| `api/services/interview_answer_service.py` | 1 | 122 | |

`scripts/repair_registry_current.py` calls it zero times - it only names it in a comment, and is a candidate for deletion once the class is fixed rather than a call site to migrate.

### Two ordering hazards

**The rename window.** `insert_agent_output_sync` writes `{key}.json`, then renames it to `{key}_vN.json`, then inserts the row. Between rename and insert the ledger names no current file. Any resolve in that window must fall through rather than return `None`, so the resolver's fallback is not optional - it is what makes the write path safe.

**Merge-on-write reads mid-write.** `_merge_with_current` resolves the current artefact before the new one is written. It must see the *previous* version, never a partially written one. Resolving from the ledger makes this stricter and safer than the glob, which could see a half-renamed file.

## What this does not change

Version numbering, the `_vN` filename convention, `revert_to_version`, and the `is_current` sweep all stay exactly as they are. The ledger is already right; this only makes it authoritative.

Nor does it introduce a new table. A separate "current filename registry" would be a second thing to keep in step with `agent_outputs`, and two registries disagree in exactly the way one registry and a filename convention already do.

## Testing

- **Ledger wins over disk.** A project whose `is_current` row names `_v5` while `_v12` sits beside it resolves to v5. This is the `value_chain_summary` incident, as a test.
- **Revert is honoured.** After `revert_to_version` to an older version, the resolver returns the reverted file while the newer files remain on disk untouched.
- **A dangling row is not a wrong answer.** A row marked current whose file is absent returns `None` and records the fact, rather than falling through to a stale file.
- **First write.** No row yet, file on disk: falls back and finds it.
- **Rename window.** A resolve between rename and row insert does not raise and does not return a stale version.
- **One type per family.** After the migration, no filename family is claimed by two output types - asserted across every type, so a new writer that reintroduces the split fails a test rather than a demo.
- **Merge-on-write.** A merging write resolves the previous complete version, never a partial one.
- **`DeriveRegistryTool` re-typing.** A derived registry is recorded as `value_chain_registry`; pre-existing `state` rows naming registry files are migrated; `state` rows naming other files are untouched.

## Sequencing

Independent of the A+B and E plans, and safe to build alongside either. It should land **before** the first full Alex-to-Casey run that anyone intends to trust, because every agent input in that chain resolves through the function this replaces.

## Not in this spec

Changing the version-numbering scheme; content-addressed filenames; removing `latest_output_path` (it remains the documented fallback); and the `output_lineage` edges, which already record what a run read and are unaffected.
