---
title: "Did the revised numeric rule do better?"
summary: "We compared a revised scoring rule and a retention buffer with earlier numeric selections."
date: 2026-07-17
language: en
slug: numeric
---

# Did the revised numeric rule do better?

English · [简体中文](../zh-CN/research/numeric.md)

## What we wanted to know

The first adjustment failed. Could a revised score reduce losses, and could retaining yesterday's holdings inside the current Top15 reduce turnover?

## What we tried

On the same January 15–July 15, 2026 window, compare the original numeric rule, the Top30 candidate pool held equally, a revised rule, and the revised rule with a Top15 retention buffer.

The revised score used relevance 10%, daily confirmation 30%, intraday stability 20%, liquidity 25%, and trend 15%, with fixed overheating penalties. The retention buffer kept yesterday's stocks only if they were still in today's revised Top15, then filled the remaining Top10 slots.

Signals, next-open entry, holding periods, and modeled costs matched the previous replay. This revised idea was proposed **after seeing earlier replay results**, so it is a retrospective follow-up, not a new unseen test.

## What happened

At 20 bps and three sessions, total returns were -36.57% for the original rule, -31.01% for equal-weight candidates, -25.66% for the revised rule, and -24.21% with the buffer. Losses were smaller, but every variant still lost money at every tested holding-period/cost combination.

For one session, the revised rule returned -59.30%, still below equal-weight candidates at -58.61%. The buffer returned -58.22%. Estimated daily improvements relative to the original rule had intervals crossing zero, so this window does not establish a reliable advantage.

The buffer reduced one-way name turnover from 96.35% to 94.87%—1.48 percentage points. That was still higher than the original rule's 93.13%. The revised ranking shared only 3.87 of the original Top10 names on average: it did change selection, without establishing reliable usefulness.

## What we decided

Do not automatically promote the revised rule or keep scanning buffer sizes on the same history. Improvements need a genuinely later test and complete execution inputs.

## How to read it

Losing less is an improvement within this comparison, not a profitable strategy. Missing prices and price-limit fields were not evenly distributed across variants. Execution data was marked incomplete, so differences cannot all be attributed to ranking quality.

<details>
<summary>Technical source reference</summary>

The originals are retained in the private research archive. These fingerprints identify the versions used for this summary.

| Source file | SHA-256 |
| --- | --- |
| `hotsector-numeric-v2-retrospective-receipt-20260717.json` | `ca83705e68d158b9d4f21ec1d1443b09c1b0c6dce79e5271428f668aef69c850` |
| `hotsector-numeric-v2-retrospective-result-20260717.md` | `6bb5c2979e66e72626b17522a837493fd33fc5a0106d0543b2009b26aadf6bcc` |

</details>
