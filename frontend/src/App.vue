<template>
    <div class="min-h-screen p-3 lg:p-8 max-w-[98%] mx-auto bg-slate-50">
    <header class="mb-6 lg:mb-10 text-center">
      <h1 class="text-2xl lg:text-4xl font-bold text-gray-900 mb-2">多模态 JD 与面经智能解析系统</h1>
      <p class="text-sm lg:text-base text-gray-500">将零散的内容放至暂存区，确认无误后一键提交解析与增量聚类</p>
    </header>

    <div class="bg-white rounded-xl shadow-md border border-gray-200 mb-6 lg:mb-10 overflow-hidden">
      <div class="bg-gray-50 p-4 border-b border-gray-200 flex items-center gap-4">
        <label class="font-semibold text-gray-700 whitespace-nowrap">来源链接 (URL):</label>
        <input 
          v-model="sourceUrl"
          type="text" 
          class="flex-1 border border-gray-300 rounded-lg p-2 focus:ring-blue-500 focus:border-blue-500"
          placeholder="粘贴小红书/牛客网帖子链接 (用于去重，避免重复录入)"
        />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 divide-x divide-gray-100">
        <div class="p-4 lg:p-6 flex flex-col">
          <label class="block text-sm font-semibold text-gray-700 mb-2">补充纯文本内容</label>
          <textarea 
            v-model="stagedText"
            class="flex-1 w-full border border-gray-300 rounded-lg p-3 focus:ring-blue-500 focus:border-blue-500 resize-none"
            placeholder="在此处粘贴面经或 JD 的纯文本内容（可与右侧图片组合提交）..."
          ></textarea>
        </div>

        <div 
          class="p-4 lg:p-6 flex flex-col transition-colors relative"
          :class="isDragging ? 'bg-blue-50' : ''"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="handleDrop"
        >
          <div class="flex justify-between items-center mb-2">
            <label class="block text-sm font-semibold text-gray-700">图片暂存区 ({{ stagedFiles.length }} 张)</label>
            <div>
              <input type="file" multiple class="hidden" ref="fileInput" @change="handleFileSelect" accept="image/*" />
              <button @click="$refs.fileInput.click()" class="text-xs bg-gray-200 text-gray-700 px-3 py-1 rounded hover:bg-gray-300 transition">
                + 选择图片
              </button>
            </div>
          </div>
          
          <div class="flex-1 border-2 border-dashed border-gray-300 rounded-lg p-4 overflow-y-auto max-h-48 bg-gray-50">
            <div v-if="stagedFiles.length === 0" class="h-full flex flex-col items-center justify-center text-gray-400">
              <svg class="h-8 w-8 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <p class="text-sm">拖拽图片到此处，或使用 Ctrl+V 粘贴</p>
            </div>
            
            <div v-else class="flex flex-wrap gap-3">
              <div v-for="(item, index) in stagedFiles" :key="item.id" class="relative group">
                <img :src="item.preview" class="h-24 w-24 object-cover rounded-md border border-gray-300 shadow-sm" @error="handleImgError" />
                <button @click="removeFile(index)" class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition shadow">
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="bg-gray-50 border-t border-gray-200 p-4 flex flex-col items-center">
        <div class="flex gap-4 w-full justify-end mb-4">
          <button @click="clearStaging" :disabled="isUploading" class="px-5 py-2 rounded-lg text-gray-600 hover:bg-gray-200 transition">
            清空暂存
          </button>
          <button 
            @click="submitAll" 
            :disabled="isUploading || (!stagedText.trim() && stagedFiles.length === 0)"
            class="bg-blue-600 text-white font-bold px-8 py-2 rounded-lg hover:bg-blue-700 transition shadow-md disabled:bg-blue-300 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <svg v-if="isUploading" class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
            {{ isUploading ? '大模型正在提取及增量聚类中...' : '提交联合解析' }}
          </button>
        </div>

        <div v-if="uploadResult" class="text-green-600 font-medium w-full text-center bg-green-50 p-2 rounded">
          ✅ 解析成功！已提取为：<span class="font-bold ml-1">{{ uploadResult.type }}</span> （新考点已丢入后台排队生成解答）
        </div>
        <div v-if="uploadError" class="text-red-600 font-medium w-full text-center bg-red-50 p-2 rounded">
          ❌ {{ uploadError }}
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-4 gap-8">
      
      <div class="lg:col-span-1 bg-white p-4 lg:p-6 rounded-xl shadow-sm border border-gray-100 h-fit lg:sticky lg:top-8 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto custom-scrollbar">
        <h2 class="text-2xl font-bold mb-6">📊 全局分析</h2>
        <button @click="fetchAnalytics" class="w-full bg-indigo-50 text-indigo-700 px-4 py-2 rounded mb-6 hover:bg-indigo-100 transition">
          刷新分析数据
        </button>

        <div class="mb-8">
          <h3 class="text-lg font-semibold text-gray-700 mb-3 border-l-4 border-purple-500 pl-2">考点分布 (精炼题库)</h3>
          <div ref="chartRef" class="w-full h-[320px]"></div>
        </div>
        
        <div class="mb-8">
          <h3 class="text-lg font-semibold text-gray-700 mb-3 border-l-4 border-blue-500 pl-2">热点技术栈 (JD)</h3>
          <ul class="space-y-2">
            <li v-for="(count, tech) in analytics.tech_trends" :key="tech" class="flex justify-between items-center text-sm px-2">
              <span class="bg-gray-100 px-2 py-1 rounded break-all mr-2">{{ tech }}</span>
              <span class="text-gray-500 font-mono whitespace-nowrap">{{ count }} 次</span>
            </li>
            <li v-if="!analytics.tech_trends || Object.keys(analytics.tech_trends).length === 0" class="text-gray-400 text-sm px-2">暂无数据</li>
          </ul>
        </div>

        <div>
          <h3 class="text-lg font-semibold text-gray-700 mb-3 border-l-4 border-green-500 pl-2">题库分类目录</h3>
          <ul class="space-y-1">
            <li 
              @click="selectTag('全部')"
              class="flex justify-between items-center text-sm cursor-pointer p-2 rounded transition-colors border border-transparent"
              :class="selectedTag === '全部' ? 'bg-green-50 text-green-700 font-bold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
            >
              <span>🌟 全部高频真题</span>
              <span class="text-gray-500 font-mono">{{ masterBank.length }} 题</span>
            </li>
            <li 
              v-for="(count, topic) in popularTags" :key="topic" 
              @click="selectTag(topic)"
              class="flex justify-between items-center text-sm cursor-pointer p-2 rounded transition-colors border border-transparent group"
              :class="selectedTag === topic ? 'bg-green-50 text-green-700 font-bold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
            >
              <span class="break-all mr-2 group-hover:text-green-600 transition-colors">{{ topic }}</span>
              <span class="text-gray-400 font-mono whitespace-nowrap group-hover:text-green-500">{{ count }} 题</span>
            </li>
            <li v-if="!popularTags || Object.keys(popularTags).length === 0" class="text-gray-400 text-sm p-2">暂无数据</li>
          </ul>
        </div>
      </div>

      <div class="lg:col-span-3 bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        
        <div class="flex flex-wrap border-b bg-gray-50">
          <button 
            @click="activeTab = 'JD'"
            class="flex-1 min-w-0 py-3 lg:py-4 text-sm lg:text-lg font-medium transition-colors"
            :class="activeTab === 'JD' ? 'text-blue-600 bg-white border-b-2 border-blue-600' : 'text-gray-500 hover:text-gray-700'"
          >
            JD
          </button>
          <button 
            @click="activeTab = 'Interview'"
            class="flex-1 min-w-0 py-3 lg:py-4 text-sm lg:text-lg font-medium transition-colors"
            :class="activeTab === 'Interview' ? 'text-gray-600 bg-white border-b-2 border-gray-600' : 'text-gray-500 hover:text-gray-700'"
          >
            面经
          </button>
          <button 
            @click="activeTab = 'MasterBank'"
            class="flex-1 min-w-0 py-3 lg:py-4 text-sm lg:text-lg font-bold transition-colors"
            :class="activeTab === 'MasterBank' ? 'text-red-600 bg-white border-b-2 border-red-600' : 'text-gray-500 hover:text-gray-700'"
          >
            🔥题库
          </button>
          <button 
            @click="activeTab = 'MockInterview'; startMockInterview()"
            class="flex-1 min-w-0 py-3 lg:py-4 text-sm lg:text-lg font-bold transition-colors"
            :class="activeTab === 'MockInterview' ? 'text-orange-600 bg-white border-b-2 border-orange-600' : 'text-gray-500 hover:text-gray-700'"
          >
            🎯模拟
          </button>
        </div>

        <div class="p-3 lg:p-6">
          <!-- 搜索和筛选栏（MasterBank 和 MockInterview 共用） -->
          <div v-if="activeTab === 'MasterBank' || activeTab === 'MockInterview'" class="mb-4 flex flex-wrap gap-3 items-center">
            <div class="flex-1 min-w-[200px]">
              <input 
                v-model="searchQuery"
                type="text" 
                class="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-blue-500 focus:border-blue-500"
                placeholder="🔍 搜索题目关键词..."
                @input="onSearchInput"
              />
            </div>
            <select v-model="filterDifficulty" class="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
              <option value="">全部难度</option>
              <option value="L1">L1-基础</option>
              <option value="L2">L2-中等</option>
              <option value="L3">L3-困难</option>
            </select>
            <button 
              v-if="activeTab === 'MasterBank'"
              @click="showStarredOnly = !showStarredOnly"
              class="px-3 py-2 text-sm rounded-lg border transition"
              :class="showStarredOnly ? 'bg-yellow-100 border-yellow-300 text-yellow-700' : 'bg-white border-gray-300 text-gray-500 hover:bg-gray-50'"
            >
              {{ showStarredOnly ? '⭐ 仅看收藏' : '☆ 全部' }}
            </button>
          </div>

          <div class="flex flex-wrap justify-between items-center mb-4 lg:mb-6 gap-2">
            <h2 class="text-lg lg:text-xl font-bold flex items-center gap-2">
              {{ activeTab === 'JD' ? '职位描述库' : activeTab === 'Interview' ? '原始面经流水' : activeTab === 'MockInterview' ? '🎯 模拟面试' : '必考真题库' }}
              <span v-if="activeTab === 'MasterBank' && selectedTag !== '全部'" class="text-sm font-normal bg-green-100 text-green-700 px-3 py-1 rounded-full border border-green-200">
                分类筛选: {{ selectedTag }}
              </span>
              <span v-if="activeTab === 'MasterBank' && searchQuery" class="text-sm font-normal bg-blue-100 text-blue-700 px-3 py-1 rounded-full border border-blue-200">
                搜索: {{ searchQuery }}
              </span>
            </h2>
            <div class="flex flex-wrap gap-2">
              <button v-if="activeTab === 'MasterBank'" @click="triggerBuildMasterBank" class="text-sm bg-purple-600 text-white font-bold px-4 py-2 rounded hover:bg-purple-700 transition">
                {{ isBuilding ? '正在提取全量特征并聚类去重...' : '⚡ 全量重新计算题库排序' }}
              </button>
              <button v-if="activeTab === 'MockInterview'" @click="startMockInterview" class="text-sm bg-orange-600 text-white font-bold px-4 py-2 rounded hover:bg-orange-700 transition">
                🔄 换一批题目
              </button>
              
              <button @click="fetchTableData" :disabled="isDataLoading" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed">
            {{ isDataLoading ? '加载中...' : '刷新数据' }}
          </button>
              <button v-if="activeTab !== 'MasterBank' && activeTab !== 'MockInterview'" @click="downloadCSV" class="text-sm bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700">一键导出 CSV</button>
            </div>
          </div>

          <!-- 全局数据加载错误提示 -->
          <div v-if="dataLoadError" class="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center justify-between">
            <span>⚠️ {{ dataLoadError }}</span>
            <button @click="fetchTableData" class="text-sm bg-red-100 hover:bg-red-200 px-3 py-1 rounded transition">重试</button>
          </div>

          <!-- 全局数据加载骨架 -->
          <div v-if="isDataLoading && jdData.length === 0 && interviewData.length === 0 && masterBank.length === 0" class="py-10 text-center">
            <svg class="animate-spin h-8 w-8 text-blue-500 mx-auto mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
            <p class="text-gray-500">数据加载中...</p>
          </div>

          <div v-if="activeTab === 'JD'" class="overflow-x-auto w-full">
            <div class="mb-4 flex gap-2">
              <button @click="toggleSelectAllJd" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">全选/取消全选</button>
              <button @click="invertSelectionJd" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">反选</button>
              <div class="w-px h-5 bg-gray-300 mx-1 self-center"></div>
              <button @click="batchDeleteData('jd')" :disabled="selectedJdCount === 0" class="text-sm bg-red-100 text-red-700 px-3 py-1.5 rounded hover:bg-red-200 transition font-medium disabled:opacity-50 disabled:cursor-not-allowed">
                🗑️ 批量删除 ({{ selectedJdCount }})
              </button>
            </div>

            <table class="w-full text-left border-collapse min-w-full">
              <thead>
                <tr class="bg-gray-50 text-gray-600 text-sm">
                  <th class="p-3 border-b whitespace-nowrap w-10">选择</th>
                  <th class="p-3 border-b whitespace-nowrap">操作</th>
                  <th class="p-3 border-b whitespace-nowrap">公司</th>
                  <th class="p-3 border-b whitespace-nowrap">岗位名称</th>
                  <th class="p-3 border-b whitespace-nowrap">薪资范围</th>
                  <th class="p-3 border-b">核心技术</th>
                  <th class="p-3 border-b">加分项</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in jdData" :key="idx" class="border-b hover:bg-gray-50 text-sm" :class="row._selected ? 'bg-blue-50' : ''">
                  <td class="p-3 whitespace-nowrap text-center">
                    <input type="checkbox" v-model="row._selected" class="w-4 h-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500 cursor-pointer">
                  </td>
                  <td class="p-3 whitespace-nowrap">
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="row['来源链接']" target="_blank" class="text-blue-500 hover:underline mr-3" title="访问链接">🔗</a>
                    <span v-else class="text-gray-300 mr-3">-</span>
                    <button @click="deleteDataRow('jd', row.id)" class="text-red-500 hover:text-red-700 font-bold" title="删除该行">🗑️</button>
                  </td>

                  <td class="p-3 whitespace-nowrap group">
                    <div v-if="!row._isEditingCompany" class="flex items-center gap-2">
                      {{ row['公司'] }}
                      <button @click="row._isEditingCompany = true; row._editCompany = row['公司']" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition" title="编辑">✏️</button>
                    </div>
                    <div v-else class="flex items-center gap-1">
                      <input v-model="row._editCompany" class="border rounded px-2 py-1 w-24 text-sm" @keyup.enter="saveField('jd', row.id, 'company', row._editCompany, row, '_isEditingCompany', '公司')" />
                      <button @click="saveField('jd', row.id, 'company', row._editCompany, row, '_isEditingCompany', '公司')" class="text-green-500 hover:text-green-700" title="保存">💾</button>
                      <button @click="row._isEditingCompany = false" class="text-red-400 hover:text-red-600" title="取消">✖</button>
                    </div>
                  </td>

                  <td class="p-3 font-medium whitespace-nowrap group">
                    <div v-if="!row._isEditingTitle" class="flex items-center gap-2">
                      {{ row['岗位名称'] }}
                      <button @click="row._isEditingTitle = true; row._editTitle = row['岗位名称']" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition" title="编辑">✏️</button>
                    </div>
                    <div v-else class="flex items-center gap-1">
                      <input v-model="row._editTitle" class="border rounded px-2 py-1 w-32 text-sm" @keyup.enter="saveField('jd', row.id, 'job_title', row._editTitle, row, '_isEditingTitle', '岗位名称')" />
                      <button @click="saveField('jd', row.id, 'job_title', row._editTitle, row, '_isEditingTitle', '岗位名称')" class="text-green-500 hover:text-green-700" title="保存">💾</button>
                      <button @click="row._isEditingTitle = false" class="text-red-400 hover:text-red-600" title="取消">✖</button>
                    </div>
                  </td>

                  <td class="p-3 text-red-600 whitespace-nowrap">{{ row['薪资范围'] }}</td>
                  <td class="p-3 whitespace-pre-wrap break-words min-w-[200px]">{{ row['核心技术要求'] }}</td>
                  <td class="p-3 text-gray-500 whitespace-pre-wrap break-words">{{ row['加分项'] }}</td>
                </tr>
                <tr v-if="jdData.length === 0">
                  <td colspan="7" class="p-6 text-center text-gray-400">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="activeTab === 'Interview'" class="overflow-x-auto w-full">
            <div class="mb-4 flex gap-2">
              <button @click="toggleSelectAllInterview" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">全选/取消全选</button>
              <button @click="invertSelectionInterview" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">反选</button>
              <div class="w-px h-5 bg-gray-300 mx-1 self-center"></div>
              <button @click="batchReprocessInterview" :disabled="selectedInterviewCount === 0" class="text-sm bg-blue-100 text-blue-700 px-3 py-1.5 rounded hover:bg-blue-200 transition font-medium disabled:opacity-50 disabled:cursor-not-allowed">
                🔄 批量重新分析 ({{ selectedInterviewCount }})
              </button>
              <button @click="batchDeleteData('interview')" :disabled="selectedInterviewCount === 0" class="text-sm bg-red-100 text-red-700 px-3 py-1.5 rounded hover:bg-red-200 transition font-medium disabled:opacity-50 disabled:cursor-not-allowed">
                🗑️ 批量删除 ({{ selectedInterviewCount }})
              </button>
            </div>

            <table class="w-full text-left border-collapse min-w-full">
              <thead>
                <tr class="bg-gray-50 text-gray-600 text-sm">
                  <th class="p-3 border-b whitespace-nowrap w-10">选择</th>
                  <th class="p-3 border-b whitespace-nowrap">操作</th>
                  <th class="p-3 border-b whitespace-nowrap">公司</th>
                  <th class="p-3 border-b whitespace-nowrap">面试轮次</th>
                  <th class="p-3 border-b min-w-[120px]">考察重点</th>
                  <th class="p-3 border-b min-w-[300px]">具体题目清单</th>
                  <th class="p-3 border-b whitespace-nowrap">难度</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in interviewData" :key="idx" class="border-b hover:bg-gray-50 text-sm" :class="row._selected ? 'bg-blue-50' : ''">
                  <td class="p-3 whitespace-nowrap text-center">
                    <input type="checkbox" v-model="row._selected" class="w-4 h-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500 cursor-pointer">
                  </td>
                  <td class="p-3 whitespace-nowrap">
                    <button @click="reprocessInterview(row.id)" :disabled="reprocessingIds[row.id]" class="text-blue-500 hover:text-blue-700 font-bold mr-2 disabled:opacity-50" title="重新提取并打标">
                      <svg v-if="reprocessingIds[row.id]" class="animate-spin inline-block w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                      <span v-else>🔄</span>
                    </button>
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="row['来源链接']" target="_blank" class="text-blue-500 hover:underline mr-3" title="访问链接">🔗</a>
                    <span v-else class="text-gray-300 mr-3">-</span>
                    <button @click="deleteDataRow('interview', row.id)" class="text-red-500 hover:text-red-700 font-bold" title="删除该行">🗑️</button>
                  </td>

                  <td class="p-3 font-medium whitespace-nowrap group">
                    <div v-if="!row._isEditingCompany" class="flex items-center gap-2">
                      {{ row['公司'] }}
                      <button @click="row._isEditingCompany = true; row._editCompany = row['公司']" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition" title="编辑">✏️</button>
                    </div>
                    <div v-else class="flex items-center gap-1">
                      <input v-model="row._editCompany" class="border rounded px-2 py-1 w-24 text-sm" @keyup.enter="saveField('interview', row.id, 'company', row._editCompany, row, '_isEditingCompany', '公司')" />
                      <button @click="saveField('interview', row.id, 'company', row._editCompany, row, '_isEditingCompany', '公司')" class="text-green-500 hover:text-green-700" title="保存">💾</button>
                      <button @click="row._isEditingCompany = false" class="text-red-400 hover:text-red-600" title="取消">✖</button>
                    </div>
                  </td>

                  <td class="p-3 whitespace-nowrap group">
                    <div v-if="!row._isEditingRound" class="flex items-center gap-2">
                      {{ row['面试轮次'] }}
                      <button @click="row._isEditingRound = true; row._editRound = row['面试轮次']" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition" title="编辑">✏️</button>
                    </div>
                    <div v-else class="flex items-center gap-1">
                      <input v-model="row._editRound" class="border rounded px-2 py-1 w-20 text-sm" @keyup.enter="saveField('interview', row.id, 'round', row._editRound, row, '_isEditingRound', '面试轮次')" />
                      <button @click="saveField('interview', row.id, 'round', row._editRound, row, '_isEditingRound', '面试轮次')" class="text-green-500 hover:text-green-700" title="保存">💾</button>
                      <button @click="row._isEditingRound = false" class="text-red-400 hover:text-red-600" title="取消">✖</button>
                    </div>
                  </td>
                  <td class="p-3 whitespace-pre-wrap break-words group">
                    <div v-if="!row._isEditingFocus" class="flex items-start gap-2">
                      <span class="flex-1">{{ row['考察重点'] }}</span>
                      <button @click="row._isEditingFocus = true; row._editFocus = row['考察重点']" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition shrink-0" title="编辑">✏️</button>
                    </div>
                    <div v-else class="flex flex-col gap-1">
                      <textarea v-model="row._editFocus" rows="3" class="border rounded px-2 py-1 w-full text-sm"></textarea>
                      <div class="flex gap-1 justify-end">
                        <button @click="saveField('interview', row.id, 'focus', row._editFocus, row, '_isEditingFocus', '考察重点')" class="text-green-500 hover:text-green-700 text-sm" title="保存">💾</button>
                        <button @click="row._isEditingFocus = false" class="text-red-400 hover:text-red-600 text-sm" title="取消">✖</button>
                      </div>
                    </div>
                  </td>
                  <td class="p-3 whitespace-pre-wrap break-words leading-relaxed group">
                    <div v-if="!row._isEditingQuestions" class="flex items-start gap-2">
                      <span class="flex-1">{{ row['具体题目清单'] }}</span>
                      <button @click="row._isEditingQuestions = true; row._editQuestions = row['具体题目清单']" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition shrink-0" title="编辑">✏️</button>
                    </div>
                    <div v-else class="flex flex-col gap-1">
                      <textarea v-model="row._editQuestions" rows="6" class="border rounded px-2 py-1 w-full text-sm font-mono"></textarea>
                      <div class="flex gap-1 justify-end">
                        <button @click="saveField('interview', row.id, 'questions_list', row._editQuestions, row, '_isEditingQuestions', '具体题目清单')" class="text-green-500 hover:text-green-700 text-sm" title="保存">💾</button>
                        <button @click="row._isEditingQuestions = false" class="text-red-400 hover:text-red-600 text-sm" title="取消">✖</button>
                      </div>
                    </div>
                  </td>
                  <td class="p-3 whitespace-nowrap group">
                    <div v-if="!row._isEditingDifficulty" class="flex items-center gap-2">
                      <span class="px-2 py-1 rounded text-xs" :class="(row['难易程度'] || '').includes('难') ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'">
                        {{ row['难易程度'] || row['难度'] || '-' }}
                      </span>
                      <button @click="row._isEditingDifficulty = true; row._editDifficulty = row['难易程度'] || ''" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition" title="编辑">✏️</button>
                    </div>
                    <div v-else class="flex items-center gap-1">
                      <select v-model="row._editDifficulty" class="border rounded px-2 py-1 text-sm">
                        <option value="">未提供</option>
                        <option value="简单">简单</option>
                        <option value="中等">中等</option>
                        <option value="困难">困难</option>
                      </select>
                      <button @click="saveField('interview', row.id, 'difficulty', row._editDifficulty, row, '_isEditingDifficulty', '难易程度')" class="text-green-500 hover:text-green-700" title="保存">💾</button>
                      <button @click="row._isEditingDifficulty = false" class="text-red-400 hover:text-red-600" title="取消">✖</button>
                    </div>
                  </td>
                </tr>
                <tr v-if="interviewData.length === 0">
                  <td colspan="7" class="p-6 text-center text-gray-400">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 模拟面试模式 -->
          <div v-if="activeTab === 'MockInterview'" class="space-y-6">
            <div v-if="mockQuestions.length === 0" class="text-center py-10 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl">
              <p class="mb-2 text-lg">正在加载模拟面试题目...</p>
              <p class="text-sm">如果没有题目，请先录入面经数据。</p>
            </div>
            <div v-for="(q, qIdx) in mockQuestions" :key="q.id" class="border border-orange-200 rounded-xl overflow-hidden bg-white shadow-sm">
              <div class="p-5 bg-gradient-to-r from-orange-50 to-amber-50">
                <div class="flex items-start gap-4">
                  <div class="flex flex-col items-center justify-center bg-orange-100 text-orange-700 font-bold rounded-lg p-3 min-w-[50px] border border-orange-200">
                    <span class="text-xs font-normal text-orange-400">第</span>
                    <span class="text-xl leading-none">{{ qIdx + 1 }}</span>
                    <span class="text-xs font-normal text-orange-400">题</span>
                  </div>
                  <div class="flex-1">
                    <div class="flex gap-2 mb-2 items-center flex-wrap">
                      <span class="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
                      <span class="text-xs font-medium px-2 py-0.5 rounded" :class="String(q.difficulty).includes('L3') ? 'bg-red-50 text-red-600' : String(q.difficulty).includes('L2') ? 'bg-yellow-50 text-yellow-600' : 'bg-green-50 text-green-600'">
                        {{ q.difficulty || '-' }}
                      </span>
                      <span class="text-xs text-gray-400 ml-auto">考频 {{ q.frequency }}</span>
                    </div>
                    <h3 class="text-lg font-bold text-gray-800 leading-snug">{{ q.question }}</h3>
                  </div>
                </div>
              </div>
              <div class="border-t border-orange-100">
                <button 
                  @click="q._showAnswer = !q._showAnswer"
                  class="w-full py-3 text-sm font-medium text-orange-600 hover:bg-orange-50 transition flex items-center justify-center gap-2"
                >
                  {{ q._showAnswer ? '🙈 收起参考答案' : '👁️ 查看参考答案（先自己想想！）' }}
                </button>
                <div v-if="q._showAnswer" class="p-6 bg-slate-50 border-t border-orange-100">
                  <div v-if="q.ai_answer" class="text-gray-700 text-sm leading-relaxed" v-html="renderMarkdown(q.ai_answer)"></div>
                  <div v-else class="text-center py-4">
                    <p class="text-gray-400 mb-3 text-sm">该题目暂无 AI 生成的参考答案。</p>
                    <button @click="generateAnswer(q)" class="bg-blue-100 text-blue-700 font-bold px-6 py-2 rounded-lg hover:bg-blue-200 transition text-sm">
                      ✨ 召唤 AI 生成参考答案
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="activeTab === 'MasterBank'" class="space-y-4">
            <div class="flex flex-wrap justify-end items-center bg-white p-4 rounded-lg border border-gray-200 shadow-sm gap-4">
              <div class="flex items-center gap-2">
                <button @click="toggleSelectAll" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">全选/取消全选</button>
                <button @click="invertSelection" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">反选</button>
                <div class="w-px h-5 bg-gray-300 mx-1"></div>
                <button @click="batchGenerateAnswers" :disabled="selectedCount === 0" class="text-sm bg-blue-100 text-blue-700 px-3 py-1.5 rounded hover:bg-blue-200 transition font-medium flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed">
                  ✨ 批量生成答案 ({{ selectedCount }})
                </button>
                <button @click="batchDeleteMasterBank" :disabled="selectedCount === 0" class="text-sm bg-red-100 text-red-700 px-3 py-1.5 rounded hover:bg-red-200 transition font-medium flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed">
                  🗑️ 批量删除 ({{ selectedCount }})
                </button>
              </div>
            </div>

            <div v-if="filteredMasterBank.length === 0" class="text-center py-10 text-gray-400 border-2 border-dashed border-gray-200 rounded-xl">
              <p class="mb-2">暂无符合条件的精炼真题。</p>
              <p class="text-sm">你可以点击左侧“全部高频真题”查看所有，或者录入更多面经自动扩充。</p>
            </div>

            <div v-for="q in filteredMasterBank" :key="q.id" class="border border-gray-200 rounded-lg overflow-hidden bg-white hover:border-blue-300 transition shadow-sm" :class="q._selected ? 'border-blue-400 ring-1 ring-blue-400' : ''">
              
              <div class="p-5 flex gap-4 items-start cursor-pointer hover:bg-slate-50 transition" @click="toggleAnswer(q)">
                <div class="flex items-center h-full pt-3" @click.stop>
                  <input type="checkbox" v-model="q._selected" class="w-5 h-5 text-blue-600 rounded border-gray-300 focus:ring-blue-500 cursor-pointer">
                </div>
                <div class="flex flex-col items-center justify-center bg-red-50 text-red-600 font-bold rounded-lg p-3 min-w-[60px] border border-red-100 shadow-inner">
                  <span class="text-xs font-normal text-red-400 mb-0.5">考频</span>
                  <span class="text-xl leading-none">{{ q.frequency }}</span>
                </div>
                
                <div class="flex-1">
                  <div class="flex gap-2 mb-2 items-center flex-wrap">
                    <span class="bg-indigo-100 text-indigo-700 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
                    <span v-for="tag in (q.tags ? q.tags.split(',') : [])" :key="tag" class="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded border border-gray-200">
                      {{ tag }}
                    </span>
                    <span class="text-xs ml-auto font-medium px-2 py-0.5 rounded" :class="String(q.difficulty).includes('困难') || String(q.difficulty).includes('L3') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'">
                      难度: {{ q.difficulty || '-' }}
                    </span>
                    <button @click.stop="toggleStar(q)" class="text-lg ml-1 transition-transform hover:scale-125" :title="q.is_starred ? '取消收藏' : '收藏'">
                      {{ q.is_starred ? '⭐' : '☆' }}
                    </button>
                    <button @click.stop="retagQuestion(q)" :disabled="q._isRetagging" class="text-xs bg-yellow-50 text-yellow-700 px-2 py-0.5 rounded border border-yellow-200 hover:bg-yellow-100 transition disabled:opacity-50 ml-2">
                      <svg v-if="q._isRetagging" class="animate-spin inline-block w-3 h-3 mr-1" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                      {{ q._isRetagging ? '打标中...' : '🏷️ 重新打标' }}
                    </button>
                  </div>
                  <h3 class="text-lg font-bold text-gray-800 leading-snug">{{ q.question }}</h3>
                </div>

                <div class="text-gray-400 mt-2">
                  <svg class="w-6 h-6 transform transition-transform" :class="q._showAnswer ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                </div>
              </div>

              <div v-if="q._showAnswer" class="border-t border-gray-100 bg-slate-50 p-6 relative group">
                
                <div v-if="q.sources && q.sources.length > 0" class="mb-4 bg-indigo-50/50 border border-indigo-100 rounded-lg p-3">
                  <h4 class="text-sm font-bold text-indigo-800 mb-2 flex items-center gap-1">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path></svg>
                    追溯面经源头 (共 {{ q.sources.length }} 次出现)
                  </h4>
                  <div class="flex flex-wrap gap-2 text-xs">
                    <span v-for="(src, idx) in q.sources" :key="idx" class="bg-white border border-indigo-200 text-indigo-700 px-2.5 py-1 rounded-md inline-flex items-center shadow-sm">
                      {{ src.company === '未提供' ? '未知公司' : src.company }}
                      <span class="text-indigo-400 mx-1">|</span>
                      {{ src.round === '未提供' ? '未知轮次' : src.round }}
                      <a v-if="src.url && src.url !== '未提供链接'" :href="src.url" target="_blank" class="ml-2 text-blue-500 hover:text-blue-700 font-bold transition-colors" title="访问原帖">
                        [原帖链接]
                      </a>
                    </span>
                  </div>
                </div>
                <div v-if="q._isEditingAnswer" class="flex flex-col gap-3">
                  <label class="font-bold text-gray-700 flex items-center gap-2">
                    ✏️ 编辑答案
                  </label>
                  <textarea v-model="q._editAnswer" rows="8" class="w-full border border-blue-300 rounded p-4 text-sm focus:ring-blue-500 focus:border-blue-500 shadow-inner font-mono"></textarea>
                  <div class="flex gap-2 justify-end mt-2">
                    <button @click="q._isEditingAnswer = false" class="px-5 py-2 bg-gray-200 rounded-lg text-gray-700 text-sm hover:bg-gray-300 transition">取消</button>
                    <button @click="saveField('master_question_bank', q.id, 'ai_answer', q._editAnswer, q, '_isEditingAnswer', 'ai_answer')" class="px-5 py-2 bg-blue-600 text-white font-bold rounded-lg text-sm hover:bg-blue-700 transition shadow">保存修改</button>
                  </div>
                </div>

                <div v-else>
                  <button v-if="q.ai_answer" @click="q._isEditingAnswer = true; q._editAnswer = q.ai_answer" class="absolute top-4 right-4 bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 px-3 py-1 rounded text-xs transition opacity-0 group-hover:opacity-100 shadow-sm z-10">
                    ✏️ 修改答案
                  </button>
                  
                  <div v-if="q.ai_answer && !isFailedAnswer(q.ai_answer)" class="text-gray-700 text-sm leading-relaxed max-w-none" v-html="renderMarkdown(q.ai_answer)"></div>
                  
                  <div v-else-if="q._isLoadingAnswer" class="flex flex-col items-center justify-center py-6 text-blue-600 gap-3">
                    <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    <span class="font-medium">大模型正在为您生成高质量解答，请稍候...</span>
                  </div>

                  <div v-else class="text-center py-4">
                    <p v-if="isFailedAnswer(q.ai_answer)" class="text-red-500 mb-3 text-sm">⚠️ 上次自动生成失败，请手动重试。</p>
                    <p v-else class="text-gray-500 mb-3 text-sm">该题目是由系统后台刚刚抽取出的新考点，尚未生成解答。</p>
                    <button @click.stop="generateAnswer(q)" class="bg-blue-100 text-blue-700 font-bold px-6 py-2.5 rounded-lg hover:bg-blue-200 transition shadow-sm border border-blue-200">
                      ✨ 召唤 AI 生成满分回答
                    </button>
                    <button @click="q._isEditingAnswer = true; q._editAnswer = ''" class="ml-3 bg-gray-100 text-gray-600 font-bold px-6 py-2.5 rounded-lg hover:bg-gray-200 transition shadow-sm border border-gray-200">
                      ✏️ 手动编写答案
                    </button>
                  </div>
                </div>
              </div>

            </div>
          </div>

        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { marked } from 'marked'
