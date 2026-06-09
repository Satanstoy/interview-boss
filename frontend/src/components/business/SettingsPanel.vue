<template>
  <AppDialog :open="visible" @update:open="emit('close')" title="系统配置" size="xl">
    <!-- Body -->
    <div class="flex-1 overflow-y-auto custom-scrollbar space-y-6 -my-2">

            <!-- ═══ Per-user LLM Config (所有用户可见) ═══ -->
            <div class="space-y-3.5 p-5 rounded-2xl border border-primary-100 dark:border-primary-800 bg-gradient-to-b from-primary-50/50 to-white dark:from-primary-900/20 dark:to-surface-800">
              <h3 class="text-xs font-bold text-primary-600 dark:text-primary-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                我的 LLM 配置
              </h3>

              <!-- 未配置提示 -->
              <div v-if="!myLLM.configured && !myLLM.editing" class="flex items-center gap-3 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                <svg class="w-5 h-5 text-amber-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
                <span class="text-sm text-amber-700 dark:text-amber-300">请先配置 LLM 密钥才能使用 AI 功能</span>
                <button @click="startEditMyLLM" class="ml-auto text-xs bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 px-3 py-1.5 rounded-lg hover:bg-amber-200 dark:hover:bg-amber-900/60 transition font-medium border border-amber-300 dark:border-amber-700">立即配置</button>
              </div>

              <!-- 已配置：显示摘要 -->
              <div v-if="myLLM.configured && !myLLM.editing" class="space-y-2">
                <div class="space-y-2 text-sm">
                  <div class="flex items-center gap-3">
                    <span class="text-xs text-ink-500 dark:text-ink-400 w-16 shrink-0">API Key</span>
                    <span class="font-mono text-ink-700 dark:text-ink-200 truncate">{{ myLLM.settings.llm_api_key || '未设置' }}</span>
                  </div>
                  <div class="flex items-center gap-3">
                    <span class="text-xs text-ink-500 dark:text-ink-400 w-16 shrink-0">模型</span>
                    <span class="font-mono text-ink-700 dark:text-ink-200 truncate">{{ myLLM.settings.llm_model || '未设置' }}</span>
                  </div>
                  <div class="flex items-center gap-3">
                    <span class="text-xs text-ink-500 dark:text-ink-400 w-16 shrink-0">Base URL</span>
                    <span class="font-mono text-ink-700 dark:text-ink-200 truncate">{{ myLLM.settings.llm_base_url || '未设置' }}</span>
                  </div>
                  <div class="flex items-center gap-3">
                    <span class="text-xs text-ink-500 dark:text-ink-400 w-16 shrink-0">超时</span>
                    <span class="font-mono text-ink-700 dark:text-ink-200">{{ myLLM.settings.llm_timeout || 120 }}s</span>
                  </div>
                </div>
                <div class="flex gap-2">
                  <button @click="startEditMyLLM" class="text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 px-3 py-1.5 rounded-lg hover:bg-primary-100 dark:hover:bg-primary-900/50 transition font-medium border border-primary-200 dark:border-primary-800">
                    修改配置
                  </button>
                  <button @click="deleteMyLLM" class="text-xs bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 px-3 py-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/50 transition font-medium border border-red-200 dark:border-red-800">
                    清除配置
                  </button>
                </div>
              </div>

              <!-- 编辑表单 -->
              <div v-if="myLLM.editing" class="space-y-3">
                <div>
                  <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">API Key</label>
                  <div v-if="myLLM.settings.llm_api_key_set && !myLLM.editKey" class="flex items-center gap-2">
                    <span class="flex-1 border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-surface-50 dark:bg-surface-900 text-ink-500 dark:text-ink-400 select-none">{{ myLLM.settings.llm_api_key }}</span>
                    <button @click="myLLM.editKey = true; myLLM.form.llm_api_key = ''" type="button" class="text-xs text-primary-600 hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-300 whitespace-nowrap font-medium">更换</button>
                  </div>
                  <div v-else class="relative">
                    <input
                      v-model="myLLM.form.llm_api_key"
                      :type="myLLM.showKey ? 'text' : 'password'"
                      class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 pr-10 text-sm font-mono bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200"
                      placeholder="输入 API Key"
                    />
                    <button @click="myLLM.showKey = !myLLM.showKey" type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 transition">
                      <svg v-if="myLLM.showKey" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"/></svg>
                      <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
                    </button>
                  </div>
                </div>
                <div>
                  <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">Base URL <span class="text-red-400">*</span></label>
                  <input v-model="myLLM.form.llm_base_url" type="text" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" placeholder="https://api.openai.com/v1" />
                </div>
                <div>
                  <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">模型名称 <span class="text-red-400">*</span></label>
                  <input v-model="myLLM.form.llm_model" type="text" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" placeholder="如 gpt-4o" />
                </div>
                <div>
                  <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">超时 (秒)</label>
                  <input v-model="myLLM.form.llm_timeout" type="number" min="10" max="600" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
                </div>
                <div class="flex gap-2 pt-1">
                  <button @click="saveMyLLM" :disabled="myLLM.saving" class="btn-primary px-4 text-sm">
                    {{ myLLM.saving ? '保存中...' : '保存' }}
                  </button>
                  <button @click="myLLM.editing = false" class="btn-secondary px-4 text-sm">取消</button>
                </div>
                <p v-if="myLLM.error" class="text-xs text-red-500 dark:text-red-400">{{ myLLM.error }}</p>
              </div>
            </div>

            <!-- ═══ 目标岗位（所有用户可见） ═══ -->
            <div class="space-y-3.5 p-5 rounded-2xl border border-accent-100 dark:border-accent-800 bg-gradient-to-b from-accent-50/50 to-white dark:from-accent-900/20 dark:to-surface-800">
              <h3 class="text-xs font-bold text-accent-600 dark:text-accent-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/></svg>
                目标岗位
              </h3>
              <div>
                <div class="flex gap-2 flex-wrap mb-2">
                  <div v-for="pos in availablePositions" :key="pos" class="flex items-center gap-1">
                    <button
                      @click="onSwitchPosition(pos)"
                      :class="taxonomy.job_position === pos
                        ? 'bg-accent-100 dark:bg-accent-900/40 text-accent-700 dark:text-accent-300 border-accent-300 dark:border-accent-700'
                        : 'bg-white dark:bg-surface-900 text-ink-600 dark:text-ink-400 border-surface-200 dark:border-ink-600 hover:border-accent-300 dark:hover:border-accent-700'"
                      class="px-3 py-1.5 text-xs rounded-lg border transition-all font-medium"
                    >{{ pos }}</button>
                    <button
                      v-if="isAdmin"
                      @click="onDeletePosition(pos)"
                      class="p-1 text-ink-300 dark:text-ink-600 hover:text-red-500 dark:hover:text-red-400 transition"
                      title="删除岗位"
                    >
                      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                    </button>
                  </div>
                </div>
                <div class="flex gap-2">
                  <input v-model="newPositionInput" placeholder="新增岗位（最多30字）" class="flex-1 border border-surface-200 dark:border-ink-600 rounded-xl px-3 py-2 text-xs bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-accent-200 dark:focus:ring-accent-800 focus:border-accent-400 transition-all duration-200" />
                  <button @click="addPosition" class="text-xs bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-400 px-3 py-2 rounded-xl hover:bg-accent-100 dark:hover:bg-accent-900/50 transition font-medium whitespace-nowrap border border-accent-200 dark:border-accent-800">添加</button>
                </div>
                <div v-if="newPositionInput.length > 20" class="text-xs mt-1" :class="newPositionInput.length > 30 ? 'text-red-500' : 'text-ink-400 dark:text-ink-500'">
                  {{ newPositionInput.length }} / 30
                </div>
                <!-- AI生成分类按钮 -->
                <button
                  @click="onGenerateTaxonomy"
                  :disabled="aiTaxonomyLoading || !taxonomy.job_position"
                  class="mt-2 w-full text-xs bg-gradient-to-r from-accent-500 to-primary-500 text-white px-4 py-2.5 rounded-xl hover:from-accent-600 hover:to-primary-600 transition-all font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  <svg v-if="aiTaxonomyLoading" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
                  {{ aiTaxonomyLoading ? 'AI 生成中...' : 'AI 智能生成分类' }}
                </button>
              </div>
            </div>

            <!-- AI分类预览弹窗 -->
            <Teleport to="body">
              <div v-if="aiTaxonomyPreview" class="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 backdrop-blur-sm">
                <div class="bg-white dark:bg-surface-800 rounded-2xl shadow-2xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
                  <div class="px-6 py-4 border-b border-surface-200 dark:border-ink-700">
                    <h3 class="text-lg font-bold text-ink-800 dark:text-ink-100">AI 推荐分类体系</h3>
                    <p class="text-xs text-ink-500 dark:text-ink-400 mt-1">岗位：{{ aiTaxonomyPreview.position }}</p>
                  </div>
                  <div class="flex-1 overflow-y-auto px-6 py-4 space-y-3">
                    <div v-for="(cat, i) in aiTaxonomyPreview.categories" :key="i" class="rounded-xl border border-surface-200 dark:border-ink-700 overflow-hidden">
                      <div class="px-4 py-2.5 bg-accent-50 dark:bg-accent-900/20 font-semibold text-sm text-accent-700 dark:text-accent-300">
                        {{ cat.cat1 }}
                      </div>
                      <div class="px-4 py-2 space-y-1">
                        <div v-for="(child, j) in cat.children" :key="j" class="text-sm text-ink-600 dark:text-ink-300 pl-4">
                          {{ child }}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="px-6 py-4 border-t border-surface-200 dark:border-ink-700 flex gap-3 justify-end">
                    <button @click="onCancelTaxonomy" class="px-4 py-2 text-sm rounded-xl border border-surface-300 dark:border-ink-600 text-ink-600 dark:text-ink-300 hover:bg-surface-100 dark:hover:bg-surface-700 transition">
                      取消
                    </button>
                    <button @click="onConfirmTaxonomy" class="px-4 py-2 text-sm rounded-xl bg-accent-500 text-white hover:bg-accent-600 transition font-medium">
                      采纳此分类
                    </button>
                  </div>
                </div>
              </div>
            </Teleport>

            <!-- 公开分类弹窗 -->
            <Teleport to="body">
              <div v-if="showPublicTaxonomies" class="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 backdrop-blur-sm">
                <div class="bg-white dark:bg-surface-800 rounded-2xl shadow-2xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
                  <div class="px-6 py-4 border-b border-surface-200 dark:border-ink-700 flex items-center justify-between">
                    <div>
                      <h3 class="text-lg font-bold text-ink-800 dark:text-ink-100">公开分类体系</h3>
                      <p class="text-xs text-ink-500 dark:text-ink-400 mt-1">选择一个分类体系应用到当前岗位</p>
                    </div>
                    <button @click="showPublicTaxonomies = false" class="p-2 rounded-xl text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-700 transition">
                      <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                    </button>
                  </div>
                  <div class="flex-1 overflow-y-auto px-6 py-4">
                    <!-- Loading -->
                    <div v-if="publicTaxonomiesLoading" class="flex items-center justify-center py-8">
                      <svg class="w-6 h-6 animate-spin text-primary-500" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    </div>
                    <!-- Empty -->
                    <div v-else-if="publicTaxonomies.length === 0" class="text-center py-8 text-ink-400 dark:text-ink-500 text-sm">
                      暂无公开分类
                    </div>
                    <!-- List -->
                    <div v-else class="space-y-3">
                      <div v-for="tax in publicTaxonomies" :key="tax.id"
                        class="rounded-xl border border-surface-200 dark:border-ink-700 p-4 hover:border-accent-300 dark:hover:border-accent-700 transition"
                      >
                        <div class="flex items-center justify-between mb-2">
                          <h4 class="text-sm font-semibold text-ink-800 dark:text-ink-100 cursor-pointer" @click="onUsePublicTaxonomy(tax)">{{ tax.position_name }}</h4>
                          <div class="flex items-center gap-2">
                            <span class="text-xs text-ink-400 dark:text-ink-500">分享者: {{ tax.owner_name || '匿名' }}</span>
                            <button v-if="isAdmin" @click.stop="onDeletePublicTaxonomy(tax)"
                              class="p-1 rounded-lg text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition"
                              title="删除此公开分类">
                              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                            </button>
                          </div>
                        </div>
                        <div class="flex flex-wrap gap-1.5 cursor-pointer" @click="onUsePublicTaxonomy(tax)">
                          <span v-for="(cat, i) in (tax.categories || [])" :key="i"
                            class="text-xs bg-surface-100 dark:bg-surface-700 text-ink-600 dark:text-ink-300 px-2 py-0.5 rounded">
                            {{ cat.cat1 }}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </Teleport>

            <!-- ═══ Global settings (Admin only) ═══ -->
            <template v-if="isAdmin">
              <!-- General settings -->
              <div class="space-y-3.5 p-5 rounded-2xl border border-surface-200 dark:border-ink-700 bg-gradient-to-b from-surface-50/50 to-white dark:from-surface-800/50 dark:to-surface-800">
                <h3 class="text-xs font-bold text-ink-500 dark:text-ink-400 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
                  基础设置
                </h3>
                <div>
                  <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">当前招聘季</label>
                  <RoundedSelect
                    v-model="form.active_season"
                    :options="[{ value: '', label: '未设置' }, ...seasons.map(s => ({ value: s, label: s }))]"
                    wrapper-class="w-full"
                    trigger-class="w-full bg-surface-50 dark:bg-surface-900"
                  />
                  <div class="mt-2 flex gap-2">
                    <input v-model="newSeason" placeholder="新增招聘季" class="flex-1 min-w-0 border border-surface-200 dark:border-ink-600 rounded-xl px-3 py-2 text-xs bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
                    <button @click="addSeason" class="text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 px-3 py-2 rounded-xl hover:bg-primary-100 dark:hover:bg-primary-900/50 transition font-medium whitespace-nowrap border border-primary-200 dark:border-primary-800">添加</button>
                  </div>
                </div>
              </div>

              <!-- Taxonomy config (admin only: edit categories) -->
              <div class="space-y-3.5 p-5 rounded-2xl border border-accent-100 dark:border-accent-800 bg-gradient-to-b from-accent-50/50 to-white dark:from-accent-900/20 dark:to-surface-800">
                <h3 class="text-xs font-bold text-accent-600 dark:text-accent-400 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/></svg>
                  分类管理
                </h3>

                <!-- Category list -->
                <div class="space-y-2">
                  <div class="flex items-center justify-between">
                    <label class="text-xs font-semibold text-ink-600 dark:text-ink-400">一级大类 / 二级子类</label>
                    <button @click="addCat1" class="text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-medium flex items-center gap-1">
                      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
                      添加大类
                    </button>
                  </div>

                  <div v-for="(cat, ci) in taxonomy.categories" :key="ci"
                    class="rounded-xl border border-surface-200 dark:border-ink-600 bg-white dark:bg-surface-900 overflow-hidden">
                    <div class="flex items-center gap-2 px-3 py-2.5 bg-surface-50 dark:bg-surface-800 border-b border-surface-100 dark:border-ink-700">
                      <button @click="cat._open = !cat._open" class="text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 transition">
                        <svg :class="{'rotate-90': cat._open}" class="w-4 h-4 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/></svg>
                      </button>
                      <input v-model="cat.cat1"
                        class="flex-1 text-sm font-semibold bg-transparent border-none outline-none text-ink-800 dark:text-ink-100 placeholder-ink-400 dark:placeholder-ink-500"
                        placeholder="如 A.项目经验与设计" />
                      <span class="text-xs text-ink-400 dark:text-ink-500">{{ cat.children.length }} 个子类</span>
                      <button @click="removeCat1(ci)" class="text-ink-300 dark:text-ink-600 hover:text-red-500 dark:hover:text-red-400 transition p-1">
                        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                      </button>
                    </div>
                    <div v-if="cat._open" class="p-3 space-y-1.5">
                      <div v-for="(child, ci2) in cat.children" :key="ci2" class="flex items-center gap-2">
                        <span class="text-ink-300 dark:text-ink-600 text-xs">-</span>
                        <input v-model="cat.children[ci2]"
                          class="flex-1 text-sm bg-transparent border-none outline-none text-ink-700 dark:text-ink-200 placeholder-ink-400 dark:placeholder-ink-500"
                          placeholder="如 A1.系统设计" />
                        <button @click="cat.children.splice(ci2, 1)" class="text-ink-300 dark:text-ink-600 hover:text-red-500 dark:hover:text-red-400 transition p-0.5">
                          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                        </button>
                      </div>
                      <button @click="cat.children.push('')" class="text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-medium mt-1 flex items-center gap-1">
                        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
                        添加子类
                      </button>
                    </div>
                  </div>
                </div>

                <!-- 分类操作按钮 -->
                <div class="flex gap-2 pt-2">
                  <button
                    @click="onSavePersonalTaxonomy"
                    class="flex-1 text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 px-3 py-2 rounded-xl hover:bg-primary-100 dark:hover:bg-primary-900/50 transition font-medium border border-primary-200 dark:border-primary-800"
                  >
                    保存为个人分类
                  </button>
                  <button
                    @click="onShareTaxonomy"
                    class="flex-1 text-xs bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-400 px-3 py-2 rounded-xl hover:bg-accent-100 dark:hover:bg-accent-900/50 transition font-medium border border-accent-200 dark:border-accent-800"
                  >
                    分享分类
                  </button>
                  <button
                    @click="showPublicTaxonomies = true"
                    class="flex-1 text-xs bg-surface-100 dark:bg-surface-800 text-ink-600 dark:text-ink-400 px-3 py-2 rounded-xl hover:bg-surface-200 dark:hover:bg-surface-700 transition font-medium border border-surface-300 dark:border-ink-600"
                  >
                    {{ isAdmin ? '使用与管理公开分类' : '使用公开分类' }}
                  </button>
                </div>
              </div>
            </template>

            <!-- ═══ 危险操作（仅管理员可见） ═══ -->
            <div v-if="isAdmin" class="space-y-3.5 p-5 rounded-2xl border border-red-200 dark:border-red-800/50 bg-red-50/50 dark:bg-red-900/10">
              <h3 class="text-xs font-bold text-red-600 dark:text-red-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
                危险操作
              </h3>
              <p class="text-xs text-ink-500 dark:text-ink-400 leading-relaxed">
                基于现有分类重新聚类，不会重新打标。仅在题库聚类结果需要修复时使用。
              </p>
              <button
                @click="emit('build-master-bank')"
                :disabled="isBuilding"
                class="btn-danger text-sm"
              >
                {{ isBuilding ? '聚类中...' : '重新聚类' }}
              </button>
            </div>
          </div>

    <!-- Footer -->
    <template #footer>
      <p v-if="saveMessage" class="text-xs font-medium flex items-center gap-1.5 mr-auto" :class="saveSuccess ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'">
        <svg v-if="saveSuccess" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        {{ saveMessage }}
      </p>
      <button @click="emit('close')" :disabled="isSaving" class="btn-secondary px-5">关闭</button>
      <button
        v-if="isAdmin"
        @click="saveProfile"
        :disabled="isSaving"
        class="btn-primary px-6"
      >
        {{ isSaving ? '保存中...' : '保存全局配置' }}
      </button>
    </template>
  </AppDialog>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { fetchProfile, fetchPublicProfile, updateProfile, switchPosition, switchMyPosition, fetchMyLLMConfig, updateMyLLMConfig, generateTaxonomy, confirmTaxonomy, savePersonalTaxonomy, shareTaxonomy, fetchPublicTaxonomies, deletePublicTaxonomy, deletePosition } from '@/api/index.js'
