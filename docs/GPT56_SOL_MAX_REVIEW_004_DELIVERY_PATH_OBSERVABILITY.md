# GPT-5.6-sol Max Thinking review 004 — Delivery-path observability

**Reviewer:** GPT-5.6-sol, Max Thinking

**Fable 5:** not used.

**Verdict:** **APPROVED FOR XCODE AND PHYSICAL-DEVICE QA**

## Scope

- persist successful Watch delivery path;
- distinguish direct HTTPS from iPhone fallback;
- display the path in Watch history;
- expose only the latest bounded path through aggregate iPhone diagnostics;
- preserve compatibility with existing outbox files.

## Decision

Physical-device testing must observe the actual route rather than infer it. A two-value enum is persisted:

```text
direct_https
iphone_fallback
```

No hostname, endpoint, request body, secret, device ID, or error detail is stored in this field.

## Security and privacy

Approved:

- the value is bounded by a Swift enum in the outbox;
- Watch diagnostics accept only the two known raw values;
- the iPhone displays a localized label;
- aggregate diagnostics still contain no capture text;
- no new network capability or credential is introduced;
- public documentation uses no private hostname.

## Reliability

Approved:

- direct `OutboxDeliveryService` records `.directHTTPS` only after a safe response;
- fallback records `.iPhoneFallback` only after the iPhone returns a safe response with matching request ID;
- failed/pending items do not claim a successful route;
- retry can replace a prior failure with the route that actually succeeded;
- legacy JSON without `last_delivery_path` decodes with `nil`;
- existing items remain visible.

## UX

Watch history presents concise labels:

```text
Directo
vía iPhone
```

The iPhone diagnostics present:

```text
Directo HTTPS
vía iPhone
```

This is sufficient for QA without crowding the primary capture flow.

## Evidence

```text
HermesCore: 13 tests, 0 failures
legacy outbox decode: passed
direct path persistence: passed
fallback path persistence: passed
shared diagnostic contract: typecheck passed
Apple UI sources: parse passed
```

## Conditions

1. Regenerate the Xcode project and build version 0.3.1 (4).
2. Verify a direct simulator capture displays `Directo`.
3. Force direct-network failure with iPhone fallback enabled and verify `vía iPhone`.
4. Refresh iPhone Watch diagnostics and verify the same latest route.
5. Repeat on physical paired devices.
6. Keep writes disabled.

## Conclusion

The change is low-risk, privacy-preserving, backward-compatible, and necessary to interpret physical networking behavior accurately.