import * as echarts from 'echarts'
import { get, post, put, del, upload, cancelAllRequests } from './utils/http.js'

const API_BASE = '/api'

const sourceUrl = ref('')
const stagedText = ref('')
const stagedFiles = ref([])
const isDragging = ref(false)

const isUploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref(null)
const isDataLoading = ref(false)
const dataLoadError = ref(null)

const activeTab = ref('MasterBank')
const jdData = ref([])
const interviewData = ref([])
const masterBank = ref([])
const isBuilding = ref(false)
const analytics = ref({ tech_trends: {} })

const selectedTag = ref('全部')
const searchQuery = ref('')
const filterDifficulty = ref('')
const showStarredOnly = ref(false)
const mockQuestions = ref([])

const reprocessingIds = ref({})

const chartRef = ref(null)
let myChart = null
let resizeHandler = null

const popularTags = computed(() => {
  const counts = {}
  masterBank.value.forEach(q => {
    const rawCat = q.cat1 || '未分类'
    const cats = rawCat.split(',').map(c => c.trim()).filter(c => c)
    if (cats.length === 0) {
      counts['未分类'] = (counts['未分类'] || 0) + 1
    } else {
      cats.forEach(cat => {
        counts[cat] = (counts[cat] || 0) + 1
      })
    }
  })
  // 按出现次数降序排序
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .reduce((acc, [key, val]) => { acc[key] = val; return acc }, {})
})

