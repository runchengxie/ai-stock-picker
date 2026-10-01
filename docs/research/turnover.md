# Can fewer replacements solve high turnover?

English · [简体中文](../zh-CN/research/turnover.md)

## What we wanted to know

If we replace at most two of ten stocks each time, can we keep turnover low without retaining unsuitable old holdings?

## What we tried

Use 107 consecutive sessions from January 15–June 29, 2026. The sample stops before three later ranking gaps; missing signals are not treated as exchange holidays.

Test three- and five-session rebalance schedules, ordinary retention rules, and a cap of two new stocks per rebalance. Costs are modeled at 0.20% per side. This is a portfolio schedule test, unlike the separate daily-selection sleeves in the earlier replay.

## What happened

The uncapped baseline replaced about 98% of names at each rebalance. Capping new stocks lowered that to 20%, but only by keeping many names after they left the current candidate pool: **74.12%** of holdings on average for the three-session schedule, and **73.46%** for five sessions.

Mean total returns across schedule offsets were -18.10% for the three-session baseline and -8.03% with the cap. Five-session results were -21.69% and -8.74%. Every setup remained negative.

A simple retention buffer and small relevance margin barely changed turnover. The apparent success of the cap therefore depends on carrying old candidates, rather than showing that the current pool became stable.

## What we decided

Before testing a replacement budget again, reevaluate old holdings using current data in a wider eligibility pool. Keep them only if they still qualify. If too few signals remain, use an execution model that can genuinely represent cash rather than forcing full investment.

## How to read it

Name turnover is the share of stock names replaced per rebalance; it is not realized trading volume. Returns here are averages across different starting rebalance offsets, not daily-return means and not directly comparable to the previous sleeve-based replay.

There were no actual orders or fills. Actual execution fields are unavailable, and the 0.20% cost is an assumption. A stock leaving the candidate pool is not automatically untradable; it means the current selection process no longer includes it.

<details>
<summary>Technical source reference</summary>

The originals are retained in the private research archive. These fingerprints identify the versions used for this summary.

| Source file | SHA-256 |
| --- | --- |
| `hotsector-low-turnover-retrospective-receipt-20260718.json` | `45fe6541c07a086819cd0fbe3a1003c3bc38dcaa4e6682b22ca6cffdccd83d95` |
| `hotsector-low-turnover-retrospective-result-20260718.md` | `d784d739939aae86330975970be9a259a5027fb1a28e01094fdbebe50872acbb` |

</details>
