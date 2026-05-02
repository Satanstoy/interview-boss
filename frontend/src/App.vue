<template>
  <div class="min-h-screen p-8 max-w-[98%] mx-auto bg-slate-50">
    <header class="mb-10 text-center">
      <h1 class="text-4xl font-bold text-gray-900 mb-2">多模态 JD 与面经智能解析系统</h1>
      <p class="text-gray-500">将零散的内容放至暂存区，确认无误后一键提交解析与增量聚类</p>
    </header>

    <div class="bg-white rounded-xl shadow-md border border-gray-200 mb-10 overflow-hidden">
      <div class="bg-gray-50 p-4 border-b border-gray-200 flex items-center gap-4">
        <label class="font-semibold text-gray-700 whitespace-nowrap">来源链接 (URL):</label>
        <input 
          v-model="sourceUrl"
          type="text" 
          class="flex-1 border border-gray-300 rounded-lg p-2 focus:ring-blue-500 focus:border-blue-500"
          placeholder="粘贴小红书/牛客网帖子链接 (用于去重，避免重复录入)"
        />
      </div>

      <div class="grid grid-cols-2 divide-x divide-gray-100">
        <div class="p-6 flex flex-col">
          <label class="block text-sm font-semibold text-gray-700 mb-2">补充纯文本内容</label>
          <textarea 
            v-model="stagedText"
            class="flex-1 w-full border border-gray-300 rounded-lg p-3 focus:ring-blue-500 focus:border-blue-500 resize-none"
            placeholder="在此处粘贴面经或 JD 的纯文本内容（可与右侧图片组合提交）..."
          ></textarea>
        </div>

        <div 
          class="p-6 flex flex-col transition-colors relative"
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
                <img :src="item.preview" class="h-24 w-24 object-cover rounded-md border border-gray-300 shadow-sm" />
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

    <div class="grid grid-cols-4 gap-8">
      
      <div class="col-span-1 bg-white p-6 rounded-xl shadow-sm border border-gray-100 h-fit sticky top-8 max-h-[calc(100vh-4rem)] overflow-y-auto custom-scrollbar">
        <h2 class="text-2xl font-bold mb-6">📊 全局分析</h2>
        <button @click="fetchAnalytics" class="w-full bg-indigo-50 text-indigo-700 px-4 py-2 rounded mb-6 hover:bg-indigo-100 transition">
          刷新分析数据
        </button>

        <div class="mb-8">
          <h3 class="text-lg font-semibold text-gray-700 mb-3 border-l-4 border-purple-500 pl-2">考点分布 (原始明细)</h3>
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

      <div class="col-span-3 bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        
        <div class="flex border-b bg-gray-50">
          <button 
            @click="activeTab = 'JD'"
            class="flex-1 py-4 text-lg font-medium transition-colors"
            :class="activeTab === 'JD' ? 'text-blue-600 bg-white border-b-2 border-blue-600' : 'text-gray-500 hover:text-gray-700'"
          >
            Job Descriptions (JD)
          </button>
          <button 
            @click="activeTab = 'Interview'"
            class="flex-1 py-4 text-lg font-medium transition-colors"
            :class="activeTab === 'Interview' ? 'text-gray-600 bg-white border-b-2 border-gray-600' : 'text-gray-500 hover:text-gray-700'"
          >
            面经流水记录
          </button>
          <button 
            @click="activeTab = 'MasterBank'"
            class="flex-1 py-4 text-lg font-bold transition-colors"
            :class="activeTab === 'MasterBank' ? 'text-red-600 bg-white border-b-2 border-red-600' : 'text-gray-500 hover:text-gray-700'"
          >
            🔥 核心精炼题库
          </button>
        </div>

        <div class="p-6">
          <div class="flex justify-between items-center mb-6">
            <h2 class="text-xl font-bold flex items-center gap-2">
              {{ activeTab === 'JD' ? '职位描述库' : activeTab === 'Interview' ? '原始面经流水' : '必考真题库' }}
              <span v-if="activeTab === 'MasterBank' && selectedTag !== '全部'" class="text-sm font-normal bg-green-100 text-green-700 px-3 py-1 rounded-full border border-green-200">
                分类筛选: {{ selectedTag }}
              </span>
            </h2>
            <div class="space-x-3">
              <button v-if="activeTab === 'MasterBank'" @click="triggerBuildMasterBank" class="text-sm bg-purple-600 text-white font-bold px-4 py-2 rounded hover:bg-purple-700 transition">
                {{ isBuilding ? '正在提取全量特征并聚类去重...' : '⚡ 全量重新计算题库排序' }}
              </button>
              
              <button @click="fetchTableData" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200">刷新数据</button>
              <button v-if="activeTab !== 'MasterBank'" @click="downloadCSV" class="text-sm bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700">一键导出 CSV</button>
            </div>
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
                    <button @click="deleteDataRow('jd', idx)" class="text-red-500 hover:text-red-700 font-bold" title="删除该行">🗑️</button>
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
                    <button @click="deleteDataRow('interview', idx)" class="text-red-500 hover:text-red-700 font-bold" title="删除该行">🗑️</button>
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

                  <td class="p-3 whitespace-nowrap">{{ row['面试轮次'] }}</td>
                  <td class="p-3 whitespace-pre-wrap break-words">{{ row['考察重点'] }}</td>
                  <td class="p-3 whitespace-pre-wrap break-words leading-relaxed">{{ row['具体题目清单'] }}</td>
                  <td class="p-3 whitespace-nowrap">
                    <span class="px-2 py-1 rounded text-xs" :class="(row['难易程度'] || '').includes('难') ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'">
                      {{ row['难易程度'] || row['难度'] || '-' }}
                    </span>
                  </td>
                </tr>
                <tr v-if="interviewData.length === 0">
                  <td colspan="7" class="p-6 text-center text-gray-400">暂无数据</td>
                </tr>
              </tbody>
            </table>
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
                  
                  <div v-if="q.ai_answer" class="text-gray-700 text-sm leading-relaxed max-w-none" v-html="renderMarkdown(q.ai_answer)"></div>
                  
                  <div v-else-if="q._isLoadingAnswer" class="flex flex-col items-center justify-center py-6 text-blue-600 gap-3">
                    <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    <span class="font-medium">大模型正在为您生成高质量解答，请稍候...</span>
                  </div>

                  <div v-else class="text-center py-4">
                    <p class="text-gray-500 mb-3 text-sm">该题目是由系统后台刚刚抽取出的新考点，尚未生成解答。</p>
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

