# Telemetry naming and cardinality

The single naming convention for KnowHub backend telemetry, applied from the
first span so that later milestones' telemetry is queryable alongside the
foundation's rather than diverging per package (M00-SPEC-003 R13).

## Attribute names

Use an **OpenTelemetry semantic convention** wherever one applies — HTTP,
database, messaging and runtime attributes all have standard names, and using
them means standard tooling understands KnowHub telemetry without
configuration.

Where no standard attribute fits, use the **`knowhub.` namespace** with
dot-separated lowercase segments naming the domain concept:

```
knowhub.correlation_id
knowhub.application.id
knowhub.source.revision
```

Never invent a second spelling of a standard attribute, and never abbreviate
a name that a semantic convention spells out.

## Resource attributes

Set at bootstrap, on every signal: `service.name` and
`deployment.environment.name`. Both come from configuration.

## Span names

A span name describes the **operation**, not the instance:

| Good | Bad |
|---|---|
| `GET /healthz` (route template) | `GET /applications/7f3a…` |
| `knowhub.foundry.compose` | `knowhub.foundry.compose:run-8821` |

## Cardinality

**Never use an unbounded or caller-controlled value as a metric label or a
span name** (M00-SPEC-003 R15). Identifiers, paths containing values, user
input and free text belong in span *attributes*, where they are bounded by
the span, not in the name or the label set — an unbounded label set makes a
metric unqueryable and expensive long before it makes it wrong.

Labels must come from a small, enumerable set: an outcome, a status class, a
named stage.

## What must never be emitted

The content rule lives with configuration and secret handling: no secret,
resolved credential, token, connection string, authorization header, cookie
or session identifier, in any attribute, log field, metric label or error
message.

When an operation fails, mark the span failed with a safe message and the
correlation identifier. That is enough to locate the failure; the detail
belongs in the system that holds the data, not in the trace.

## Log records

Every record carries `correlation_id`, and `trace_id`/`span_id` when a span is
active. Records are structured JSON objects with fixed field names — never
interpolated strings, because interpolation is how secrets reach logs
unnoticed. Extra fields are passed through `extra=`, not formatted into the
message.