const selectedJdCount = computed(() => jdData.value.filter(item => item._selected).length)
const selectedInterviewCount = computed(() => interviewData.value.filter(item => item._selected).length)

const toggleSelectAllJd = () => {
  const allSelected = jdData.value.length > 0 && jdData.value.every(q => q._selected)
  jdData.value.forEach(q => q._selected = !allSelected)
}
const invertSelectionJd = () => jdData.value.forEach(q => q._selected = !q._selected)

const toggleSelectAllInterview = () => {
  const allSelected = interviewData.value.length > 0 && interviewData.value.every(q => q._selected)
  interviewData.value.forEach(q => q._selected = !allSelected)
}
const invertSelectionInterview = () => interviewData.value.forEach(q => q._selected = !q._selected)

const handleGlobalPaste = (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return

  const items = e.clipboardData.items
  for (let item of items) {
    if (item.type.indexOf('image') !== -1) {
      const file = item.getAsFile()
      addFileToStaging(file)
    } else if (item.type === 'text/plain') {
      item.getAsString((text) => {
        stagedText.value += (stagedText.value ? '\n' : '') + text
      })
    }
  }
}

onMounted(() => {
  window.addEventListener('paste', handleGlobalPaste)
  
  if (chartRef.value) {
    myChart = echarts.init(chartRef.value)
    resizeHandler = () => myChart && myChart.resize()
    window.addEventListener('resize', resizeHandler)
  }
  
  fetchTableData()
  fetchAnalytics()
})

