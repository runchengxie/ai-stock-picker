# Selection Validation Receipt

`aipick validate` 默认保持现有向后兼容输出。下游需要可绑定到具体 selection 文件的机器验证凭据时，显式传入 `--validation-receipt`。

```bash
uv run aipick cn validate \
  --selection /absolute/path/selection.json \
  --candidates /absolute/path/candidates.json \
  --validation-receipt
```

如果同时提供 append-only evidence 目录：

```bash
uv run aipick cn validate \
  --selection /absolute/path/selection.json \
  --candidates /absolute/path/candidates.json \
  --evidence-dir /absolute/path/selection.json.evidence \
  --validation-receipt
```

## Receipt contract

当前 receipt：

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "ai_stock_selection_validation_receipt",
  "valid": true,
  "market": "CN",
  "selection_sha256": "<64 lowercase hex>",
  "selection_as_of": "2026-07-15",
  "prompt_version": "2026-07-29.1",
  "picks": 1,
  "validation_profile": "current_full",
  "prompt_hash_revalidated": true,
  "commentary_policy_revalidated": true,
  "response_sha256_verification": "format_only_raw_response_unavailable",
  "evidence_manifest_sha256": null
}
```

`selection_sha256` 直接对传给 owner validator 的 selection 文件原始字节计算，因此下游可以拒绝 receipt 与 selection 不匹配的组合。

提供 `--evidence-dir` 且 owner evidence 校验通过时：

- `response_sha256_verification` 为 `byte_exact_evidence`；
- `evidence_manifest_sha256` 为 evidence 目录中 `manifest.json` 的 SHA-256；
- owner validator 仍会先确认 evidence 内的 `selection.json` 与传入 selection 文件逐字节一致。

未提供 evidence 目录时，`evidence_manifest_sha256` 为 `null`。这表示 selection/candidate/prompt 等 owner contract 已复验，但原始 provider response 没有通过 byte-exact evidence 重新绑定。

## 信任边界

Receipt 只证明 owner validator 对**这份 selection 字节**执行并通过了声明的校验。它不会：

- 将 `strict_point_in_time=false` 升级为严格 PIT；
- 将 `eligible_as_oos_evidence=false` 升级为 OOS；
- 证明模型训练数据不存在未来信息；
- 代替外部可信时间戳；
- 将 customer commentary 包装成独立事实核验。

下游 adapter 必须重新计算 selection SHA-256 并与 receipt 比较。不能只检查 `valid=true`。

## 兼容性

不传 `--validation-receipt` 时，`aipick validate` 的原有 JSON 输出保持不变。Receipt contract 发生破坏性变更时应发布新的 `schema_version`，不能原地重解释 `1.0.0`。
