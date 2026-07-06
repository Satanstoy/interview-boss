import { ref, watch } from 'vue'

/**
 * Sidebar state composable.
 * Note: The main sidebar state is managed by AuthenticatedLayout.vue via
 * shadcn-vue's SidebarProvider. This composable is kept for potential
 * future use but is not currently imported anywhere.
 */
export function useSidebar() {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')

  const toggleSidebar = () => {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebar-collapsed', String(sidebarCollapsed.value))
  }

  watch(sidebarCollapsed, (val) => {
    localStorage.setItem('sidebar-collapsed', String(val))
  })

  return {
    sidebarCollapsed,
    toggleSidebar,
  }
}