onUnmounted(() => {
  window.removeEventListener('paste', handleGlobalPaste)
  if (myChart && resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
  if (myChart) {
    myChart.dispose()
    myChart = null
  }
  // 取消所有进行中的请求
  cancelAllRequests()
})

const updateDistributionChart = () => {
  if (!myChart || !masterBank.value.length) return

  const cat1Map = {}

  masterBank.value.forEach(item => {
    const c1 = (item.cat1 && item.cat1 !== '未分类(API漏标)') ? item.cat1 : '其他/未分类'
    cat1Map[c1] = (cat1Map[c1] || 0) + 1
  })

  const pieData = Object.keys(cat1Map)
    .map(k => ({ name: k, value: cat1Map[k] }))
    .sort((a, b) => b.value - a.value)

  const option = {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e5e7eb',
      textStyle: { color: '#374151' },
      formatter: '{b}: {c} 题 ({d}%)'
    },
    series: [
      {
        type: 'pie',
        radius: ['35%', '70%'],
        center: ['50%', '55%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          borderColor: '#fff',
          borderWidth: 2
        },
        label: {
          show: true,
          fontSize: 11,
          formatter: '{b}\n{d}%'
        },
        labelLine: {
          show: true,
          length: 8,
          length2: 12
        },
        data: pieData
      }
    ]
  }
  
  myChart.setOption(option, true)
}

