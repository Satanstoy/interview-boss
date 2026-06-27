# InterviewBoss UI/UX Polish Design

## Overview

Improve InterviewBoss' interface polish while preserving the current product structure and visual identity. This is a restrained refinement pass, not a redesign.

The current app is stable and already follows the shadcn-vue/reka-vega direction in many places. The main gaps are consistency, mobile navigation, visual hierarchy, and small interaction details that make the product feel less mature than the underlying workflow.

## Goals

- Keep the existing color palette and brand direction.
- Unify navigation and action icons around `@lucide/vue`.
- Align the sidebar order with the main user workflow.
- Add a usable mobile navigation path when the desktop sidebar is hidden.
- Make mobile pages usable, not just reachable.
- Improve hierarchy in existing page shells without changing page information architecture.
- Fix small visual defects: clipped controls, inconsistent icon sources, mixed custom SVGs, cramped card actions, and uneven button prominence.
- Preserve current routes, data flow, API contracts, and page-level behavior.

## Non-Goals

- Do not change the primary color palette or theme tokens.
- Do not redesign the core product narrative into a new dashboard.
- Do not restructure the MasterBank, Import, or Chat workflows.
- Do not replace shadcn-vue with another component system.
- Do not add new business features such as daily tasks, progress dashboards, or coaching summaries.
- Do not perform broad refactors unrelated to visible UI consistency.
- Do not make mobile changes by hiding core functionality.

## Current Observations

### Desktop

- The desktop shell is clean and efficient, but the app still reads as a generic admin workspace in several places.
- The sidebar order mixes daily practice, source material management, and analysis tools, so the navigation does not clearly reflect the user's workflow.
- The sidebar uses Hugeicons while the project guidance asks for lucide icons.
- Some components still use hand-written inline SVGs for common actions such as loading, error, close, and status icons.
- The MasterBank toolbar combines search, filters, batch actions, category pills, and primary actions into one strong block. The function is correct, but the hierarchy is flatter than ideal.
- The Import page is stable and efficient, but the text area, image dropzone, and bottom configuration bar feel like separate form fragments rather than one coherent tool panel.
- Chat is the strongest page compositionally; it mainly needs icon and spacing consistency rather than a new layout.

### Mobile

- The desktop sidebar disappears below `md`, but there is no replacement mobile navigation entry.
- Users can reach page content, but switching sections is not discoverable from the UI.
- Chat and Coding still use desktop-style internal sidebars at 390px width, which squeezes the primary content into a narrow strip.
- JD and Interview use the shared table in a compressed mobile layout, causing table cells to stack into vertical text columns.
- MasterBank cards fit without horizontal page overflow, but the accordion chevron can sit too close to the viewport edge or appear visually clipped.
- Toolbar controls wrap correctly, but their hierarchy becomes busy on narrow screens.

## Design Direction

Use a "mature workbench" direction:

- Keep the app quiet, focused, and tool-like.
- Make primary actions obvious without adding marketing-style decoration.
- Prefer better grouping, spacing, icons, and responsive navigation over new surfaces.
- Preserve the existing reka-vega/shadcn visual baseline.

## Scope

### 1. Icon Unification

Replace inconsistent icon sources in high-visibility shared UI:

- Sidebar navigation icons in `AppSidebar.vue`.
- Header job/status icons in `SiteHeader.vue`.
- Common action/status icons where hand-written SVGs duplicate lucide icons.
- Empty states and common toolbar actions when nearby files are touched.

Implementation notes:

- Use `@lucide/vue` for new or replaced icons.
- Keep existing favicon/logo assets unchanged.
- Do not migrate every icon in the repo in one sweep. Prioritize shared layout and high-traffic pages first.
- Avoid inline SVG unless a shape is genuinely custom and no lucide equivalent exists.

### 2. Sidebar Information Architecture

Reorder and group the sidebar around the user's actual work loop.

Recommended grouped order:

| Group | Routes |
| --- | --- |
| Primary | 高频题库 |
| 训练 | 模拟面试, 题目抽测, 手撕代码 |
| 素材 | 导入, JD 筛选, 面经库 |
| 洞察 | 知识图谱 |