const API_BASE = '/api'

const sourceUrl = ref('')
const stagedText = ref('')
const stagedFiles = ref([])
const isDragging = ref(false)

const isUploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref(null)

const activeTab = ref('MasterBank')
const jdData = ref([])
const interviewData = ref([])
const masterBank = ref([])
const rawTaggedData = ref([]) 
const isBuilding = ref(false)
const analytics = ref({ tech_trends: {} })

const selectedTag = ref('全部')

const reprocessingIds = ref({})

const chartRef = ref(null)
let myChart = null

const popularTags = computed(() => {
  const counts = {}
  masterBank.value.forEach(q => {
    const cat = q.cat1 || '未分类'
    counts[cat] = (counts[cat] || 0) + 1
  })
  return counts
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
    window.addEventListener('resize', () => myChart && myChart.resize())
  }
  
  fetchTableData()
  fetchAnalytics()
})

onUnmounted(() => {
  window.removeEventListener('paste', handleGlobalPaste)
  if (myChart) {
    window.removeEventListener('resize', myChart.resize)
    myChart.dispose()
  }
})

const updateDistributionChart = () => {
  if (!myChart || !rawTaggedData.value.length) return

  const cat1Map = {}
  const cat2Map = {}

  rawTaggedData.value.forEach(item => {
    const c1 = (item['一级大类'] && item['一级大类'] !== '未分类(API漏标)') ? item['一级大类'] : '其他/未分类'
    const c2 = (item['二级子类'] && item['二级子类'] !== '未分类') ? item['二级子类'] : '未知'
    
    cat1Map[c1] = (cat1Map[c1] || 0) + 1
    
    const c2Key = `${c1}|${c2}`
    cat2Map[c2Key] = (cat2Map[c2Key] || 0) + 1
  })

  const innerData = Object.keys(cat1Map).map(k => ({ name: k, value: cat1Map[k] }))
  const outerData = Object.keys(cat2Map).map(k => {
    const [c1, c2] = k.split('|')
    return { name: c2, value: cat2Map[k], cat1: c1 }
  })

  const option = {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e5e7eb',
      textStyle: { color: '#374151' },
      formatter: (params) => {
        if (params.seriesName === '一级大类') {
          const c1 = params.name
          const subItems = outerData.filter(d => d.cat1 === c1).sort((a,b) => b.value - a.value)
          let html = `<div style="font-weight:bold;margin-bottom:6px;border-bottom:1px solid #eee;padding-bottom:4px;">${c1} (共 ${params.value} 题)</div>`
          subItems.forEach(item => {
            html += `<div style="font-size:12px;color:#6b7280;margin:2px 0;">• ${item.name}: ${item.value} 题</div>`
          })
          return html
        }
        return `<div style="font-size:12px;color:#9ca3af;margin-bottom:2px;">${params.data.cat1}</div>
                <div style="font-weight:bold;">${params.name}: ${params.value} 题 (${params.percent}%)</div>`
      }
    },
    series: [
      {
        name: '一级大类',
        type: 'pie',
        selectedMode: 'single',
        radius: [0, '40%'],
        label: { 
          position: 'inner', 
          fontSize: 10,
          color: '#fff',
          formatter: '{b}' 
        },
        labelLine: { show: false },
        data: innerData,
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 1
        }
      },
      {
        name: '二级子类',
        type: 'pie',
        radius: ['50%', '75%'],
        label: {
          show: false 
        },
        data: outerData,
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 1
        }
      }
    ]
  }
  
  myChart.setOption(option)
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
    const res = await fetch(`${API_BASE}/submit`, {
      method: 'POST',
      body: formData
    })
    
    let data
    try {
      data = await res.json()
    } catch (e) {
      const errorText = await res.text()
      throw new Error(`服务器响应异常: ${errorText.substring(0, 100)}...`)
    }

    if (!res.ok) {
      if (res.status === 409) {
        throw new Error(data.detail)
      }
      throw new Error(data.detail || '提交解析失败')
    }
    
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