/**
 * 图片加载失败兜底：替换为灰色占位
 */
const handleImgError = (e) => {
  e.target.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iOTYiIGhlaWdodD0iOTYiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI2U1ZTdlYiIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0ibWlkZGxlIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjOWNhM2FmIiBmb250LXNpemU9IjE0Ij7lm77niYc8L3RleHQ+PC9zdmc+'
  e.target.alt = '图片加载失败'
}

const addFileToStaging = (file) => {
  if (!file.type.startsWith('image/')) return
  stagedFiles.value.push({
    id: Date.now() + Math.random(),
    file: file,
    preview: URL.createObjectURL(file)
  })
}

const handleDrop = (e) => {
  isDragging.value = false
  const files = Array.from(e.dataTransfer.files)
  files.forEach(addFileToStaging)
}

const handleFileSelect = (e) => {
  const files = Array.from(e.target.files)
  files.forEach(addFileToStaging)
  e.target.value = null
}

const removeFile = (index) => {
  URL.revokeObjectURL(stagedFiles.value[index].preview)
  stagedFiles.value.splice(index, 1)
}

const clearStaging = () => {
  stagedFiles.value.forEach(item => URL.revokeObjectURL(item.preview))
  stagedFiles.value = []
  stagedText.value = ''
  sourceUrl.value = ''
  uploadResult.value = null
  uploadError.value = null
}

