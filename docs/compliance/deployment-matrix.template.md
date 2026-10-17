# Deployment-specific processor and transfer matrix

这是部署实例级证据模板，不是对所有 InterviewBoss 部署的统一事实声明。
每次上线、替换 provider、变更 region 或变更 retention policy 时复制一份并由
责任人复核。禁止填写 API key、access token、个人简历、面经原文或其他 secret；
没有证据的字段必须写 `UNKNOWN — owner/action/date`，不能用供应商默认值代替。

## Instance record

| Field | Value / evidence |
|---|---|
| Deployment instance | `<instance-name>` |
| Operator / legal entity | `<self-hosted operator legal name>` |
| Deployment region | `<country / region>` |
| Data controller / owner | `<team or legal entity>` |
| Effective date | `<YYYY-MM-DD>` |
| Evidence owner | `<name/team>` |
| Privacy notice | [`privacy-policy.md`](privacy-policy.md) plus the instance URL |
| Secret / personal data fields | `REDACTED — never place credentials or samples here` |

## Provider record

| Provider slot | Provider legal entity | Processing purpose | Data categories | Region / cross-border transfer mechanism | Retention period | Deletion method | Subprocessor version | Owner |
|---|---|---|---|---|---|---|---|---|
| LLM / OpenAI-compatible endpoint | `<legal entity or self-hosted>` | `<purpose>` | `<JD/interview/resume fields>` | `<region + transfer mechanism>` | `<period>` | `<API/data deletion procedure>` | `<version/date or N/A>` | `<owner>` |
| Search provider | `<legal entity or none>` | `<answer enrichment>` | `<query text / metadata>` | `<region + transfer mechanism>` | `<period>` | `<provider deletion + local cleanup>` | `<version/date or N/A>` | `<owner>` |
| Embedding provider | `<legal entity or self-hosted>` | `<vectorization>` | `<field categories; no raw secret>` | `<region + transfer mechanism>` | `<period>` | `<provider deletion + local vector cleanup>` | `<version/date or N/A>` | `<owner>` |

## Responsibility boundary

- Self-hosted means the operator owns infrastructure access control, backups,
  retention, deletion, incident response, and any model endpoint operated inside
  that boundary.
- An OpenAI-compatible endpoint is only a protocol shape. It does not establish
  that OpenAI is the provider, where data is processed, or how long it is kept.
  Record the actual legal entity and evidence for the configured endpoint.
- User-configured endpoints are deployment data flows. The operator must review
  the endpoint before enabling it and update this matrix when it changes.
- Link the completed instance record from the deployed privacy notice; do not
  describe configurable providers as a single fixed vendor fact.

## Review checklist

- [ ] Legal entity and DPA/transfer evidence reviewed.
- [ ] Data categories match the enabled features and exclude credentials.
- [ ] Retention and deletion were verified with a dry-run or provider evidence.
- [ ] Subprocessor list/version was captured on the effective date.
- [ ] Incident contact and escalation owner are recorded.
- [ ] The completed record contains no secret or personal sample data.