import { invalidateCache } from '@/services/http.js'
import AppDialog from '@/components/common/AppDialog.vue'
import RoundedSelect from '@/components/common/RoundedSelect.vue'
import { validateSeason, validateBaseUrl } from '@/utils/validate.js'
import { useToast } from '@/composables/useNotification.js'

const toast = useToast()

const props = defineProps({
  visible: { type: Boolean, default: false },
  activeSeason: { type: String, default: '' },
  isAdmin: { type: Boolean, default: false },
  isBuilding: { type: Boolean, default: false }
})

const availablePositions = ref([])
const newPositionInput = ref('')

const taxonomy = reactive({
  job_position: 'agent开发/大模型应用开发/大模型开发',
  categories: []
})

// ── AI Taxonomy Suggestion state ──
const aiTaxonomyLoading = ref(false)
const aiTaxonomyPreview = ref(null) // { position, categories }

// ── Public Taxonomies state ──
const showPublicTaxonomies = ref(false)
const publicTaxonomies = ref([])
const publicTaxonomiesLoading = ref(false)

const emit = defineEmits(['close', 'update:activeSeason', 'settings-saved', 'position-changed', 'build-master-bank'])

const seasons = ref([])
const isSaving = ref(false)
const saveMessage = ref('')
const saveSuccess = ref(false)
const newSeason = ref('')
const originalPosition = ref('')
const positionOnlyChanged = ref(false)

