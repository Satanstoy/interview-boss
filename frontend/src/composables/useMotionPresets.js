/**
 * Motion 预设 — 声明式动画配置复用
 *
 * 提供一组常用的入场/出场动画预设，搭配 @vueuse/motion 的 v-motion 指令使用。
 * 所有预设都尊重 prefers-reduced-motion（通过 CSS media query 兜底）。
 *
 * 用法：
 *   <div v-motion-fade-visible> ... </div>
 *   <div v-motion="{ initial: presets.fadeUp.initial, enter: presets.fadeUp.enter }"> ... </div>
 */

/** 淡入 */
export const fade = {
  initial: { opacity: 0 },
  enter: { opacity: 1, transition: { duration: 300, easing: 'ease-out' } },
}

/** 淡入 + 上移 */
export const fadeUp = {
  initial: { opacity: 0, y: 16 },
  enter: { opacity: 1, y: 0, transition: { duration: 350, easing: [0.25, 0.46, 0.45, 0.94] } },
}

/** 淡入 + 下移 */
export const fadeDown = {
  initial: { opacity: 0, y: -12 },
  enter: { opacity: 1, y: 0, transition: { duration: 300, easing: 'ease-out' } },
}

/** 淡入 + 左移 */
export const fadeLeft = {
  initial: { opacity: 0, x: -16 },
  enter: { opacity: 1, x: 0, transition: { duration: 300, easing: 'ease-out' } },
}

/** 弹性缩放入场（Modal / Popover） */
export const pop = {
  initial: { opacity: 0, scale: 0.85 },
  enter: {
    opacity: 1,
    scale: 1,
    transition: { duration: 300, easing: [0.34, 1.56, 0.64, 1] },
  },
}

/** 从底部滑入（Toast / Notification） */
export const slideBottom = {
  initial: { opacity: 0, y: 24 },
  enter: { opacity: 1, y: 0, transition: { duration: 350, easing: 'ease-out' } },
}

/**
 * 生成 stagger 子元素入场的 transition.delay
 * @param {number} index - 子元素索引
 * @param {number} baseDelay - 基础延迟（ms）
 */
export function staggerDelay(index, baseDelay = 60) {
  return index * baseDelay
}

/**
 * 卡片列表 stagger 预设
 * @param {number} index - 卡片索引
 */
export function cardStagger(index) {
  return {
    initial: { opacity: 0, y: 20 },
    enter: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 350,
        delay: staggerDelay(index),
        easing: [0.25, 0.46, 0.45, 0.94],
      },
    },
  }
}
