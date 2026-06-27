# InterviewBoss UI/UX Polish Design

## Overview

Improve InterviewBoss' interface polish while preserving the current product structure and visual identity. This is a restrained refinement pass, not a redesign.

The current app is stable and already follows the shadcn-vue/reka-vega direction in many places. The main gaps are consistency, mobile navigation, visual hierarchy, and small interaction details that make the product feel less mature than the underlying workflow.

## Goals

- Keep the existing color palette and brand direction.
- Unify navigation and action icons around `@lucide/vue`.
- Add a usable mobile navigation path when the desktop sidebar is hidden.
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

## Current Observations

### Desktop

- The desktop shell is clean and efficient, but the app still reads as a generic admin workspace in several places.
- The sidebar uses Hugeicons while the project guidance asks for lucide icons.
- Some components still use hand-written inline SVGs for common actions such as loading, error, close, and status icons.
- The MasterBank toolbar combines search, filters, batch actions, category pills, and primary actions into one strong block. The function is correct, but the hierarchy is flatter than ideal.
- The Import page is stable and efficient, but the text area, image dropzone, and bottom configuration bar feel like separate form fragments rather than one coherent tool panel.
- Chat is the strongest page compositionally; it mainly needs icon and spacing consistency rather than a new layout.

### Mobile

- The desktop sidebar disappears below `md`, but there is no replacement mobile navigation entry.
- Users can reach page content, but switching sections is not discoverable from the UI.
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

### 2. Mobile Navigation

Add mobile navigation to the authenticated layout:

- Show a compact menu trigger in the mobile header.
- Open a lightweight mobile navigation surface containing the same core routes as the desktop sidebar.
- Include visible route labels, active state, and counts where they already exist.
- Include settings access either in the mobile nav surface or keep the current settings button in the header.
- Close the nav after route selection.

Preferred implementation:

- Reuse the existing `sidebarTabs` data from `AuthenticatedLayout.vue`.
- Add a mobile-only trigger in `SiteHeader.vue` or a small sibling component owned by the layout.
- Use existing shadcn primitives if already available; otherwise use a small accessible panel with `Button`, `AppTooltip`, and existing transition patterns.

Behavior:

- Desktop sidebar remains unchanged for `md` and above.
- Mobile nav must work in preview mode and authenticated mode.
- No horizontal body overflow at 390px width.
- Mobile nav should not hide the page title or settings action.

### 3. Page Hierarchy Polish

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

Login:

- Keep the minimal login composition.
- Only adjust icon/style consistency if needed while touching shared components.

### 4. Interaction And State Details

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

## Files Likely To Change

- `frontend/src/layouts/AuthenticatedLayout.vue`
- `frontend/src/components/AppSidebar.vue`
- `frontend/src/components/SiteHeader.vue`
- `frontend/src/views/MasterBankView.vue`
- `frontend/src/components/business/MasterBankList.vue`
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

Viewport checks:

- Desktop: 1440 x 900
- Mobile: 390 x 844

Acceptance criteria:

- No horizontal overflow on checked pages.
- Mobile users can open navigation and switch among core routes.
- Desktop sidebar remains functional in expanded and collapsed states.
- Sidebar and shared layout icons use lucide consistently.
- MasterBank mobile accordion chevrons no longer feel clipped.
- Existing import submission contract remains unchanged.
- Existing color palette remains unchanged.

## Open Decisions

- Mobile navigation surface shape: dropdown panel from header vs drawer-style sheet.
- Whether to install a shadcn sheet/dropdown primitive if not already present, or implement with existing primitives.
- Whether icon unification should include only shared chrome first or also high-traffic business components in the same pass.

Recommended decisions:

- Use a header dropdown/panel first. It is lighter than a drawer and enough for the current route count.
- Do shared chrome plus touched high-traffic components, not a repo-wide icon migration.