const deleteDataRow = async (type, index) => {
  if (!confirm('⚠️ 警告：确定要彻底删除这一行记录吗？此操作不可恢复！')) return
  
  try {
    const res = await fetch(`${API_BASE}/data/${type}/${index}`, {
      method: 'DELETE'
    })
    
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || '删除失败')
    }
    
    fetchTableData()
    fetchAnalytics()
  } catch (err) {
    alert(`删除失败: ${err.message}`)
  }
}

const batchDeleteData = async (type) => {
  const dataList = type === 'jd' ? jdData.value : interviewData.value;
  const selectedIndices = dataList
    .map((item, index) => item._selected ? index : -1)
    .filter(index => index !== -1)
    .sort((a, b) => b - a);

  if (selectedIndices.length === 0) return;
  if (!confirm(`⚠️ 警告：确定要彻底删除选中的 ${selectedIndices.length} 行记录吗？此操作不可恢复！`)) return;

  let successCount = 0;
  for (const idx of selectedIndices) {
    try {
      const res = await fetch(`${API_BASE}/data/${type}/${idx}`, { method: 'DELETE' });
      if (res.ok) successCount++;
    } catch (e) {
      console.error(`删除索引 ${idx} 失败`, e);
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
    const res = await fetch(`${API_BASE}/interview/${id}/re-process`, { method: 'POST' })
    const data = await res.json()
    
    if (res.ok) {
      alert(`✅ ${data.message}`)
      fetchTableData()
      fetchAnalytics()
    } else {
      const errorMsg = typeof data.detail === 'object' ? JSON.stringify(data.detail) : data.detail;
      throw new Error(errorMsg || '重新解析失败')
    }
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
      const res = await fetch(`${API_BASE}/interview/${id}/re-process`, { method: 'POST' });
      if (res.ok) successCount++;
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
    const res = await fetch(`${API_BASE}/master-bank/re-tag/${question.id}`, { method: 'POST' })
    const data = await res.json()
    
    if (res.ok) {
      question.cat1 = data.data.cat1
      question.cat2 = data.data.cat2
      question.tags = data.data.tags
      question.difficulty = data.data.difficulty
      fetchAnalytics()
    } else {
      throw new Error(data.detail || '重新打标失败')
    }
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

    const res = await fetch(`${API_BASE}/data/update`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        table_name: tableName,
        record_id: recordId,
        update_data: updateData
      })
    });

    const data = await res.json();
    if (res.ok) {
      if (frontendKey === 'ai_answer') {
        rowObj.ai_answer = newValue;
      } else {
        rowObj[frontendKey] = newValue;
      }
      rowObj[editStateKey] = false; 
    } else {
      throw new Error(data.detail || '保存失败');
    }
  } catch (err) {
    alert(`系统错误: ${err.message}`);
  }
};

