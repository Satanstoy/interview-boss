declare module "dnd-kit-vue" {
  export function useSortableContext(): {
    handleRef: (element: unknown) => void
    sortable: boolean
  }
}
