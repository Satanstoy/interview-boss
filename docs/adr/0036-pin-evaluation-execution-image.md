# ADR-0036: Eval Release 自动绑定不可变执行镜像

**Status:** accepted

正式 Eval Run 不直接运行工作区当前源码，也不把可变的 `latest` 镜像标签作为唯一版本依据。Release Manifest 创建或发布时自动记录实际执行所需的 Git SHA、Docker image digest 和配置摘要；Eval Run 只引用已锁定的 Release Manifest。

不同执行角色分别记录其运行绑定：

- Eval Target 的执行镜像或代码 Artifact；
- Simulator Harness/Eval Worker 的执行镜像；
- Candidate Simulator 如果运行在容器内，则记录其镜像，否则记录模型、Prompt 和配置摘要；
- Judge 如果运行在容器内，则记录其镜像，否则记录 Judge Release。

管理员只选择 `target_release` 和其他已发布 Release，不手工填写 digest。系统在 Release 创建、发布和 Eval Run 创建时校验引用完整性；如果只有可变标签而没有解析出的 digest，允许开发环境探索，但不得进入正式 Fixed Benchmark 或版本门禁。
