# 题库区域面积诊断报告

生成时间: 2026/5/12 22:46:32
测试工具: Playwright

---

## 1. 多视口尺寸测量结果

| 视口 | 状态 | 面板尺寸 | 滚动区尺寸 | 滚动区CSS高度 | 面板/视口% | 滚动区/视口% | Tab高 | 卡片数 | 卡片均高 |
|------|------|---------|-----------|-------------|----------|------------|-------|--------|---------|
| mobile-375x812 | ✓ | undefinedxundefined | undefinedxundefined | undefined | null% | null% | -px | - | -px |
| tablet-768x1024 | ✓ | 744x936 | 718x782 | 782px | 88.5% | 71.4% | 42px | 247 | 154px |
| laptop-1366x768 | ✓ | 1054x680 | 1020x564 | 564px | 68.3% | 54.8% | 46px | 247 | 125px |
| desktop-1920x1080 | ✓ | 1498x992 | 1464x876 | 876px | 71.7% | 61.8% | 46px | 247 | 124px |
| 2k-2560x1440 | ✓ | 1498x1352 | 1464x1236 | 1236px | 54.9% | 49.1% | 46px | 247 | 124px |

### 关键发现

**tablet-768x1024:**
- 面板 overflow: hidden 可能裁剪内容
- 内容溢出: scrollHeight(38013) > clientHeight(782)

**laptop-1366x768:**
- 面板 overflow: hidden 可能裁剪内容
- 内容溢出: scrollHeight(30953) > clientHeight(564)

**desktop-1920x1080:**
- 面板 overflow: hidden 可能裁剪内容
- 内容溢出: scrollHeight(30546) > clientHeight(876)

**2k-2560x1440:**
- 面板 overflow: hidden 可能裁剪内容
- 内容溢出: scrollHeight(30543) > clientHeight(1236)

---

## 2. overflow: hidden 裁剪分析

- 面板 overflow: `hidden`
- 面板尺寸: 1114x812px
- 滚动区尺寸: 1080x30533px
- 面板内子元素总高度: 810px
- 滚动区是否溢出面板: **是** (差值: 29721px)

> **结论:** 滚动区高度超出面板，而面板设置了 `overflow: hidden`，
> 但滚动区自身的 `overflow-y: auto` 使其内部滚动，所以 `overflow: hidden` 主要影响的是
> 面板圆角裁剪（`rounded-2xl`）而非内容裁剪。

---

## 3. 布局链逐层分析 (1440x900)

| # | 标签 | 类名 | 宽度 | 高度 | display | overflow | max-width | max-height |
|---|------|------|------|------|---------|----------|-----------|------------|
| 0 | body | bg-surface-50.dark:bg-surface-900.text-ink-800.dark:text-ink-200 | 1440px | 917px | block | visible | none | none |
| 1 | div#app |  | 1440px | 917px | block | visible | none | none |
| 2 | div | min-h-screen.bg-surface-50.dark:bg-surface-900 | 1440px | 917px | block | visible | none | none |
| 3 | main | p-3.lg:p-5.max-w-[1920px].mx-auto | 1440px | 860px | block | visible | 1920px | none |
| 4 | div | grid.grid-cols-1.lg:grid-cols-4.xl:grid-cols-5 | 1400px | 820px | grid | visible | none | none |
| 5 | div | lg:col-span-3.xl:col-span-4.relative.min-w-0 | 1114px | 812px | flex | hidden | none | none |
| 6 | div | p-3.lg:p-4.flex-1.min-h-0 | 1112px | 764px | flex | auto | none | none |
| 7 | div |  | 1080px | 764px | block | visible | none | none |
| 8 | div | flex.flex-col.flex-1.min-h-0 | 1080px | 764px | flex | visible | none | none |
| 9 | div | vue-recycle-scroller.ready.direction-vertical.virtual-scroller | 1080px | 696px | block | auto | none | none |

### 高度骤降分析

- **第 2 → 3 层:** div.min-h-screen.bg-surface-50.dark:bg-surface-900 (917px) → main.p-3.lg:p-5.max-w-[1920px].mx-auto (860px), 降低 **57px**
- **第 3 → 4 层:** main.p-3.lg:p-5.max-w-[1920px].mx-auto (860px) → div.grid.grid-cols-1.lg:grid-cols-4.xl:grid-cols-5 (820px), 降低 **40px**
- **第 5 → 6 层:** div.lg:col-span-3.xl:col-span-4.relative.min-w-0 (812px) → div.p-3.lg:p-4.flex-1.min-h-0 (764px), 降低 **48px**
- **第 8 → 9 层:** div.flex.flex-col.flex-1.min-h-0 (764px) → div.vue-recycle-scroller.ready.direction-vertical.virtual-scroller (696px), 降低 **68px**

---

## 4. Grid 布局比例分析

| 视口 | grid-template-columns | 侧边栏宽 | 面板宽 | 比例 | 面板占比 |
|------|----------------------|----------|--------|------|---------|
| lg-1024 | 222px 222px 222px 222px | 222px | 730px | 3.29:1 | 76.7% |
| xl-1280 | 222.391px 222.391px 222.391px 222.391px 222.391px | 222px | 986px | 4.44:1 | 81.6% |
| custom-1440 | 254.391px 254.391px 254.391px 254.391px 254.391px | 254px | 1114px | 4.39:1 | 81.4% |
| fhd-1920 | 350.391px 350.391px 350.391px 350.391px 350.391px | 350px | 1498px | 4.28:1 | 81.1% |