const fetchTableData = async () => {
  try {
    const resJd = await fetch(`${API_BASE}/data/jd`)
    const rawJd = await resJd.json()
    jdData.value = rawJd.map(item => ({ 
      ...item, 
      _selected: false, 
      _isEditingCompany: false, 
      _editCompany: '',
      _isEditingTitle: false,
      _editTitle: ''
    }))
    
    const resInt = await fetch(`${API_BASE}/data/interview`)
    const rawInt = await resInt.json()
    interviewData.value = rawInt.map(item => ({ 
      ...item, 
      _selected: false, 
      _isEditingCompany: false, 
      _editCompany: ''
    }))

    const resTagged = await fetch(`${API_BASE}/data/tagged`)
    rawTaggedData.value = await resTagged.json()
    nextTick(() => { updateDistributionChart() })

    const resMaster = await fetch(`${API_BASE}/master-bank`)
    const bankData = await resMaster.json()
    masterBank.value = bankData.map(q => ({ 
      ...q, 
      _showAnswer: false, 
      _isLoadingAnswer: false,
      _isRetagging: false,
      _selected: false,
      _isEditingAnswer: false,
      _editAnswer: ''
    }))
  } catch (e) {
    console.error('获取表格数据失败', e)
  }
}

const fetchAnalytics = async () => {
  try {
    const res = await fetch(`${API_BASE}/analytics`)
    analytics.value = await res.json()
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
    result = result.filter(q => (q.cat1 || '未分类') === selectedTag.value)
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
      const res = await fetch(`${API_BASE}/master-bank/${q.id}`, { method: 'DELETE' })
      if (res.ok) successCount++
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
    const res = await fetch(`${API_BASE}/master-bank/build`, { method: 'POST' })
    const data = await res.json()
    if(res.ok) {
      alert(`⚡ 全量聚类计算完毕！从所有杂乱面经中共归纳出 ${data.total_unique} 道核心真题。`)
      fetchTableData()
      fetchAnalytics()
    } else {
      throw new Error(data.detail || '未知错误')
    }
  } catch(e) {
    alert("计算失败：" + e.message)
  } finally {
    isBuilding.value = false
  }
}

const toggleAnswer = (question) => {
  question._showAnswer = !question._showAnswer
}

const generateAnswer = async (question) => {
  question._isLoadingAnswer = true
  try {
    const res = await fetch(`${API_BASE}/master-bank/generate-answer/${question.id}`, { method: 'POST' })
    const data = await res.json()
    if(res.ok) {
      question.ai_answer = data.answer
    } else {
      alert("生成解答失败，请查看后端日志")
    }
  } catch(e) {
    console.error("网络或接口错误", e)
  } finally {
    question._isLoadingAnswer = false
  }
}

const renderMarkdown = (text) => {
  if (!text) return ''
  return marked.parse(text)
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