// ── Per-user LLM config state ──
const myLLM = reactive({
  configured: false,
  editing: false,
  saving: false,
  editKey: false,
  showKey: false,
  error: '',
  settings: { llm_api_key: '', llm_api_key_set: false, llm_base_url: '', llm_model: '', llm_timeout: 120 },
  form: { llm_api_key: '', llm_base_url: '', llm_model: '', llm_timeout: 120 }
})

const loadMyLLM = async () => {
  try {
    const data = await fetchMyLLMConfig()
    myLLM.configured = data.configured
    if (data.configured) {
      myLLM.settings = data.settings
    }
    myLLM.editing = false
    myLLM.error = ''
  } catch (e) {
    console.error('加载 LLM 配置失败', e)
  }
}

const startEditMyLLM = () => {
  myLLM.editing = true
  myLLM.editKey = false
  myLLM.showKey = false
  myLLM.error = ''
  if (myLLM.configured) {
    myLLM.form.llm_api_key = ''
    myLLM.form.llm_base_url = myLLM.settings.llm_base_url || ''
    myLLM.form.llm_model = myLLM.settings.llm_model || ''
    myLLM.form.llm_timeout = myLLM.settings.llm_timeout || 120
  } else {
    myLLM.form.llm_api_key = ''
    myLLM.form.llm_base_url = ''
    myLLM.form.llm_model = ''
    myLLM.form.llm_timeout = 120
  }
}