Desktop expanded sidebar:

- Keep 高频题库 as the first standalone primary workspace.
- Add lightweight section labels for 训练, 素材, and 洞察.
- Keep counts on 高频题库, JD 筛选, and 面经库.
- Keep user menu placement unchanged.
- Avoid adding new routes or new business concepts.

Desktop collapsed sidebar:

- Keep the same icon order.
- Do not show section labels in collapsed mode.
- Use `AppTooltip` so each icon remains understandable.

Mobile navigation:

- Use the same grouped order.
- Show labels and counts.
- Close the navigation surface after route selection.

### 3. Mobile Shell

Add mobile navigation to the authenticated layout:

- Show a compact menu trigger in the mobile header.
- Open a lightweight mobile navigation surface containing the same core routes as the desktop sidebar.
- Include visible route labels, active state, and counts where they already exist.
- Include settings access either in the mobile nav surface or keep the current settings button in the header.
- Close the nav after route selection.

Preferred implementation:

- Reuse the existing `sidebarTabs` data from `AuthenticatedLayout.vue`.
- Add a mobile-only trigger in `SiteHeader.vue` or a small sibling component owned by the layout.
- Prefer the existing shadcn `Sheet`/`Sidebar` primitives already present under `components/ui/sidebar` and `components/ui/sheet`.
- If the existing sidebar primitive is too heavy for this pass, use a small Sheet-backed route menu with the same data model.

Behavior:

- Desktop sidebar remains unchanged for `md` and above.
- Mobile nav must work in preview mode and authenticated mode.
- No horizontal body overflow at 390px width.
- Mobile nav should not hide the page title or settings action.
- Mobile nav must be a shell-level navigation surface, not a page-specific workaround.

Internal page sidebars:

- Chat's conversation list should not permanently consume horizontal space on mobile.
- Coding's problem list should not permanently consume horizontal space on mobile.
- Use a mobile drawer/sheet or a toggleable panel for these internal sidebars.
- Desktop behavior for Chat and Coding should remain unchanged.

### 4. Mobile Data Presentation

Make data-heavy pages readable on small screens.

JD and Interview:

- Desktop keeps the current table layout.
- Mobile should render rows as stacked cards instead of compressing table columns.
- Cards should expose the most important fields first:
  - JD: company, role, salary, season, core tech, bonus, actions.
  - Interview: company, season, round, difficulty, created date, focus, question list, actions.
- Selection checkbox and row actions remain available on each card.
- Batch actions remain above the list.
- Pagination remains below the list when present.
- Inline editing can remain desktop-first if card editing would add too much scope, but mobile cards must still show data and core row actions clearly.

Fallback only if card mode becomes too large:

- Use horizontal table scrolling on mobile.
- Do not allow table text to collapse into one-character vertical columns.
- Prefer card mode because the data is mostly textual and cards are more readable at 390px.

MasterBank:

- Keep the accordion list on mobile.
- Reserve stable space for checkbox and chevron controls.
- Avoid card widths or child controls extending beyond the visible viewport.
- Reduce toolbar crowding by letting secondary actions wrap under primary actions in a predictable order.

KnowledgeGraph:

- Keep the chart page simple.
- Ensure the top controls wrap cleanly on mobile.
- Do not attempt a full mobile graph redesign in this pass.

### 5. Page Hierarchy Polish

Improve hierarchy without changing the information architecture.

MasterBank:

- Keep the current toolbar, category pills, and accordion list.
- Visually separate primary actions from batch actions more clearly.
- Make search/filter the first scan target, then selection/batch actions, then category filters.
- Ensure card chevrons have stable space on desktop and mobile.
- Keep current infinite-scroll behavior.

Import:

- Keep the current two-column desktop layout and stacked mobile layout.
- Make the page feel like one coherent import workbench by tightening header copy, panel spacing, and bottom action grouping.
- Preserve text + image combined upload.
- Preserve URL, season, target, and content type fields.

Chat:

- Keep the current conversation structure.
- Align icons, status chips, and action controls with the same lucide/shadcn treatment.
- Avoid changing message flow or chat data behavior.
- On mobile, make conversation switching available without squeezing the active conversation.

Coding:

- Keep the current coding workflow.
- On mobile, make problem selection available without squeezing the editor or empty state.
- Do not redesign the coding editor experience beyond making the layout responsive.

Login:

- Keep the minimal login composition.
- Only adjust icon/style consistency if needed while touching shared components.

### 6. Interaction And State Details

- Standardize icon button dimensions in shared headers and toolbars.
- Make hover, active, disabled, and focus states consistent with shadcn defaults.
- Use `AppTooltip` for icon-only controls where meaning is not obvious.
- Avoid native `title` attributes.
- Preserve reduced-motion behavior.
- Keep card radius and borders aligned with the current frontend baseline.

## Accessibility And Responsive Requirements

- Mobile navigation trigger must be keyboard reachable.
- Icon-only buttons must have accessible labels.
- Focus rings should remain visible.
- Page content must not be obscured by the mobile nav.
- Text inside buttons and cards must not overflow at 390px mobile width.
- The app must not introduce horizontal body scrolling on core preview pages.
- Mobile pages must not compress primary content into unreadable narrow columns.
- Table data must remain readable on mobile, either as cards or as an explicitly scrollable table.

## Files Likely To Change

- `frontend/src/layouts/AuthenticatedLayout.vue`
- `frontend/src/components/AppSidebar.vue`
- `frontend/src/components/SiteHeader.vue`
- `frontend/src/components/common/DataTable.vue`
- `frontend/src/views/MasterBankView.vue`
- `frontend/src/views/JdView.vue`
- `frontend/src/views/InterviewView.vue`
- `frontend/src/views/ChatView.vue`
- `frontend/src/views/CodingView.vue`
- `frontend/src/components/business/MasterBankList.vue`
- `frontend/src/components/business/ChatView.vue`
- `frontend/src/components/business/CodingPractice.vue`
- `frontend/src/components/business/StagingPanel.vue`
- Possibly nearby shared UI components under `frontend/src/components/common/`
- `frontend/CLAUDE.md` only if the work establishes or changes a durable frontend convention

## Testing And Verification

Run:

- `cd frontend && npm run build`

Manual or Playwright preview checks:

- `/login`
- `/master-bank?preview=1`
- `/import?preview=1`
- `/chat?preview=1`
- `/jd?preview=1`
- `/interview?preview=1`
- `/mock-interview?preview=1`
- `/knowledge-graph?preview=1`
- `/coding?preview=1`

Viewport checks:

- Desktop: 1440 x 900
- Mobile: 390 x 844

Acceptance criteria:

- No horizontal overflow on checked pages.
- Mobile users can open navigation and switch among core routes.
- Desktop sidebar remains functional in expanded and collapsed states.
- Desktop sidebar order follows the grouped workflow: 高频题库, 训练, 素材, 洞察.
- Sidebar and shared layout icons use lucide consistently.
- MasterBank mobile accordion chevrons no longer feel clipped.
- Chat mobile layout keeps the active conversation readable and provides a way to switch conversations.
- Coding mobile layout keeps the active content/editor readable and provides a way to choose problems.
- JD and Interview mobile layouts show readable row data instead of compressed vertical table text.
- Existing import submission contract remains unchanged.
- Existing color palette remains unchanged.

## Settled Recommendations

- Mobile navigation should use a Sheet-backed menu rather than a small dropdown. The route count and grouping need more space than a compact dropdown comfortably provides.
- JD and Interview should use mobile card rows instead of horizontal scrolling as the primary approach. Text-heavy recruiting and interview data reads better as cards.
- Chat and Coding should move their internal sidebars into mobile drawers/sheets.
- Icon unification should cover shared chrome plus touched high-traffic components, not a repo-wide migration.

## Deferred Follow-Ups

- A full mobile graph experience for KnowledgeGraph.
- A broader redesign of the Chat or Coding workflows.
- A new dashboard, today view, progress summary, or coaching layer.
- Theme or palette changes.
