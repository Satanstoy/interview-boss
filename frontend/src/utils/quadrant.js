// 四象限决策图：把「岗位热度 × 个人熟练度」映射到行动象限。
// 纯函数，无副作用，供 PracticeQuadChart.vue 和洞察总览使用。

// 熟练度阈值：average_score ≥ 60 视为「已掌握」
export const SKILL_THRESHOLD = 60

// 象限定义（key 对应 readiness items 的 status 归类）
export const QUADRANTS = {
  breakthrough: { key: 'breakthrough', label: '重点突破', hint: '高热度但没练好，最该优先补' },
  advantage: { key: 'advantage', label: '优势', hint: '高热度又熟练，面试的底气' },
  maintain: { key: 'maintain', label: '可保持', hint: '熟练但岗位热度低，保持手感即可' },
  lowPriority: { key: 'lowPriority', label: '不急', hint: '热度低也没练，暂时不用优先' },
}

/**
 * 把单个 readiness item 映射到四象限。
 * @param {{question_frequency:number, average_score:number|null}} item
 * @param {number} heatMedian  岗位热度中位数（区分高/低热度）
 * @returns {{quadrant:string, heat:number, skill:number, heatHigh:boolean, mastered:boolean}}
 */
export function mapToQuadrant(item, heatMedian) {
  const heat = item.question_frequency || 0
  const heatHigh = heat >= heatMedian
  // 未练/无分按 0 熟练度处理，落在「未掌握」一侧
  const skill = item.average_score ?? 0
  const mastered = skill >= SKILL_THRESHOLD

  let quadrant
  if (heatHigh && mastered) quadrant = 'advantage'
  else if (heatHigh && !mastered) quadrant = 'breakthrough'
  else if (!heatHigh && mastered) quadrant = 'maintain'
  else quadrant = 'lowPriority'

  return { quadrant, heat, skill, heatHigh, mastered }
}

/**
 * 计算一组 item 的岗位热度中位数（作为高/低热度分界）。
 * 空数组返回 0。
 */
export function heatMedian(items) {
  const heats = items.map(i => i.question_frequency || 0).filter(h => h > 0)
  if (!heats.length) return 0
  const sorted = [...heats].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}