const saveMyLLM = async () => {
  myLLM.error = ''
  // 验证
  if (!myLLM.form.llm_base_url.trim()) {
    myLLM.error = 'Base URL 不能为空'
    return
  }
  const urlResult = validateBaseUrl(myLLM.form.llm_base_url, 'Base URL')
  if (!urlResult.valid) {
    myLLM.error = urlResult.error
    return
  }
  if (!myLLM.form.llm_model.trim()) {
    myLLM.error = '模型名称不能为空'
    return
  }

  myLLM.saving = true
  try {
    const payload = {
      llm_base_url: myLLM.form.llm_base_url.trim(),
      llm_model: myLLM.form.llm_model.trim(),
      llm_timeout: myLLM.form.llm_timeout
    }
    if (myLLM.form.llm_api_key) {
      payload.llm_api_key = myLLM.form.llm_api_key.trim()
    }
    await updateMyLLMConfig(payload)
    toast.success('LLM 配置已保存')
    await loadMyLLM()
  } catch (e) {
    myLLM.error = `保存失败: ${e.message}`
  } finally {
    myLLM.saving = false
  }
}

const deleteMyLLM = async () => {
  if (!confirm('确定要清除 LLM 配置吗？清除后需要重新配置才能使用 AI 功能。')) return

  myLLM.saving = true
  try {
    await updateMyLLMConfig({
      llm_api_key: '',
      llm_base_url: '',
      llm_model: '',
      llm_timeout: 120
    })
    toast.success('LLM 配置已清除')
    await loadMyLLM()
  } catch (e) {
    myLLM.error = `清除失败: ${e.message}`
  } finally {
    myLLM.saving = false
  }
}

