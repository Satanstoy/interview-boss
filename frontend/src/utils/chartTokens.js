/**
 * 图表色彩 token —— porcelain 青瓷蓝阶（lieflat-charts 法典 · color-presets.js PORCELAIN 移植）
 * 规则：同一页面只锁一套色彩系统；明度即数据（最重要 = 最深蓝）；
 * 一律实心（无渐变/发光/阴影）；面积编码必须 sqrt。
 */
export const PORCELAIN = {
  light: {
    bg: '#F7F2EB',
    card: '#FFFFFF',
    txt: '#081F5C',
    muted: 'rgba(8,31,92,.60)',
    label: 'rgba(8,31,92,.72)',
    grid: 'rgba(8,31,92,.12)',
    track: 'rgba(8,31,92,.12)',
    quiet: 'rgba(8,31,92,.15)',
    data: '#334EAC',
    data2: '#7096D1',
    faint: '#BAD6EB',
    faint2: '#D0E3FF',
    hero: '#081F5C',
    tooltipBg: 'rgba(255,255,255,.95)',
    tooltipBorder: 'rgba(8,31,92,.20)',
    tooltipText: '#081F5C',
  },
  dark: {
    bg: '#081F5C',
    card: '#0F2B66',
    txt: '#EDEFF1',
    muted: '#BCC7D7',
    label: '#D5DBE2',
    grid: 'rgba(237,239,241,.14)',
    track: 'rgba(237,239,241,.12)',
    quiet: 'rgba(237,239,241,.12)',
    data: '#D5DBE2',
    data2: '#9EB3CD',
    faint: '#6C93C7',
    faint2: '#4D82C6',
    hero: '#EDEFF1',
    tooltipBg: 'rgba(8,31,92,.95)',
    tooltipBorder: '#3472C2',
    tooltipText: '#D5DBE2',
  },
}

/** 取当前主题下的 porcelain token */
export function porcelain(dark) {
  return dark ? PORCELAIN.dark : PORCELAIN.light
}

/** 共享 tooltip 配置（porcelain 换肤） */
export function porcelainTooltip(dark, trigger = 'item') {
  const t = porcelain(dark)
  return {
    trigger,
    confine: true,
    backgroundColor: t.tooltipBg,
    borderColor: t.tooltipBorder,
    textStyle: { color: t.tooltipText, fontSize: 12 },
  }
}

/**
 * 蓝阶明度梯（由浅到深）：0 = 最浅，4 = 最深。
 * 用于有序数据（难度/排名/状态档位）——明度即数据。
 */
export const RAMP = ['#D0E3FF', '#BAD6EB', '#7096D1', '#334EAC', '#081F5C']

/** 暗色下的蓝阶明度梯（由浅到深，暗卡上用） */
export const RAMP_DARK = ['#4D82C6', '#6C93C7', '#9EB3CD', '#D5DBE2', '#EDEFF1']

/** 取第 n 档（越靠后越深；越重要的数据用越大的 index） */
export function rampLevel(index, dark, max = 5) {
  const arr = dark ? RAMP_DARK : RAMP
  return arr[Math.min(Math.max(Math.round(index), 0), max - 1)]
}

/** ECharts 动画：quarticOut 统一缓动 */
export const EASE = { animationDuration: 900, animationEasing: 'quarticOut' }
