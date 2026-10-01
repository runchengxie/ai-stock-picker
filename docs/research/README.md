# Research notes: what we tried and what happened

English · [简体中文](../zh-CN/research/README.md)

The [results page](https://runchengxie.github.io/ai-stock-picker/) shows the comparisons. These notes explain them without requiring you to know the internal contract names.

| Question | Note |
| --- | --- |
| Does changing input order or hiding stock names change the answer? | [Model stability](stability.md) |
| Is Pro more useful than Flash? | [Model comparison](models.md) |
| Did the first rule adjustment improve returns? | [Six-month replay](guarded.md) |
| Did a revised numeric rule improve the outcome? | [Revised rules](numeric.md) |
| Can replacing fewer stocks reduce turnover? | [Turnover experiment](turnover.md) |
| Which daily records are available, and what do they prove? | [Daily observations](daily.md) |

Read each note in this order: the question, the setup, the result, and the next step. Exact names and source fingerprints are at the end.

These are summaries of archived July 2026 studies, reviewed for this website on October 1, 2026. The original reports and raw model responses are retained privately. The page publishes aggregate results, not raw candidate pools or credentials. Source filenames and content hashes let a source owner trace the summary back to its archive.

Later reconstruction means the candidate files cannot prove what was available at the historical time. Historical replay and an offline rehearsal are not a live track record or qualified out-of-sample evidence. The reviewed snapshot has no verified continuous daily series yet; this is a missing result, not a zero-return series.

For file formats and execution commands, use the [documentation index](../README.md). For data updates, see [Website maintenance](../showcase.md).