// ── Admin global config ──
const addCat1 = () => {
  taxonomy.categories.push({ cat1: '', children: [''], _open: true })
}
const removeCat1 = (index) => {
  taxonomy.categories.splice(index, 1)
}

const onSwitchPosition = async (pos) => {
  if (pos === taxonomy.job_position) return
  try {
    // 仅本地更新，不调用后端 API（等 saveProfile 统一提交）
    taxonomy.job_position = pos
    positionOnlyChanged.value = true
    if (!availablePositions.value.includes(pos)) {
      availablePositions.value.push(pos)
    }
    // 重新加载分类配置（绕过缓存）
    if (props.isAdmin) {
      const data = await fetchProfile({ noCache: true })
      const s = data.settings
      if (s.taxonomy_config) {
        try {
          const tc = typeof s.taxonomy_config === 'string' ? JSON.parse(s.taxonomy_config) : s.taxonomy_config
          taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        } catch { taxonomy.categories = [] }
      } else {
        taxonomy.categories = []
      }
      availablePositions.value = data.settings.available_positions || availablePositions.value
      // 确保当前岗位在列表中（新增岗位可能还没写入后端）
      if (!availablePositions.value.includes(taxonomy.job_position)) {
        availablePositions.value.push(taxonomy.job_position)
      }
    } else {
      const data = await fetchPublicProfile({ noCache: true })
      if (data.settings?.taxonomy_config) {
        try {
          const tc = typeof data.settings.taxonomy_config === 'string' ? JSON.parse(data.settings.taxonomy_config) : data.settings.taxonomy_config
          taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        } catch { taxonomy.categories = [] }
      }
    }
  } catch (e) {
    toast.error(`加载分类失败: ${e.message}`)
  }
}

