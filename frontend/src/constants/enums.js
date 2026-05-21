/**
 * 应用枚举常量
 */

/** 题库模式 */
export const BANK_MODE = Object.freeze({
  PUBLIC: 'public',
  PERSONAL: 'personal',
  MIXED: 'mixed',
})

/** 难度等级 */
export const DIFFICULTY = Object.freeze({
  L1: 'L1',
  L2: 'L2',
  L3: 'L3',
})

/** 难度标签映射 */
export const DIFFICULTY_LABEL = Object.freeze({
  L1: '基础',
  L2: '中等',
  L3: '困难',
})

/** Tab 名称 */
export const TAB = Object.freeze({
  JD: 'JD',
  INTERVIEW: 'Interview',
  MASTER_BANK: 'MasterBank',
  MOCK_INTERVIEW: 'MockInterview',
  KNOWLEDGE_GRAPH: 'KnowledgeGraph',
  IMPORT: 'Import',
})

/** 排序方式 */
export const SORT = Object.freeze({
  FREQUENCY_DESC: 'frequency_desc',
  FREQUENCY_ASC: 'frequency_asc',
  DIFFICULTY_ASC: 'difficulty_asc',
  DIFFICULTY_DESC: 'difficulty_desc',
  NEWEST: 'newest',
  OLDEST: 'oldest',
})