const submitAll = async () => {
  if (!stagedText.value.trim() && stagedFiles.value.length === 0) return
  
  isUploading.value = true
  uploadResult.value = null
  uploadError.value = null

  const formData = new FormData()
  formData.append('url', sourceUrl.value)
  formData.append('text', stagedText.value)
  
  stagedFiles.value.forEach(item => {
    formData.append('files', item.file)
  })

  try {
    const data = await upload(`${API_BASE}/submit`, formData)
    
    uploadResult.value = data
    activeTab.value = 'MasterBank'
    
    stagedFiles.value.forEach(item => URL.revokeObjectURL(item.preview))
    stagedFiles.value = []
    stagedText.value = ''
    
    fetchTableData()
    fetchAnalytics()
  } catch (err) {
    uploadError.value = err.message
  } finally {
    isUploading.value = false
  }
}

const deleteDataRow = async (type, recordId) => {
  if (!confirm('⚠️ 警告：确定要彻底删除这一行记录吗？此操作不可恢复！')) return
  
  try {
    await del(`${API_BASE}/data/${type}/${recordId}`)
    
    fetchTableData()
    fetchAnalytics()
  } catch (err) {
    alert(`删除失败: ${err.message}`)
  }
}

const batchDeleteData = async (type) => {
  const dataList = type === 'jd' ? jdData.value : interviewData.value;
  const selectedIds = dataList
    .filter(item => item._selected)
    .map(item => item.id);

  if (selectedIds.length === 0) return;
  if (!confirm(`⚠️ 警告：确定要彻底删除选中的 ${selectedIds.length} 行记录吗？此操作不可恢复！`)) return;

  let successCount = 0;
  for (const id of selectedIds) {
    try {
      await del(`${API_BASE}/data/${type}/${id}`);
      successCount++;
    } catch (e) {
      console.error(`删除 ID:${id} 失败`, e);
    }
  }
  
  alert(`已成功删除 ${successCount} 条记录！`);
  fetchTableData();
  fetchAnalytics();
}