const addPosition = async () => {
  const pos = newPositionInput.value.trim()
  if (!pos) return
  if (pos.length > 30) {
    toast.warning('岗位名称不能超过 30 个字符')
    return
  }
  if (!/^[一-龥a-zA-Z0-9\s/\-_()（）]+$/.test(pos)) {
    toast.warning('岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号')
    return
  }
  if (availablePositions.value.includes(pos)) {
    toast.warning('该岗位已存在')
    return
  }
  newPositionInput.value = ''
  await onSwitchPosition(pos)
}

const onDeletePosition = async (pos) => {
  if (!confirm(`确定要删除岗位"${pos}"吗？`)) return
  try {
    await deletePosition(pos)
    // 从列表中移除
    availablePositions.value = availablePositions.value.filter(p => p !== pos)
    // 如果删除的是当前岗位，切换到第一个可用岗位
    if (taxonomy.job_position === pos && availablePositions.value.length > 0) {
      await onSwitchPosition(availablePositions.value[0])
    }
    toast.success(`岗位"${pos}"已删除`)
  } catch (e) {
    toast.error(`删除失败: ${e.message}`)
  }
}

// ── AI Taxonomy Suggestion ──
const onGenerateTaxonomy = async () => {
  if (!taxonomy.job_position) {
    toast.warning('请先选择目标岗位')
    return
  }
  aiTaxonomyLoading.value = true
  try {
    const data = await generateTaxonomy()
    aiTaxonomyPreview.value = data
  } catch (e) {
    toast.error(`AI生成失败: ${e.message}`)
  } finally {
    aiTaxonomyLoading.value = false
  }
}

