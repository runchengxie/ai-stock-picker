---
title: "Did the first rule adjustment improve returns?"
summary: "We replayed a simple momentum and stability adjustment against the original numeric Top10."
date: 2026-07-16
language: en
slug: guarded
---

# Did the first rule adjustment improve returns?

English · [简体中文](../zh-CN/research/guarded.md)

## What we wanted to know

Could a simple momentum-and-stability rule improve the existing numeric Top10 without paying for AI calls?

## What we tried

Use January 15–July 15, 2026 historical candidates. Of 119 expected dates, 116 formed paired samples. June 30–July 2 had no qualified pools and remained missing.

The adjustment started from the numeric Top15, kept candidates close enough to the original relevance cutoff, then averaged trend, volume, intraday stability, and liquidity. Those choices were fixed before inspecting this replay's returns.

Signals were generated after the close, with entry at the next open. Holding periods were one, three, and five open-to-open sessions. Costs of 10, 20, and 50 bps per side were tested. The page shows the 20 bps case: 0.20% per buy or sell. **This replay made zero AI calls.**

## What happened

At 20 bps, the original rule returned -62.84%, -36.57%, and -27.23% for the three holding periods. The adjusted rule returned -65.47%, -37.85%, and -30.15%. It lost more in every case.

The initial report's average daily differences were -6.28, -1.68, and -3.42 bps/day. An independent review removed a shared cash-only tail that slightly diluted those averages. The corrected differences are **-6.4395, -1.7193, and -3.5671 bps/day**. The website uses those corrected averages and preserves the original figures in the downloadable source data.

One-way name turnover was 93.13% for the original rule and 92.96% for the adjustment—a reduction of about 0.17 percentage points, too small to be meaningful here.

## What we decided

Do not continue this version into future shadow testing or keep changing weights on this window. The main one-session result, consistency across time blocks, and five-session check failed.

## How to read it

Total return is the return over the whole replay. Average daily difference is the daily adjusted-rule return minus the original-rule return; it is not the total-return difference.

Candidates were reconstructed after the observation dates. In addition, 6,524 price-limit fields were missing on June 23–26 and were treated as not tradable. These results do not prove what could have been achieved in live trading at the time.

<details>
<summary>Technical source reference</summary>

The originals are retained in the private research archive. These fingerprints identify the versions used for this summary.

| Source file | SHA-256 |
| --- | --- |
| `hotsector-deepseek-challenger-v2-result-20260716.md` | `d7fb18cee8d47ebc9cd117a9f292663edc45781d797becb93353dbcac539dd76` |

</details>
