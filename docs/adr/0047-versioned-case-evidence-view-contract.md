# 版本化 Case Evidence View 契约

**Status: accepted (2026-08-20)**

评测控制台不直接依赖 Target Adapter 的原始 Observation 或数据库 JSON，而由后端提供带 `Evidence Contract Version` 的稳定 Case Evidence View。该视图统一承载冻结 Case 输入、Harness/Target Observation、确定性断言、Judge 结果、Attempt 和 Artifact；前端只依赖这一展示契约，目标类型差异放在版本化的 target payload 中。

这样可以让 Target Adapter 和数据库内部结构继续演进，同时保证 Run 详情与人工 A/B 使用同一份可复核证据。破坏性字段变化必须升级证据契约版本，并保留历史 Run 的旧版本解释能力。

## 约束

- 公共外壳固定描述 `run`、`item`、`case`、`execution`、`observation`、`scoring`、`attempts` 和 `artifacts`。
- 目标专属 payload 固定分为 `output`、`trace`、`metrics`，并拥有独立的 `payload_schema_version`。
- 公共字段使用稳定英文命名；执行、契约、Hard Gate、Judge 和质量状态分别建模。
- 初始目标 Payload 注册表覆盖 `interview`、`experience_extraction`、`jd_extraction`、`resume_analysis` 和 `question_tagging`。
- 管理员可以查看脱敏后的 Harness 私有上下文，但必须和候选人可见输入分区展示。
- 后端 Pydantic 响应模型是 API 权威契约，前端在边界使用 Zod 校验；契约不兼容必须显式报错。
- Run 列表只返回摘要；完整 Case Evidence View 按 Case 按需加载，人工 A/B 必须复用同一视图。
- 正式 Case 证据入口为专用 Evidence API；旧 Item 接口在迁移窗口内保持兼容。
- 历史 Run 通过 legacy normalizer 归一化；无法恢复的字段必须显式标记不可用，不得伪造。
- 原始 Observation 作为不可变 Artifact 保存，结构化 DTO 只返回主要证据和 Artifact 元数据。
- Target、Hard Gate、Judge 等证据区独立表达可用性，部分失败不得隐藏已成功的证据。
- 前端所有证据页面通过统一 API/normalizer 读取，禁止组件直接猜测原始 JSON 路径。
- 进度分布由后端按 Evaluation Release 的质量阈值计算 `passed`、`poor`、`failed`、`pending`；前端只渲染颜色、数量、百分比和筛选入口。
- 不同目标类型分别计算质量分布；Experiment 父级不得把不同目标的质量门槛混成一个结论。
- 管理员主入口是唯一的评测结果工作台；原“测评可视化”只作为结果工作台的汇总视图，不再与评测结果并列成两个主页面。
- 结果工作台首屏按失败、不佳、通过、未完成/处理中分区展示质量结论和 Harness 分布；失败和不佳优先呈现，通过内容可以降级或折叠。版本与评测集、运行控制、批量历史和人工 A/B 通过现有评测侧栏入口进入，不在结果首屏重复堆叠。
- 版本与发布和 Benchmark 属于同一配置上下文，统一进入“版本与评测集”工作区，同时展示 Target Release、Evaluation Release、Harness/Candidate Simulator 与 Benchmark Suite，避免管理员在两个页面间拼接评测上下文。
- 结果工作台的主要中文文案必须是贴近业务的人话；`Contract`、`Hard Gate`、`Judge`、`tool_metrics` 等内部术语不能作为管理员首要结论。可以在括号或高级详情中保留技术名，但主文案必须直接说明 Harness 检查的业务含义。
- 每个主界面指标至少展示业务名称、当前值、单位和状态；阈值可以用简短形式就近展示，完整定义、判定依据和异常解释通过 Tooltip 或详情查看。这些语义由后端目标 Payload 注册表提供，前端不自行猜测或堆叠解释性文案。
- 初始文案示例：`Contract` 显示为“输出格式与内容要求”，`Hard Gate` 显示为“硬性要求”，`Judge` 显示为“固定质量评审”，工具相关指标显示为“工具使用效果”，意图相关指标显示为“用户意图理解效果”。
- 指标缺失、尚未完成或不适用必须显示业务可理解的原因（例如“评测尚未完成”“该目标不检查工具使用”），不能只显示空白、内部枚举或 `[object Object]`。
- 实现前先冻结五类 target 的目标指标字典，包含核心指标、中文名称、单位、阈值、状态语义、展示顺序和主/次级层级；每个 target 首屏最多展示 3–5 个核心指标。
- Harness 执行表现和 Target 业务结果分成两个可识别的结果层，不以一个不可解释的混合总分替代；Case 列表只突出主要失败原因，完整原因保留在 Case Evidence View。
- 原始 JSON 证据保留为折叠的审计入口或 Artifact 引用，不作为主要展示契约。
- 新增可选字段保持兼容；破坏性变化升级 `schema_version` 或 `payload_schema_version`，历史 Run 继续使用旧版本解释。