const onConfirmTaxonomy = async () => {
  if (!aiTaxonomyPreview.value) return
  try {
    await confirmTaxonomy(aiTaxonomyPreview.value.categories)
    // 更新本地状态
    taxonomy.categories = aiTaxonomyPreview.value.categories.map(c => ({ ...c, _open: false }))
    aiTaxonomyPreview.value = null
    toast.success('分类体系已更新')
    emit('settings-saved')
  } catch (e) {
    toast.error(`保存失败: ${e.message}`)
  }
}

const onCancelTaxonomy = () => {
  aiTaxonomyPreview.value = null
}

// ── 保存为个人分类 ──
const onSavePersonalTaxonomy = async () => {
  if (!taxonomy.categories || taxonomy.categories.length === 0) {
    toast.warning('没有可保存的分类')
    return
  }
  try {
    const validCategories = taxonomy.categories
      .filter(c => c.cat1.trim())
      .map(c => ({ cat1: c.cat1.trim(), children: c.children.filter(x => x.trim()) }))
    await savePersonalTaxonomy(validCategories)
    toast.success('已保存为个人分类')
  } catch (e) {
    toast.error(`保存失败: ${e.message}`)
  }
}

// ── 分享分类 ──
const onShareTaxonomy = async () => {
  if (!taxonomy.categories || taxonomy.categories.length === 0) {
    toast.warning('没有可分享的分类')
    return
  }
  try {
    // 先保存为个人分类
    const validCategories = taxonomy.categories
      .filter(c => c.cat1.trim())
      .map(c => ({ cat1: c.cat1.trim(), children: c.children.filter(x => x.trim()) }))
    const result = await savePersonalTaxonomy(validCategories)

    // 然后分享
    if (result.taxonomy && result.taxonomy.id) {
      await shareTaxonomy(result.taxonomy.id)
      toast.success('分类已分享')
    }
  } catch (e) {
    toast.error(`分享失败: ${e.message}`)
  }
}

// ── 获取公开分类 ──
const loadPublicTaxonomies = async () => {
  publicTaxonomiesLoading.value = true
  try {
    const data = await fetchPublicTaxonomies()
    publicTaxonomies.value = data.taxonomies || []
  } catch (e) {
    toast.error(`获取公开分类失败: ${e.message}`)
  } finally {
    publicTaxonomiesLoading.value = false
  }
}

