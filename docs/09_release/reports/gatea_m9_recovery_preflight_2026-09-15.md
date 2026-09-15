# M9 恢复候选 E：前置检查与精确模式绑定

> 2026-09-15；Gate A 仍为 No-Go。本文只记录仓库修复与验证，不是现场 stage、迁移或发布成功证据。

## 1. 基线与历史证据边界

主开发分支已到 M15（审计时 HEAD `ec4c06831c684a65084926def2d89a3bbd6dca73`），而 Gate A 发布器仍要求精确 M0–M9。恢复候选从 D `ab7b8d2875264c384f2d02bf48ddf4d38607c180` 建立独立分支 `codex/m9-gatea-recovery`，保留 M9 业务和迁移树；不得删除主分支的 M10–M15 文件来伪装兼容。PR base 仍须满足发布器的 `develop` 契约，并复核最终 merge target 的真实文件树。

用户交接记录提供的 D 结果如下（本轮尚未重新向 GitHub 或 Gate A 核验）：

- head：`ab7b8d2875264c384f2d02bf48ddf4d38607c180`；merge target：`c88771f0bdf651e8ea3ca43df30f3cc741640f5c`。
- Run `34664987914`、attempt `1`，required Jobs 为 9/9。
- 真实 stage 在完整 provenance、第二次 blocker scan 后因 operations 模式契约不一致失败；发生于 D pending、Image、Release 写入前。
- 原交接确认 D 输入与 staging 已清理，D Release/stage Record/pending/Image 均不存在；S/A/B、三个冻结 digest 不变，A/M9 五服务健康。以上是历史交接结论，不替代下一次现场只读核验。
- S 为 finalized/current M7 lineage；live 为 A/M9；A acceptance failure 和 B prepared retirement pending 继续受保护。不得重跑 D 或复用其 Run/artifact 作为 E 证据。

## 2. 根因及最小修复

Git 中 `gatea_operations.py` 为 `100755`。Git archive 的原始权限会受归档配置影响；安全解压既有规则将有执行位的普通文件规范化为 `0755`，无执行位为 `0644`。旧加载器固定要求 `0644`，而旧测试按扩展名生成归档，把 Python 文件统一做成 `0644`，掩盖了问题。

E 在解压时同时冻结 operations SHA-256 与规范化后的精确模式。完整 GitHub provenance 后，加载器只接受冻结模式为 `0644` 或 `0755`，并按该值调用原 stable no-follow reader；当前模式必须精确相同。root:root、普通非 symlink 文件、nlink=1、O_NOFOLLOW、读取前后文件身份与内容摘要检查均保留。不修改归档、不现场 chmod、不接受宽泛的权限集合。

顺序保持：安全解压 → archive/launcher/artifact 身份验证 → 完整 GitHub provenance → 第二次 blocker scan → 完整 source manifest → exact-bytes/exact-mode loader → predecessor takeover → 再次 source manifest → candidate pending / Image build / Release install。

新增模式只在 stage 内传递，不扩展持久 Record schema；v1/v2 行为和 v3 对 A failure、B stage、B prepared 三份 digest 的绑定保持不变。私有模块继续按对象身份在 finally 清理。

## 3. 快速前置门槛

新增 `scripts/ci/check_gatea_source_contract.py`，仅依赖标准库和 Git：

- 只读取指定 commit 的 Git 树及源码常量，不执行候选 Python；
- 比较 migration step、operations 和 upgrade 的支持范围；
- 核验批准链编号连续、Git 中迁移文件集合精确匹配；集合比较不依赖两位数文件名的词典序；
- 输出 operations Git 模式和预期解压模式；
- 明确输出 `deployment_evidence=false`，不能替代 provenance、真实 loader、CI 或现场预检。

从仓库根目录执行：

```sh
python3 -B scripts/ci/check_gatea_source_contract.py
```

它检查不可变 HEAD，未提交改动需由单元测试验证，提交后再检查最终 SHA。M9 恢复基线通过；M15 主开发分支在该 M9 门槛下预期拒绝。CI 在既有 updater Job 安装依赖之前运行此检查；依赖就绪后用 root 执行真实 Git archive loader 回归，再进入完整 updater。不改 required Job 身份或 9-Job 契约。

测试归档默认保留 Git 执行位；隔离 subprocess 使用 `-I -B`，通过显式测试 harness 替代网络/Docker 边界，不借助 PYTHONPATH。该 harness 结果不冒充完整现场 provenance。另以真实 archive 和真实 operations 模块验证 Linux/root 加载，不替代完整 takeover/acceptance 演练。

## 4. 验证策略与当前进度

- 已先用真实 Git 模式复现旧加载器的 `0755` 拒绝。
- 定向覆盖：两种合法模式、双向模式漂移、非法模式、symlink/FIFO/硬链接、内容漂移、加载及 context 异常、私有模块与字节码清理。
- candidate 与源码预检合计 `238 passed in 5.28s`；其余 Release `806 passed in 19.32s`；其余后端 `2122 passed, 39 skipped in 155.89s`。三组无重叠，合计 `3166 passed, 39 skipped`；39 项需要独立 MySQL 环境，不能计作通过。修订 root CI 的精确 Git safe.directory 后，真实归档用例另行 `1 passed`。
- 真实 Linux/root 一次性容器通过真实归档加载和模式漂移拒绝，未修改宿主源码或连接任何数据库；容器退出并复核不存在。当前本地 Docker 为 ARM64，因此该检查不冒充远端 AMD64 updater 演练。
- 本轮完整本地后端覆盖通过上述分组完成，不连续重复已被覆盖的专项套件。仓库卫生与差异检查通过；远端完整 required CI 仍是独立门槛。
- E 尚未取得自身远端 9/9、artifact、stage、retirement、adoption、acceptance、resilience、Backup/Restore 或 finalize 证据，不提前标记通过。

## 5. 后续执行顺序

先冻结 E 并取得其自身 CI/artifact，再重新核对现场 S/A/B、三个 digest、目录权限及五服务。通过后才进入受控 takeover、新 A/M9 Backup/Restore、M9→M9 零迁移 adoption/replay、E acceptance/resilience、数据后恢复与 finalize；新阻塞仍须停止写入并保留受保护 journal。

M9 收口后单独扩展 M9→M15：批准链及整数排序、Schema 检查、旧数据保护摘要、新表 Backup/Restore、正式入口验收、逐条 DDL 部分失败恢复。M10–M15 不能通过更改 `TARGET_VERSION` 或复用 M9 摘要规则直接上线。真实微信支付、小程序码、共享/预发布/生产均不在本轮范围。
