# Phase 9.2.5 依赖审计策略

本目录只保存可 Review 的策略与合成测试夹具；每次 CI 产生的原始
`pip-audit`/`npm audit` JSON 和策略结果作为绑定 Git SHA/run ID 的 artifact 保存，
不提交到仓库。

- `python-policy.json` 固定 `pip-audit==2.10.1`、精确包版本/公告和有期限例外；
- `npm-policy.json` 固定 npm 11.6.2 production tree 的 10 个受影响包、5 个叶子公告、依赖路径和 Gate A 可达性；
- `npm-audit-fixture.json` 是去除非契约字段的合成测试夹具，不是某次 CI 的原始审计证据。

两个检查器均 fail-closed：审计报告缺失/损坏、公告或包集合增减、安装版本、
严重性、direct/range 分类变化、缺少 Review 字段或 2026-11-30 例外到期都会失败。
策略更新必须同时保留新的官方审计 JSON 作为 CI/Review 证据；不得用
`npm audit fix --force`、降低 severity 门槛或扩大例外来让门禁变绿。
