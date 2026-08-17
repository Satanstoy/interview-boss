# ADR-0010: 评测结果必须绑定不可变 Judge Release

**Status:** superseded by ADR-0043 and ADR-0044

每次评测运行必须记录实际使用的 Judge 配置，至少能够追溯裁判模型及其评测 Prompt、量规和采样配置。Judge 配置属于 Evaluation Release 的内部配置，不再作为管理员单独维护的公开 Release。Benchmark Case 可以保持裁判无关，只定义输入和预期行为；评测运行创建时解析并固定完整 Evaluation Release。更换 Judge 后必须创建新的 Evaluation Release，新结果不得直接与旧结果混合；需要时可以对同一原始产物重新裁判，以识别裁判漂移。