const reprocessInterview = async (id) => {
  if (id === undefined) {
    alert("错误：无法获取面经ID，请确保后端 /api/data 接口已经返回了 id 字段！");
    return;
  }

  if (!confirm("确定要重新调用大模型提取并打标该面经记录吗？\n提取出的题目将会再次被追加进入题库。")) return
  
  reprocessingIds.value[id] = true
  try {
    const data = await post(`${API_BASE}/interview/${id}/re-process`)
    alert(`✅ ${data.message}`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) {
    alert(`错误: ${e.message}`)
  } finally {
    reprocessingIds.value[id] = false
  }
}

const batchReprocessInterview = async () => {
  const targets = interviewData.value.filter(item => item._selected && !reprocessingIds.value[item.id]);
  if (targets.length === 0) return;
  
  if (!confirm(`确定要为选中的 ${targets.length} 条面经记录排队重新调用大模型提取打标吗？`)) return;

  let successCount = 0;
  for (const item of targets) {
    const id = item.id;
    if (id === undefined) continue;
    
    reprocessingIds.value[id] = true;
    try {
      await post(`${API_BASE}/interview/${id}/re-process`);
      successCount++;
    } catch (e) {
      console.error(`重新解析面经ID ${id} 失败`, e);
    } finally {
      reprocessingIds.value[id] = false;
    }
  }
  
  alert(`✅ 批量重新分析完成，成功解析 ${successCount} 条记录！`);
  fetchTableData();
  fetchAnalytics();
}

const retagQuestion = async (question) => {
  if (!confirm("确定要重新调用大模型对该题目进行结构化打标吗？")) return
  
  question._isRetagging = true
  try {
    const data = await post(`${API_BASE}/master-bank/re-tag/${question.id}`)
    question.cat1 = data.data.cat1
    question.cat2 = data.data.cat2
    question.tags = data.data.tags
    question.difficulty = data.data.difficulty
    fetchAnalytics()
  } catch (e) {
    alert(`错误: ${e.message}`)
  } finally {
    question._isRetagging = false
  }
}

const saveField = async (tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey) => {
  try {
    const updateData = {};
    updateData[dbColumn] = newValue;

    await put(`${API_BASE}/data/update`, {
      table_name: tableName,
      record_id: recordId,
      update_data: updateData
    });

    if (frontendKey === 'ai_answer') {
      rowObj.ai_answer = newValue;
    } else {
      rowObj[frontendKey] = newValue;
    }
    rowObj[editStateKey] = false; 
  } catch (err) {
    alert(`系统错误: ${err.message}`);
  }
};

const fetchTableData = async () => {
  isDataLoading.value = true
  dataLoadError.value = null
  try {
    const [jdResp, intResp, masterResp] = await Promise.all([
      get(`${API_BASE}/data/jd?page_size=500`),
      get(`${API_BASE}/data/interview?page_size=500`),
      get(`${API_BASE}/master-bank?page_size=500`),
    ])

    const rawJd = jdResp.items || jdResp
    jdData.value = rawJd.map(item => ({ 
      ...item, 
      _selected: false, 
      _isEditingCompany: false, 
      _editCompany: '',
      _isEditingTitle: false,
      _editTitle: ''
    }))
    
    const rawInt = intResp.items || intResp
    interviewData.value = rawInt.map(item => ({ 
      ...item, 
      _selected: false, 
      _isEditingCompany: false, 
      _editCompany: '',
      _isEditingRound: false,
      _editRound: '',
      _isEditingFocus: false,
      _editFocus: '',
      _isEditingQuestions: false,
      _editQuestions: '',
      _isEditingDifficulty: false,
      _editDifficulty: ''
    }))

    const bankData = masterResp.items || masterResp
    masterBank.value = bankData.map(q => ({ 
      ...q, 
      _showAnswer: false, 
      _isLoadingAnswer: false,
      _isRetagging: false,
      _selected: false,
      _isEditingAnswer: false,
      _editAnswer: ''
    }))
    nextTick(() => { updateDistributionChart() })
  } catch (e) {
    console.error('获取表格数据失败', e)
    dataLoadError.value = e.message || '数据加载失败，请刷新重试'
  } finally {
    isDataLoading.value = false
  }
}

const fetchAnalytics = async () => {
  try {
    analytics.value = await get(`${API_BASE}/analytics`)
  } catch (e) {
    console.error('获取分析数据失败', e)
  }
}

const downloadCSV = () => {
  const url = `${API_BASE}/download/${activeTab.value.toLowerCase()}`
  window.open(url, '_blank')
}

const filteredMasterBank = computed(() => {
  let result = masterBank.value
  
  if (selectedTag.value !== '全部') {
    result = result.filter(q => {
      const rawCat = q.cat1 || '未分类'
      const cats = rawCat.split(',').map(c => c.trim()).filter(c => c)
      return cats.includes(selectedTag.value)
    })
  }

  if (searchQuery.value.trim()) {
    const query = searchQuery.value.trim().toLowerCase()
    result = result.filter(q => 
      (q.question || '').toLowerCase().includes(query) ||
      (q.cat1 || '').toLowerCase().includes(query) ||
      (q.tags || '').toLowerCase().includes(query)
    )
  }

  if (filterDifficulty.value) {
    result = result.filter(q => 
      (q.difficulty || '').includes(filterDifficulty.value)
    )
  }

  if (showStarredOnly.value) {
    result = result.filter(q => q.is_starred)
  }

  return result
})

const selectedCount = computed(() => filteredMasterBank.value.filter(q => q._selected).length)

const toggleSelectAll = () => {
  const currentList = filteredMasterBank.value
  const allSelected = currentList.length > 0 && currentList.every(q => q._selected)
  currentList.forEach(q => q._selected = !allSelected)
}

const invertSelection = () => {
  filteredMasterBank.value.forEach(q => q._selected = !q._selected)
}

const batchGenerateAnswers = async () => {
  const targets = filteredMasterBank.value.filter(q => q._selected && !q.ai_answer && !q._isLoadingAnswer)
  if (targets.length === 0) {
    alert('提示：选中的题目都已经生成过答案，或者当前没有选中任何题目！')
    return
  }
  if (!confirm(`确定要为 ${targets.length} 道新考点排队生成答案吗？\n（为了避免触发大模型速率限制，系统将依次为您生成）`)) return

  for (const q of targets) {
    await generateAnswer(q)
  }
  alert('✅ 批量生成解答完成！')
}

const batchDeleteMasterBank = async () => {
  const targets = filteredMasterBank.value.filter(q => q._selected)
  if (targets.length === 0) return
  if (!confirm(`⚠️ 警告：确定要彻底删除这 ${targets.length} 道高频真题吗？此操作不可恢复！`)) return

  let successCount = 0
  for (const q of targets) {
    try {
      await del(`${API_BASE}/master-bank/${q.id}`)
      successCount++
    } catch (e) {
      console.error(`删除 ID:${q.id} 失败`, e)
    }
  }
  
  alert(`已成功删除 ${successCount} 道题目！`)
  fetchTableData()
}

const selectTag = (tag) => {
  selectedTag.value = tag
}

const triggerBuildMasterBank = async () => {
  if(!confirm("⚠️ 警告：这将调用 OpenAI Embeddings API 对历史面经的所有题目进行重新提取、算力和聚类。\n\n一般只需在初次迁移时执行一次，后续提交面经会自动增量更新。确定继续吗？")) return
  
  isBuilding.value = true
  try {
    const data = await post(`${API_BASE}/master-bank/build`)
    alert(`⚡ 全量聚类计算完毕！从所有杂乱面经中共归纳出 ${data.total_unique} 道核心真题。`)
    fetchTableData()
    fetchAnalytics()
  } catch(e) {
    alert("计算失败：" + e.message)
  } finally {
    isBuilding.value = false
  }
}

const toggleAnswer = (question) => {
  question._showAnswer = !question._showAnswer
}

const isFailedAnswer = (answer) => {
  return answer && answer.includes('生成失败')
}

const generateAnswer = async (question) => {
  question._isLoadingAnswer = true
  // 如果是失败状态，先清空以便后端重新生成
  if (isFailedAnswer(question.ai_answer)) {
    question.ai_answer = null
  }
  try {
    const data = await post(`${API_BASE}/master-bank/generate-answer/${question.id}`)
    question.ai_answer = data.answer
  } catch(e) {
    console.error("网络或接口错误", e)
    alert(`生成解答失败: ${e.message}`)
  } finally {
    question._isLoadingAnswer = false
  }
}

const toggleStar = async (question) => {
  try {
    const data = await post(`${API_BASE}/master-bank/toggle-star/${question.id}`)
    question.is_starred = data.is_starred
  } catch (e) {
    console.error('收藏操作失败', e)
    alert(`收藏操作失败: ${e.message}`)
  }
}

const renderMarkdown = (text) => {
  if (!text) return ''
  return marked.parse(text)
}

let searchDebounceTimer = null
const onSearchInput = () => {
  clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    // 搜索是纯前端过滤，computed 自动响应
  }, 200)
}