// ── 使用公开分类 ──
const onUsePublicTaxonomy = (publicTaxonomy) => {
  taxonomy.categories = publicTaxonomy.categories.map(c => ({ ...c, _open: false }))
  showPublicTaxonomies.value = false
  toast.success(`已加载"${publicTaxonomy.position_name}"的分类`)
}

// ── 删除公开分类（管理员） ──
const onDeletePublicTaxonomy = async (tax) => {
  if (!confirm(`确定要删除"${tax.position_name}"的公开分类吗？`)) return
  try {
    await deletePublicTaxonomy(tax.id)
    publicTaxonomies.value = publicTaxonomies.value.filter(t => t.id !== tax.id)
    toast.success('已删除公开分类')
  } catch (e) {
    toast.error(`删除失败: ${e.message}`)
  }
}

const form = reactive({
  active_season: '',
})

const loadProfile = async () => {
  try {
    let data, s
    if (props.isAdmin) {
      data = await fetchProfile()
      s = data.settings
      form.active_season = s.active_season || ''
      seasons.value = data.available_seasons || []
    } else {
      data = await fetchPublicProfile()
      s = data.settings || {}
      seasons.value = data.available_seasons || []
    }

    availablePositions.value = s.available_positions || ['agent开发/大模型应用开发/大模型开发']
    if (s.taxonomy_config) {
      try {
        const tc = typeof s.taxonomy_config === 'string' ? JSON.parse(s.taxonomy_config) : s.taxonomy_config
        taxonomy.job_position = tc.job_position || s.current_job_position || 'agent开发/大模型应用开发/大模型开发'
        taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        originalPosition.value = taxonomy.job_position
      } catch { /* ignore parse error */ }
    }
  } catch (e) {
    console.error('加载配置失败', e)
  }
}

watch(() => props.visible, (val) => {
  if (val) {
    saveMessage.value = ''
    positionOnlyChanged.value = false
    loadMyLLM()
    loadProfile()
  }
})

watch(showPublicTaxonomies, (val) => {
  if (val) loadPublicTaxonomies()
})

const saveProfile = async () => {
  isSaving.value = true
  saveMessage.value = ''
  try {
    // 如果岗位有变更，先调用切换 API
    if (positionOnlyChanged.value) {
      if (props.isAdmin) {
        await switchPosition(taxonomy.job_position)
      } else {
        await switchMyPosition(taxonomy.job_position)
      }
    }

    const payload = {
      active_season: form.active_season,
    }

    const validCategories = taxonomy.categories
      .filter(c => c.cat1.trim())
      .map(c => ({ cat1: c.cat1.trim(), children: c.children.filter(x => x.trim()) }))
    if (validCategories.length > 0) {
      payload.taxonomy_config = JSON.stringify({ job_position: taxonomy.job_position, categories: validCategories })
    }

    await updateProfile(payload)
    invalidateCache()  // 清除所有 GET 缓存，确保 loadAllData 获取最新数据
    emit('update:activeSeason', form.active_season)
    await loadProfile()

    saveMessage.value = '全局配置已保存'
    saveSuccess.value = true
    originalPosition.value = taxonomy.job_position
    if (positionOnlyChanged.value) {
      emit('position-changed')
    } else {
      emit('settings-saved')
    }
    positionOnlyChanged.value = false
    setTimeout(() => { saveMessage.value = '' }, 3000)
  } catch (e) {
    saveMessage.value = `保存失败: ${e.message}`
    saveSuccess.value = false
  } finally {
    isSaving.value = false
  }
}

const addSeason = async () => {
  const result = validateSeason(newSeason.value)
  if (!result.valid) {
    saveMessage.value = result.error
    saveSuccess.value = false
    return
  }
  if (seasons.value.includes(result.value)) {
    saveMessage.value = '该招聘季已存在'
    saveSuccess.value = false
    return
  }
  seasons.value.push(result.value)
  form.active_season = result.value
  newSeason.value = ''

  try {
    await updateProfile({ active_season: result.value })
    emit('update:activeSeason', result.value)
    toast.success(`招聘季「${result.value}」已添加并设为当前`)
  } catch (e) {
    saveMessage.value = `添加失败: ${e.message}`
    saveSuccess.value = false
    seasons.value = seasons.value.filter(s => s !== result.value)
  }
}
</script>

<style scoped>
/* SettingsPanel styles */
</style>
