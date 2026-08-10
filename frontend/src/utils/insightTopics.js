const NON_REFERENCE_TOPIC_NAMES = new Set([
  '其他',
  '未分类',
  '其他/未分类',
  '未分类(API漏标)',
])

/** 兜底分类没有稳定岗位语义，不应进入能力雷达。 */
export function isReferenceTopic(name) {
  const normalized = String(name || '').trim()
  return Boolean(normalized) && !NON_REFERENCE_TOPIC_NAMES.has(normalized)
}
