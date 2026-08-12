const NO_SEARCH_CONFIRM_MESSAGE = '当前没有可用的联网搜索配置，是否使用非搜索模式继续生成？'

export const isSearchNotConfiguredError = (error) =>
  error?.code === 'SEARCH_NOT_CONFIGURED' ||
  error?.data?.detail?.code === 'SEARCH_NOT_CONFIGURED'

export async function runWithSearchFallback(action, showConfirm) {
  try {
    return await action(false)
  } catch (error) {
    if (!isSearchNotConfiguredError(error)) throw error

    const confirmed = await showConfirm(NO_SEARCH_CONFIRM_MESSAGE, {
      title: '未配置联网搜索',
      confirmLabel: '继续生成',
      cancelLabel: '取消',
      variant: 'warning',
    })
    if (!confirmed) return null
    return action(true)
  }
}
