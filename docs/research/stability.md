# Does changing the input change the answer?

English · [简体中文](../zh-CN/research/stability.md)

## What we wanted to know

If a model is making a useful decision from the numbers, simply moving a stock higher in the input list should not dominate its choice. Hiding a stock's real identity should also be a useful check.

## What we tried

We froze candidate pools for 20 dates. For each date, we made five calls: original order, three shuffled orders, and anonymous symbols/names. That makes 100 calls, with no retries. Responses identified the actual model as `deepseek-v4-flash`.

Before calling the model, the experiment required at least 95 fully usable results. “Fully usable” means the stock list and its explanations passed the checks—not just that the network request succeeded.

## What happened

Only **34 of 100** calls passed. The remaining 66 were rejected during selection validation. The original order passed 6/20, the shuffled setups passed 6/20, 5/20, and 11/20, and the anonymous setup passed 6/20.

The usable original/shuffled comparisons shared an average of 8.89 of the 10 selected stocks, but there were only 9 valid pairs. The original/anonymous comparisons shared 9.00 stocks, but there were only 2 valid pairs. These small subsets are not enough to offset the failed overall reliability check.

Only one date met the requirement that all three shuffled setups share at least seven selections with the original; the requirement was 15 dates. The 95% interval for dependence on input position was `[-0.100067, -0.010193]`, just outside the required `[-0.10, 0.10]` interval. The first-row lift check passed, with upper bound `-0.164901` against a maximum of `0.10`. One passed check does not reverse the overall failed decision.

Most rejections involved unsupported concepts (24), risk sentences not tied to candidate fields (22), or unsupported themes (12). The remaining eight involved trading advice, external/future claims, field binding, missing schema fields, or reversed stability meaning.

## What we decided

Do not promote this experiment or pay for a full 116-day model replay. First align the Prompt with the explanation checks, then register a new experiment. Preserve the old results rather than rerunning until they pass.

## How to read it

This tests response usability and sensitivity to input presentation. It does not test investment returns. High overlap means two lists are similar; it does not mean either list earns money. The 34 usable outputs shared 9.29 stocks on average with the original numeric Top10.

<details>
<summary>Technical source reference</summary>

The originals are retained in the private research archive. These fingerprints identify the versions used for this summary.

| Source file | SHA-256 |
| --- | --- |
| `hotsector-deepseek-stability-v1-receipt-20260716.json` | `fd15405d028dd988bcf53902f21a8c28c16b4e40ea7376f7ab2d44dbe6e526bb` |
| `hotsector-deepseek-challenger-v2-result-20260716.md` | `d7fb18cee8d47ebc9cd117a9f292663edc45781d797becb93353dbcac539dd76` |

</details>
