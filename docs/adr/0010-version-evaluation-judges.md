# ADR-0010: 评测结果必须绑定不可变 Judge Release

**Status:** accepted

每次评测运行必须记录实际使用的 Judge Release，至少能够追溯裁判模型及其评测 Prompt、量规和采样配置。Benchmark Case 本身保持裁判无关，只定义输入和预期行为；评测运行解析并固定具体 Judge Release。更换 Judge 后产生的新结果不得直接与旧结果混合，只有在相同 Judge Release 下才可进行严格的分数趋势和版本回归比较；需要时可以对同一原始产物重新裁判，以识别裁判漂移。
