---
title: "Is Pro more useful than Flash?"
summary: "We compared Flash and Pro on the same candidates to see whether the stronger model added useful stock choices."
date: 2026-07-16
language: en
slug: models
---

# Is Pro more useful than Flash?

English · [简体中文](../zh-CN/research/models.md)

## What we wanted to know

Would a different model provide useful choices rather than just better wording?

## What we tried

For six dates, Flash and Pro each saw three presentations of the same candidates: original order, shuffled order, and anonymous identities. Each model had 18 calls; the experiment made 36 calls without retries. The minimum was 17 fully usable results per model.

## What happened

Both models produced valid stock lists in all 18 calls. Explanations were the problem: **Flash passed 3/18 and Pro passed 7/18**. Pro improved by four calls, or 22.22 percentage points, but both missed the target.

On all six original-order dates, Flash, Pro, and the numeric rule chose **exactly the same ten stocks in exactly the same order**. Changing the model did not introduce a new ranking signal on those dates.

Shuffling shared an average of 9.33 stocks for Flash and 9.00 for Pro. Anonymous presentation shared 9.83 for Flash and 10.00 for Pro. Each comparison used all six valid pairs, and the overlap checks passed. That says the lists are similar, not that the models add profitable information.

Estimated cost was CNY 0.235918 for Flash and CNY 0.712788 for Pro. Mean latency was 10.891 and 19.116 seconds. Those are this experiment's estimates using the July 16, 2026 price schedule—not today's prices or an independently verified provider bill.

## What we decided

Stop after screening. The remaining 24 calls and the one-month return backtest were **not run**. No return result should be drawn for this experiment. The failed next-stage check is not a zero return.

Next research should give the model a narrower job, such as comparing close boundary candidates or identifying a specific risk. Test that task before considering a model switch.

## How to read it

Separate three things: the service returned text, the stock list passed, and the complete result including explanations passed. A valid list does not automatically make a result ready to publish. These findings apply to this frozen Prompt and sample; they are not a general comparison of all current model versions.

<details>
<summary>Technical source reference</summary>

The originals are retained in the private research archive. These fingerprints identify the versions used for this summary.

| Source file | SHA-256 |
| --- | --- |
| `hotsector-deepseek-v4-pro-month-v1-receipt-20260716.json` | `ea9e9fd4ca4d787987efbafd070de78f8c865ddb0bbf60361ea64512b8548e63` |
| `hotsector-deepseek-v4-pro-month-v1-result-20260716.md` | `c2abe19feed076c63326737e8c5d8f70106eb1c666cadc28a920a5222b8219b0` |

</details>
