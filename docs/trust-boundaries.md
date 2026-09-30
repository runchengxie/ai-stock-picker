# Time and evidence boundaries

English · [简体中文](zh-CN/trust-boundaries.md)

The tool records the relationship between input, Prompt, model response, and output. These records help inspect a run, but their proof has limits.

## Dates

- `candidate_observation_date`: the market observation day represented by the data.
- `selection_as_of`: the signal date supplied by `--as-of`.

The observation date may precede the signal date, but cannot follow it. A common workflow is:

```text
Day D: closing data becomes available
Day D or D+1: generate the candidate pool
Day D+1: select using --as-of=D+1
```

## Generation status (`temporal_status`)

| Value | Meaning |
| --- | --- |
| `contemporaneous` | Generated on the signal date in the market's time zone, with no detected inversion where the candidate manifest is later than the result |
| `retrospective_simulation` | Generated after the signal date; suitable for replay or research, not a real same-day signal |

`contemporaneous` describes date relationships only; it is not strict historical-existence proof.

## Assurance (`point_in_time_assurance`)

| Value | Meaning |
| --- | --- |
| `signal_date_only` | Supported A-share contract with observation day, cutoff, and generation time; still lacks external publication receipts or strict historical-existence proof |
| `unverified` | Generic JSON or CSV whose timing contract cannot be confirmed |

Self-reported input fields cannot upgrade assurance.

## Fixed limits

All selections include:

```json
{
  "strict_point_in_time": false,
  "eligible_as_oos_evidence": false
}
```

A hash identifies content, not its historical existence time. The upstream rotation data lacks verified publication receipts; candidate files alone cannot establish out-of-sample validity. Pools rebuilt after the observation date are not qualified out-of-sample results. The details are recorded in `evidence_limitations`.

## What hashes can prove

The record includes hashes for the input, candidate symbol set, Prompt, and raw provider response. They can detect content changes, identify the materials behind a result, and compare inputs across runs.

They cannot prove historical publication time, tradability, out-of-sample validity, or future profitability.

## Trading limits

The upstream value `execution_not_before=next_trading_session` is recorded as supplied. This project has no exchange calendar or execution module, so it does not verify:

- The actual next trading day, holidays, or temporary closures.
- Data availability at the open.
- Suspensions or price limits.
- Fill prices, slippage, transaction costs, or executable quantities.

An independent execution or backtesting system must supply trading-level evidence.

## How to describe results

Treat the output as a constrained model-ranking record. Real runs retain original candidates, full numeric ranking, exact Prompt and parameters, sanitized HTTP information, raw response, requested and actual model identity, extracted model text, rejection details for malformed responses, final selection, timing, and file hashes.

Research reports should also document the command, external publication receipts, and subsequent evaluation method. Without these, avoid presenting a reproducible run as strict historical investment evidence.
