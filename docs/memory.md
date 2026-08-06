# Memory and context management

Agent Hive keeps memory outside the conversation so a fresh worker receives only relevant context. The local store defaults to `.hive/memory.json`.

## Memory shapes

| Need | Representation |
| --- | --- |
| Short-term or session context | `session` or `mission` scope with a TTL. |
| Cross-run project knowledge | `project` scope and an explicit namespace. |
| People, systems, or products | `kind: entity`; extraction is intentionally not automatic. |
| Contextual recall | Scope/namespace plus role, trust, sensitivity, minimum score, and result limit. |
| Shared worker knowledge | `team` scope with `*` or selected role visibility. |
| Private worker scratch memory | `agent` scope; its namespace is the default role visibility. |
| Stateful flow | Mission plan, usage ledger, audit events, and distilled keeper memory. |

## Retention and poisoning controls

Retention combines recency, confidence, relevance, source quality, verified utility, reuse, and sensitivity. Untrusted memories start with lower source quality and utility. Only verified successful reuse can reinforce a record. TTL and half-life decay cool, archive, or delete stale records. Sensitive records above `0.5` are excluded from ordinary queries.

These are deterministic filters, not semantic retrieval. The MVP does not embed content, infer entities, encrypt the file, or authenticate namespaces. A multi-user product requires tenant-isolated encrypted storage and server-side authorization.

## Examples

```powershell
python .\hive.py memory put --scope team --namespace mission-42 `
  --kind decision --content "Migration uses the existing adapter" --trusted `
  --visibility builder --visibility guard

python .\hive.py memory query --scope team --namespace mission-42 `
  --role guard --trusted-only --minimum-score 0.6 --limit 5

python .\hive.py memory decay
python .\hive.py memory delete --scope mission --namespace mission-42
```
