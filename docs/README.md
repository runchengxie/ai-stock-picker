# Documentation

English · [简体中文](zh-CN/README.md)

Start with the [project README](../README.md): install the tool, then run the sample without an API key. These guides are organized by what you want to do next.

## Research results, in plain language

Start with the [research results page](https://runchengxie.github.io/ai-stock-picker/) and the [online experiment notes](https://runchengxie.github.io/ai-stock-picker/research/stability/). The source notes are also available in [English](research/README.md) and [Chinese](zh-CN/research/README.md).

## Everyday use

| I want to… | Read |
| --- | --- |
| Configure keys, choose options, or resolve an error | [Usage guide](usage.md) |
| Prepare my candidate file | [Input formats](input-formats.md) |
| Understand the result JSON | [Output format](output-artifact.md) |
| Try the bundled samples | [Examples](../examples/README.md) |

## Research and integration

| I want to… | Read |
| --- | --- |
| Check inputs, prompts, responses, and file integrity | [Evidence and stability](evidence-and-stability.md) |
| Run repeated, anonymous, or controlled experiments | [Research guide](shadow-research.md) |
| Understand what the record can prove | [Time and evidence boundaries](trust-boundaries.md) |
| Validate a result in a downstream system | [Validation receipt](validation-receipt.md) |

## Development and maintenance

- [Architecture](architecture.md): execution flow and module responsibilities.
- [Development](development.md): environment, quality checks, and tests.
- [Website and publishing](showcase.md): Astro preview, translations, snapshot checks, and GitHub Pages.

English is authoritative. Chinese translations are reference material. Update both languages when changing CLI options, environment variables, input or output formats, default models, styles, timing semantics, development commands, or Python support. Keep the project README focused on first use; put field contracts and internal details here.