const startMockInterview = async () => {
  try {
    const params = new URLSearchParams({ count: '5' })
    if (filterDifficulty.value) params.append('difficulty', filterDifficulty.value)
    const data = await get(`${API_BASE}/master-bank/random?${params}`)
    mockQuestions.value = data.map(q => ({ ...q, _showAnswer: false }))
  } catch (e) {
    console.error('获取模拟面试题目失败', e)
    mockQuestions.value = []
  }
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent; 
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: #cbd5e1; 
  border-radius: 20px; 
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: #94a3b8; 
}

:deep(pre) {
  background-color: #1e293b;
  color: #f8fafc;
  padding: 1rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin-top: 0.5rem;
  margin-bottom: 1rem;
}
:deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.875em;
}
:deep(p code) {
  background-color: #e2e8f0;
  color: #c53030;
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
}
:deep(ul) {
  list-style-type: disc;
  padding-left: 1.5rem;
  margin-bottom: 1rem;
}
:deep(ol) {
  list-style-type: decimal;
  padding-left: 1.5rem;
  margin-bottom: 1rem;
}
:deep(strong) {
  font-weight: 700;
  color: #111827;
}
:deep(h1), :deep(h2), :deep(h3) {
  font-weight: 700;
  color: #111827;
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
}
:deep(h3) {
  font-size: 1.125rem;
}
</style>