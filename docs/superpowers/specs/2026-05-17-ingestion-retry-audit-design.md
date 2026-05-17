# Ingestion Retry Audit Design

Date: 2026-05-17
Status: Approved in chat
Scope: Close the remaining audit gap for `POST /api/v1/ingestion/jobs/{job_id}/retry` by adding explicit success, denied, and conflict audit events without changing retry mechanics.

## Context

The ingestion reliability hardening slice added retry/re-dispatch for existing queued or failed runs and verified the runtime behavior locally. The remaining gap is audit coverage: the API contract says every security-relevant action emits audit events, and retry is security-relevant because it re-triggers background processing on an ACL-protected document/run.

Current state:

- ingestion list emits audit events
- ingestion get emits audit events
- ingestion retry performs the action but does not emit a retry-specific audit event

This is a small but important contract-compliance gap.

## Decision

Add explicit retry audit coverage at the existing route/repository boundary.

Use three retry-specific audit outcomes:

1. `ingestion.job.retry`
2. `ingestion.job.retry.denied`
3. `ingestion.job.retry.conflict`

Keep retry mechanics in the service layer and keep audit persistence in repository helpers, matching the current ingestion list/get pattern.

## Design

### 1. Boundary

- `api/routes/ingestion.py` remains responsible for HTTP outcome mapping.
- `services/ingestion_service.py` remains responsible for retry behavior.
- `repositories/ingestion.py` gains retry-specific audit helpers.

This keeps the slice small and consistent with the current structure.

### 2. Audit outcomes

#### Success: `ingestion.job.retry`

Written when:

- the caller is authorized to the run
- the run is in a retryable state
- retry preparation succeeds
- dispatch is attempted

Suggested details:

- `job_id`
- `document_id`
- `previous_status`
- `resulting_status`

#### Denied: `ingestion.job.retry.denied`

Written when:

- the run does not exist, or
- the run exists but is not visible through ACL

Suggested details:

- `job_id`
- `reason: not_found_or_denied`

This intentionally avoids leaking whether the run exists.

#### Conflict: `ingestion.job.retry.conflict`

Written when:

- the caller is authorized to the run
- but the run is in a non-retryable state such as `running` or `completed`

Suggested details:

- `job_id`
- `document_id`
- `current_status`
- `reason: non_retryable_status`

### 3. Request flow

```text
POST /api/v1/ingestion/jobs/{job_id}/retry
  -> require documents:write
  -> ACL-scoped run lookup
  -> if not found/denied:
       write ingestion.job.retry.denied
       return 404
  -> try retry preparation
  -> if state invalid:
       write ingestion.job.retry.conflict
       return 409
  -> dispatch existing run
  -> write ingestion.job.retry
  -> return refreshed run payload
```

### 4. Error-handling rules

- **404 path** stays non-leaky.
- **409 path** is explicit and auditable.
- **success path** records who retried which run and what state transition was requested.

### 5. Testing

Add integration coverage for:

- successful retry writes `ingestion.job.retry`
- denied/not-found retry writes `ingestion.job.retry.denied`
- retrying a completed or running run writes `ingestion.job.retry.conflict`
- existing retry response behavior remains unchanged

## Non-goals

- cancel endpoint audit coverage
- generalized audit refactor across all ingestion endpoints
- parser/OCR/quality-report expansion

## Acceptance criteria

- retry now satisfies the API contract’s audit requirement
- no retry response semantics regress
- audit payloads are specific enough for investigation without leaking protected existence details

## Risks

- If retry auditing is implemented inconsistently with list/get patterns, ingestion audit semantics become harder to reason about.
- If conflict auditing is omitted, operators lose visibility into repeated invalid retry attempts.

## Outcome

After this slice, ingestion retry is contract-compliant with explicit audit coverage for success, denial, and conflict outcomes.
