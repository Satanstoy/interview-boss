# Unified Settings Page Design

> Date: 2026-06-10 | Status: Approved | Scope: Frontend

## Problem

Settings in InterviewBoss are scattered across 4 disconnected places:
- `SettingsPanel.vue` (gear icon in header) — LLM config, positions, admin taxonomy
- `ProfilePanel.vue` (user menu → "个人信息") — email, resume, learning progress, favorites
- `UserMenu.vue` (sidebar dropdown) — bank mode toggle
- Top nav bar — dark mode toggle

Users need to discover 3+ entry points to find all settings. No single mental model.

## Research Summary

Industry standards (Linear, GitHub, Vercel) follow these principles:
1. **Left sidebar navigation** for 5+ setting groups — always visible, scales
2. **Group by user task**, not backend schema
3. **Progressive disclosure** — 90% of users change only 4-5 settings
4. **Hybrid save** — auto-save for toggles/preferences, explicit save for security/config

## Design

### Layout: Full-page with left sidebar

```
┌──────────────────────────────────────────────────┐
│  ← Back to Workspace           Settings    [Search]│
├──────────────┬───────────────────────────────────┤
│  Nav Sidebar │  Content Area                     │
│              │                                   │
│  👤 Profile  │  Settings for the active section   │
│  🎯 Interview│                                   │
│  🤖 AI Config│                                   │
│  🔒 Security │                                   │
│  ⚙️ Admin    │                                   │
│  (admin only)│                                   │
└──────────────┴───────────────────────────────────┘
```

### Navigation Groups

| Section | Contents | Visibility |
|---------|----------|------------|
| **个人信息** (Profile) | Email binding, resume upload, learning progress, bank mode, appearance (theme + sidebar default) | All users |
| **面试偏好** (Interview) | Target position, difficulty preference, starred items | All users |
| **AI 配置** (AI Config) | API Key, Base URL, Model name, Timeout | All users |
| **账户安全** (Security) | Change password, logout | All users |
| **管理员设置** (Admin) | Active season, category taxonomy management, bank rebuild | Admin only |

### Key Changes

1. **Bank mode**: moved from UserMenu dropdown → Profile section (it's a global preference, not a quick action)
2. **Dark mode**: moved from top nav bar → Profile section (unified entry; add "system" option)
3. **Email + Resume + Progress**: merged from ProfilePanel → Profile section
4. **LLM config**: independent AI Config section (currently mixed with admin settings in one dialog)
5. **Taxonomy + Season**: kept in admin section with proper permission gating
6. **Sidebar collapse preference**: persisted to localStorage (currently resets on reload)

### Data Flow

- Single `SettingsPage.vue` component as the full-page shell
- Section components: `SettingsProfile.vue`, `SettingsInterview.vue`, `SettingsAIConfig.vue`, `SettingsSecurity.vue`, `SettingsAdmin.vue`
- Access from sidebar nav item or gear icon in header
- Back button returns to previous tab/workspace
- Each section handles its own save independently (no global save button)

### Components to Create/Modify

| Action | File | Notes |
|--------|------|-------|
| **NEW** | `SettingsPage.vue` | Full-page shell with sidebar nav |
| **NEW** | `SettingsNav.vue` | Left navigation sidebar |
| **NEW** | `SettingsProfile.vue` | Email, resume, progress, bank mode, theme |
| **NEW** | `SettingsInterview.vue` | Position, difficulty, favorites |
| **NEW** | `SettingsAIConfig.vue` | LLM API config |
| **NEW** | `SettingsSecurity.vue` | Password change, logout |
| **NEW** | `SettingsAdmin.vue` | Season, taxonomy, rebuild |
| **MODIFY** | `App.vue` | Add SettingsPage route/invocation; persist sidebarCollapsed |
| **MODIFY** | `SiteHeader.vue` | Remove dark mode toggle, gear icon → SettingsPage |
| **MODIFY** | `UserMenu.vue` | Remove bank mode toggle, settings link → SettingsPage |
| **REMOVE** | `SettingsPanel.vue` | Absorbed into SettingsPage |
| **REMOVE** | `ProfilePanel.vue` | Absorbed into SettingsPage |

### Visual Style

- Consistent with existing shadcn-vue design system
- Left nav: `w-56 bg-sidebar border-r`, items with active highlight
- Content area: `max-w-3xl mx-auto` for comfortable reading width
- Section cards with `border border-border rounded-xl bg-card`
- Toggles use shadcn `Switch`, selects use shadcn `Select`