### 分析

- `grid-cols-4` + `col-span-3` 理论比例为 3:1 (75%:25%)
- 实际比例受 `max-w-[1440px]` 容器和 padding/gap 影响
- 当视口 > 1440px 时，两侧留白增大，面板实际宽度被 `max-width` 限制

---

## 5. 虚拟滚动高度计算公式验证

公式: 桌面端 `calc(100vh - 280px)`, 移动端 `calc(100vh - 400px)`

| 视口高度 | 桌面端(100vh-280) | 占比 | 移动端(100vh-400) | 占比 |
|---------|-------------------|------|-------------------|------|
| 600px | 320px | 53.3% | 200px | 33.3% |
| 700px | 420px | 60.0% | 300px | 42.9% |
| 768px | 488px | 63.5% | 368px | 47.9% |
| 800px | 520px | 65.0% | 400px | 50.0% |
| 900px | 620px | 68.9% | 500px | 55.6% |
| 1000px | 720px | 72.0% | 600px | 60.0% |
| 1080px | 800px | 74.1% | 680px | 63.0% |
| 1440px | 1160px | 80.6% | 1040px | 72.2% |

### 280px 扣除值分解估算

| 组成部分 | 估算高度 |
|---------|---------|
| 导航栏 (nav h-14) | ~56px |
| main padding (lg:p-8) | ~64px (上下各32px) |
| TabBar (py-3.5 + border) | ~58px |
| SearchFilterBar + 间距 | ~56px |
| 内容区 padding (lg:p-6) | ~48px (上下各24px) |
| **合计** | **~282px** |

> **问题:** 280px 是静态值，但 TabBar 高度、SearchFilterBar 是否显示、子标签筛选栏等
> 都是动态的。当这些元素实际占用更多空间时，虚拟滚动区会被压缩。
> 当视口高度 < 800px（常见笔记本），可用高度 < 520px，体验较差。

---

## 6. 问题卡片尺寸分析

- 可见卡片总数: 247
- 平均高度: 123px
- 平均面积: 132522 px²

| 序号 | 宽度 | 高度 | 面积 | 头部高 | 徽标宽 | 文本区宽 | padding |
|------|------|------|------|--------|--------|---------|---------|
| 0 | 1080px | 123px | 132522px² | 121px | 44px | 920px | 0px |
| 1 | 1080px | 123px | 132522px² | 121px | 44px | 920px | 0px |
| 2 | 1080px | 123px | 132522px² | 121px | 44px | 920px | 0px |
| 3 | 1080px | 123px | 132522px² | 121px | 44px | 920px | 0px |
| 4 | 1080px | 123px | 132522px² | 121px | 44px | 920px | 0px |

---

## 7. 综合诊断结论

### 根本原因（按影响程度排序）

#### 1. 虚拟滚动区高度使用固定扣除值（**高影响**）

`MasterBankList.vue` 中 `.virtual-scroller` 的高度为 `calc(100vh - 280px)`，
这个 280px 是硬编码的估算值，没有考虑：
- 子标签筛选栏的动态显示/隐藏
- 批量操作面板（BatchActionPanel）的显示
- "全部展开/收起" 按钮行
- 不同设备上 TabBar/SearchFilterBar 的实际高度差异

#### 2. Grid 布局 3:1 比例固定（**中影响**）

`grid-cols-4` + `lg:col-span-3` 使题库面板固定占 75% 宽度。
对于以内容阅读为主的题库场景，侧边栏可能不需要始终占 25%。

#### 3. 多层 padding 叠加（**中影响**）

main (32px) → 内容区 (24px) → 卡片 (20px) 共 76px 水平 padding，
在 1366px 笔记本上实际内容宽度仅约 1290px * 75% - 48px ≈ 919px。

#### 4. overflow: hidden 用于圆角裁剪（**低影响**）

面板的 `overflow: hidden` 主要是为了 `rounded-2xl` 圆角裁剪，
但由于虚拟滚动区自身的 `overflow-y: auto`，不会裁剪滚动内容。

#### 5. max-w-[1440px] 容器限制（**仅影响大屏**）

在 >1440px 的显示器上，内容区不会填满屏幕，两侧留白。

### 优化建议

1. **动态计算虚拟滚动区高度** — 使用 `ResizeObserver` 或 CSS `calc()` 结合 CSS 变量，
   根据 TabBar、SearchFilterBar 等元素的实际高度动态计算
2. **调整 Grid 比例** — 考虑 `lg:grid-cols-5` + `lg:col-span-4` (80%:20%) 或响应式折叠侧边栏
3. **减少 padding 层级** — 合并 main padding 和内容区 padding
4. **小屏优化** — 在 1366px 以下考虑隐藏或折叠侧边栏
5. **卡片紧凑模式** — 提供可选的更紧凑的卡片布局，减少单卡高度
