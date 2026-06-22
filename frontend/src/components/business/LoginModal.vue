<template>
  <!-- Embedded mode: inline form without overlay -->
  <div v-if="embedded">
    <div v-if="!hideHeader" class="mb-6">
      <h3 class="text-xl font-semibold text-foreground">{{ authTitle }}</h3>
      <p class="text-sm text-muted-foreground mt-1">{{ authSubtitle }}</p>
    </div>

    <!-- Login mode toggle (hidden when binding email) -->
    <div v-if="!needEmailBind && !resetMode" class="flex gap-1 mb-5 p-1 bg-muted rounded-lg">
      <button
        @click="loginMode = 'password'; error = ''"
        :class="loginMode === 'password'
          ? 'bg-background text-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground'"
        class="flex-1 py-1.5 text-xs font-medium rounded-md transition-all"
      >
        密码登录
      </button>
      <button
        @click="loginMode = 'email'; error = ''"
        :class="loginMode === 'email'
          ? 'bg-background text-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground'"
        class="flex-1 py-1.5 text-xs font-medium rounded-md transition-all"
      >
        验证码登录
      </button>
    </div>

    <!-- Bind email form (old users without email) -->
    <form v-if="needEmailBind" @submit.prevent="handleBindEmailSubmit">
      <div class="mb-4 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
        <p class="text-sm text-amber-700 dark:text-amber-300">你的账号尚未绑定邮箱，请绑定邮箱后继续使用。</p>
      </div>

      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">邮箱</label>
          <input
            v-model="bindEmail"
            type="email"
            placeholder="your@email.com"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="email"
          />
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">验证码</label>
          <div class="flex gap-2">
            <input
              v-model="bindCode"
              type="text"
              placeholder="6位数字"
              maxlength="6"
              class="flex-1 h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="loading"
            />
            <button
              type="button"
              @click="handleSendBindCode"
              :disabled="codeCooldown > 0 || !bindEmail.trim() || !isEmailValid(bindEmail)"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-input bg-transparent text-foreground hover:bg-muted transition disabled:opacity-50 whitespace-nowrap"
            >
              {{ codeCooldown > 0 ? `${codeCooldown}s` : '发送验证码' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
        <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {{ error }}
      </div>

      <button
        type="submit"
        :disabled="loading || !bindEmail.trim() || bindCode.length < 6"
        class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span :class="{ 'opacity-0': loading }">{{ loading ? '绑定中...' : '绑定邮箱并登录' }}</span>
        <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </button>

      <div class="mt-3 text-center">
        <button
          @click="needEmailBind = false; error = ''"
          type="button"
          class="text-sm text-muted-foreground hover:text-foreground transition"
        >
          返回登录
        </button>
      </div>
    </form>

    <!-- Password mode -->
    <form
      v-if="loginMode === 'password' && !needEmailBind && !resetMode"
      ref="formEl"
      @submit.prevent="handlePasswordSubmit"
      action="/api/auth/login-form"
      method="post"
    >
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">用户名</label>
          <input
            ref="usernameInput"
            v-model="username"
            type="text"
            name="username"
            placeholder="2-32 个字符"
            maxlength="32"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="username"
          />
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">密码</label>
          <input
            v-model="password"
            type="password"
            name="password"
            placeholder="至少 8 位"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="current-password"
          />
        </div>
        <div v-if="isRegister" class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">
            邮箱 <span class="text-destructive">*</span>
          </label>
          <input
            v-model="email"
            type="email"
            placeholder="your@email.com"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="email"
          />
        </div>
      </div>

      <div v-if="!isRegister" class="flex items-center justify-between gap-3 mt-3">
        <label class="flex items-center gap-2 cursor-pointer group min-w-0">
          <input
            v-model="rememberMe"
            type="checkbox"
            class="h-4 w-4 rounded-sm border border-input bg-transparent checked:bg-primary checked:text-primary-foreground focus-visible:ring-ring/50 focus-visible:ring-3 transition"
          />
          <span class="text-sm text-muted-foreground group-hover:text-foreground transition truncate">记住我（30 天免登录）</span>
        </label>
        <button type="button" class="text-sm text-primary hover:text-primary/80 font-medium whitespace-nowrap transition" @click="showResetPassword">
          忘记密码？
        </button>
      </div>

      <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
        <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {{ error }}
      </div>

      <button
        type="submit"
        :disabled="loading || !username.trim() || password.length < 8"
        class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
      >
        <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}</span>
        <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </button>
    </form>

    <!-- Email mode -->
    <form v-else-if="!needEmailBind && !resetMode" @submit.prevent="handleEmailSubmit">
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">邮箱</label>
          <input
            v-model="email"
            type="email"
            placeholder="your@email.com"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="email"
          />
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">验证码</label>
          <div class="flex gap-2">
            <input
              v-model="verifyCode"
              type="text"
              placeholder="6位数字"
              maxlength="6"
              class="flex-1 h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="loading"
            />
            <button
              type="button"
              @click="handleSendCode"
              :disabled="codeCooldown > 0 || !email.trim() || !isEmailValid(email)"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-input bg-transparent text-foreground hover:bg-muted transition disabled:opacity-50 whitespace-nowrap"
            >
              {{ codeCooldown > 0 ? `${codeCooldown}s` : '发送验证码' }}
            </button>
          </div>
        </div>
        <template v-if="isRegister">
          <div class="flex flex-col gap-2">
            <label class="text-sm font-medium text-foreground">用户名</label>
            <input
              ref="usernameInput"
              v-model="username"
              type="text"
              placeholder="2-32 个字符"
              maxlength="32"
              class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="loading"
              autocomplete="username"
            />
          </div>
          <div class="flex flex-col gap-2">
            <label class="text-sm font-medium text-foreground">密码</label>
            <input
              v-model="password"
              type="password"
              placeholder="至少 8 位"
              class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="loading"
              autocomplete="new-password"
            />
          </div>
        </template>
      </div>

      <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
        <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {{ error }}
      </div>

      <button
        type="submit"
        :disabled="loading || !email.trim() || verifyCode.length < 6"
        class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
      >
        <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}</span>
        <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </button>
    </form>

    <!-- Reset password mode -->
    <form v-if="resetMode && !needEmailBind" @submit.prevent="handleResetPasswordSubmit">
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">邮箱</label>
          <input
            v-model="resetEmail"
            type="email"
            placeholder="your@email.com"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="email"
          />
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">验证码</label>
          <div class="flex gap-2">
            <input
              v-model="resetCode"
              type="text"
              placeholder="6位数字"
              maxlength="6"
              class="flex-1 h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="loading"
            />
            <button
              type="button"
              @click="handleSendResetCode"
              :disabled="codeCooldown > 0 || !resetEmail.trim() || !isEmailValid(resetEmail)"
              class="px-3 py-1.5 text-xs font-medium rounded-md border border-input bg-transparent text-foreground hover:bg-muted transition disabled:opacity-50 whitespace-nowrap"
            >
              {{ codeCooldown > 0 ? `${codeCooldown}s` : '发送验证码' }}
            </button>
          </div>
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">新密码</label>
          <input
            v-model="resetNewPassword"
            type="password"
            placeholder="至少 8 位"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="new-password"
          />
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-sm font-medium text-foreground">确认新密码</label>
          <input
            v-model="resetConfirmPassword"
            type="password"
            placeholder="再次输入新密码"
            class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loading"
            autocomplete="new-password"
          />
        </div>
      </div>

      <p v-if="resetSuccess" class="mt-3 text-sm text-emerald-600 dark:text-emerald-400">{{ resetSuccess }}</p>
      <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
        <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {{ error }}
      </div>

      <button
        type="submit"
        :disabled="loading || !resetEmail.trim() || resetCode.length < 6 || resetNewPassword.length < 8 || resetConfirmPassword.length < 8"
        class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
      >
        <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : '重置密码' }}</span>
        <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </button>

      <div class="mt-3 text-center">
        <button type="button" class="text-sm text-muted-foreground hover:text-foreground transition" @click="backToLogin">
          返回登录
        </button>
      </div>
    </form>

    <div v-if="!needEmailBind && !resetMode" class="mt-4 text-center">
      <span class="text-sm text-muted-foreground">{{ isRegister ? '已有账号？' : '还没有账号？' }}</span>
      <button
        @click="toggleRegister"
        class="text-sm text-primary hover:text-primary/80 font-medium ml-1 transition"
      >
        {{ isRegister ? '去登录' : '立即注册' }}
      </button>
    </div>
  </div>

  <!-- Modal mode: overlay dialog (for 401 re-login etc.) -->
  <Teleport v-else to="body">
    <Transition name="dialog-fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-[9999] flex items-center justify-center p-4"
        @click.self="$emit('close')"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity" />

        <!-- Panel -->
        <div class="relative w-full max-w-sm bg-card text-card-foreground rounded-xl border shadow-xl overflow-hidden animate-slide-up">
          <!-- Header -->
          <div class="px-6 pt-6 pb-4 text-center">
            <div class="size-10 mx-auto mb-3 rounded-lg bg-primary flex items-center justify-center">
              <svg class="size-5 text-primary-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </div>
            <h2 class="text-lg font-semibold text-foreground">{{ authTitle }}</h2>
            <p class="text-sm text-muted-foreground mt-1">{{ authSubtitle }}</p>
          </div>

          <!-- Login mode toggle (hidden when binding email) -->
          <div v-if="!needEmailBind && !resetMode" class="mx-6 mb-4 flex gap-1 p-1 bg-muted rounded-lg">
            <button
              @click="loginMode = 'password'; error = ''"
              :class="loginMode === 'password'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'"
              class="flex-1 py-1.5 text-xs font-medium rounded-md transition-all"
            >
              密码登录
            </button>
            <button
              @click="loginMode = 'email'; error = ''"
              :class="loginMode === 'email'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'"
              class="flex-1 py-1.5 text-xs font-medium rounded-md transition-all"
            >
              验证码登录
            </button>
          </div>

          <!-- Bind email form (modal mode) -->
          <form v-if="needEmailBind" @submit.prevent="handleBindEmailSubmit" class="px-6 pb-6">
            <div class="mb-4 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
              <p class="text-sm text-amber-700 dark:text-amber-300">你的账号尚未绑定邮箱，请绑定邮箱后继续使用。</p>
            </div>

            <div class="flex flex-col gap-4">
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">邮箱</label>
                <input
                  v-model="bindEmail"
                  type="email"
                  placeholder="your@email.com"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="email"
                />
              </div>
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">验证码</label>
                <div class="flex gap-2">
                  <input
                    v-model="bindCode"
                    type="text"
                    placeholder="6位数字"
                    maxlength="6"
                    class="flex-1 h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="loading"
                  />
                  <button
                    type="button"
                    @click="handleSendBindCode"
                    :disabled="codeCooldown > 0 || !bindEmail.trim() || !isEmailValid(bindEmail)"
                    class="px-3 py-1.5 text-xs font-medium rounded-md border border-input bg-transparent text-foreground hover:bg-muted transition disabled:opacity-50 whitespace-nowrap"
                  >
                    {{ codeCooldown > 0 ? `${codeCooldown}s` : '发送验证码' }}
                  </button>
                </div>
              </div>
            </div>

            <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
              <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {{ error }}
            </div>

            <button
              type="submit"
              :disabled="loading || !bindEmail.trim() || bindCode.length < 6"
              class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
            >
              <span :class="{ 'opacity-0': loading }">{{ loading ? '绑定中...' : '绑定邮箱并登录' }}</span>
              <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </button>

            <div class="mt-3 text-center">
              <button
                @click="needEmailBind = false; error = ''"
                type="button"
                class="text-sm text-muted-foreground hover:text-foreground transition"
              >
                返回登录
              </button>
            </div>
          </form>

          <!-- Password mode Form -->
          <form
            v-if="loginMode === 'password' && !needEmailBind && !resetMode"
            ref="formEl"
            @submit.prevent="handlePasswordSubmit"
            action="/api/auth/login-form"
            method="post"
            class="px-6 pb-6"
          >
            <div class="flex flex-col gap-4">
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">用户名</label>
                <input
                  ref="usernameInput"
                  v-model="username"
                  type="text"
                  name="username"
                  placeholder="2-32 个字符"
                  maxlength="32"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="username"
                />
              </div>
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">密码</label>
                <input
                  v-model="password"
                  type="password"
                  name="password"
                  placeholder="至少 8 位"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="current-password"
                />
              </div>
              <div v-if="isRegister" class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">
                  邮箱 <span class="text-destructive">*</span>
                </label>
                <input
                  v-model="email"
                  type="email"
                  placeholder="your@email.com"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="email"
                />
              </div>
            </div>

            <div v-if="!isRegister" class="flex items-center justify-between gap-3 mt-3">
              <label class="flex items-center gap-2 cursor-pointer group min-w-0">
                <input
                  v-model="rememberMe"
                  type="checkbox"
                  class="h-4 w-4 rounded-sm border border-input bg-transparent checked:bg-primary checked:text-primary-foreground focus-visible:ring-ring/50 focus-visible:ring-3 transition"
                />
                <span class="text-sm text-muted-foreground group-hover:text-foreground transition truncate">记住我（30 天免登录）</span>
              </label>
              <button type="button" class="text-sm text-primary hover:text-primary/80 font-medium whitespace-nowrap transition" @click="showResetPassword">
                忘记密码？
              </button>
            </div>

            <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
              <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {{ error }}
            </div>

            <button
              type="submit"
              :disabled="loading || !username.trim() || password.length < 8"
              class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
            >
              <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}</span>
              <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </button>
          </form>

          <!-- Email mode Form -->
          <form v-else-if="!needEmailBind && !resetMode" @submit.prevent="handleEmailSubmit" class="px-6 pb-6">
            <div class="flex flex-col gap-4">
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">邮箱</label>
                <input
                  v-model="email"
                  type="email"
                  placeholder="your@email.com"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="email"
                />
              </div>
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">验证码</label>
                <div class="flex gap-2">
                  <input
                    v-model="verifyCode"
                    type="text"
                    placeholder="6位数字"
                    maxlength="6"
                    class="flex-1 h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="loading"
                  />
                  <button
                    type="button"
                    @click="handleSendCode"
                    :disabled="codeCooldown > 0 || !email.trim() || !isEmailValid(email)"
                    class="px-3 py-1.5 text-xs font-medium rounded-md border border-input bg-transparent text-foreground hover:bg-muted transition disabled:opacity-50 whitespace-nowrap"
                  >
                    {{ codeCooldown > 0 ? `${codeCooldown}s` : '发送验证码' }}
                  </button>
                </div>
              </div>
              <template v-if="isRegister">
                <div class="flex flex-col gap-2">
                  <label class="text-sm font-medium text-foreground">用户名</label>
                  <input
                    ref="usernameInput"
                    v-model="username"
                    type="text"
                    placeholder="2-32 个字符"
                    maxlength="32"
                    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="loading"
                    autocomplete="username"
                  />
                </div>
                <div class="flex flex-col gap-2">
                  <label class="text-sm font-medium text-foreground">密码</label>
                  <input
                    v-model="password"
                    type="password"
                    placeholder="至少 8 位"
                    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="loading"
                    autocomplete="new-password"
                  />
                </div>
              </template>
            </div>

            <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
              <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {{ error }}
            </div>

            <button
              type="submit"
              :disabled="loading || !email.trim() || verifyCode.length < 6"
              class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
            >
              <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : (isRegister ? '注册' : '登录') }}</span>
              <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </button>
          </form>

          <!-- Reset password mode -->
          <form v-if="resetMode && !needEmailBind" @submit.prevent="handleResetPasswordSubmit" class="px-6 pb-6">
            <div class="flex flex-col gap-4">
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">邮箱</label>
                <input
                  v-model="resetEmail"
                  type="email"
                  placeholder="your@email.com"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="email"
                />
              </div>
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">验证码</label>
                <div class="flex gap-2">
                  <input
                    v-model="resetCode"
                    type="text"
                    placeholder="6位数字"
                    maxlength="6"
                    class="flex-1 h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="loading"
                  />
                  <button
                    type="button"
                    @click="handleSendResetCode"
                    :disabled="codeCooldown > 0 || !resetEmail.trim() || !isEmailValid(resetEmail)"
                    class="px-3 py-1.5 text-xs font-medium rounded-md border border-input bg-transparent text-foreground hover:bg-muted transition disabled:opacity-50 whitespace-nowrap"
                  >
                    {{ codeCooldown > 0 ? `${codeCooldown}s` : '发送验证码' }}
                  </button>
                </div>
              </div>
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">新密码</label>
                <input
                  v-model="resetNewPassword"
                  type="password"
                  placeholder="至少 8 位"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="new-password"
                />
              </div>
              <div class="flex flex-col gap-2">
                <label class="text-sm font-medium text-foreground">确认新密码</label>
                <input
                  v-model="resetConfirmPassword"
                  type="password"
                  placeholder="再次输入新密码"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="loading"
                  autocomplete="new-password"
                />
              </div>
            </div>

            <p v-if="resetSuccess" class="mt-3 text-sm text-emerald-600 dark:text-emerald-400">{{ resetSuccess }}</p>
            <div v-if="error" class="mt-3 text-sm text-destructive flex items-center gap-1.5">
              <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {{ error }}
            </div>

            <button
              type="submit"
              :disabled="loading || !resetEmail.trim() || resetCode.length < 6 || resetNewPassword.length < 8 || resetConfirmPassword.length < 8"
              class="w-full mt-5 h-9 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed relative overflow-hidden"
            >
              <span :class="{ 'opacity-0': loading }">{{ loading ? '处理中...' : '重置密码' }}</span>
              <svg v-if="loading" class="animate-spin h-4 w-4 absolute" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </button>

            <div class="mt-3 text-center">
              <button type="button" class="text-sm text-muted-foreground hover:text-foreground transition" @click="backToLogin">
                返回登录
              </button>
            </div>
          </form>

          <!-- Toggle -->
          <div v-if="!needEmailBind && !resetMode" class="px-6 py-4 bg-muted/50 text-center border-t border-border/50">
            <span class="text-sm text-muted-foreground">{{ isRegister ? '已有账号？' : '还没有账号？' }}</span>
            <button
              @click="toggleRegister"
              class="text-sm text-primary hover:text-primary/80 font-medium ml-1 transition"
            >
              {{ isRegister ? '去登录' : '立即注册' }}
            </button>
          </div>

          <!-- Close button -->
          <button
            type="button"
            class="absolute top-3 right-3 inline-flex items-center justify-center size-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            @click="$emit('close')"
          >
            <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            <span class="sr-only">关闭</span>
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { authLogin, authRegister, authLoginWithEmail, authRegisterWithEmail, sendVerifyCode, bindEmailWithToken, resetPassword } from '@/api/index.js'
import { setAuthToken } from '@/services/http.js'
import { validateUsername, validatePassword } from '@/utils/validate.js'

const props = defineProps({
  visible: Boolean,
  embedded: { type: Boolean, default: false },
  hideHeader: { type: Boolean, default: false }
})
const emit = defineEmits(['close', 'login-success'])

const usernameInput = ref(null)
const formEl = ref(null)
const isRegister = ref(false)
const loginMode = ref('password') // 'password' | 'email'
const username = ref('')
const password = ref('')
const email = ref('')
const verifyCode = ref('')
const rememberMe = ref(true)
const loading = ref(false)
const error = ref('')
const codeCooldown = ref(0)
let cooldownTimer = null
const needEmailBind = ref(false)
const tempToken = ref('')
const bindEmail = ref('')
const bindCode = ref('')
const resetMode = ref(false)
const resetEmail = ref('')
const resetCode = ref('')
const resetNewPassword = ref('')
const resetConfirmPassword = ref('')
const resetSuccess = ref('')

const authTitle = computed(() => {
  if (resetMode.value) return '重置密码'
  return isRegister.value ? '创建账号' : '欢迎回来'
})

const authSubtitle = computed(() => {
  if (resetMode.value) return '使用已绑定邮箱验证身份'
  return isRegister.value ? '注册后即可使用全部功能' : '登录以访问你的面试题库'
})

// Email format validation
const isEmailValid = (e) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim())

function clearCooldown() {
  if (cooldownTimer) {
    clearInterval(cooldownTimer)
    cooldownTimer = null
  }
  codeCooldown.value = 0
}

function startCooldown() {
  clearCooldown()
  codeCooldown.value = 60
  cooldownTimer = setInterval(() => {
    codeCooldown.value--
    if (codeCooldown.value <= 0) clearCooldown()
  }, 1000)
}

function resetResetPasswordForm() {
  resetEmail.value = ''
  resetCode.value = ''
  resetNewPassword.value = ''
  resetConfirmPassword.value = ''
  resetSuccess.value = ''
}

function showResetPassword() {
  error.value = ''
  resetSuccess.value = ''
  resetMode.value = true
  isRegister.value = false
  loginMode.value = 'password'
  resetEmail.value = email.value || ''
  clearCooldown()
}

function backToLogin() {
  error.value = ''
  resetMode.value = false
  resetSuccess.value = ''
  loginMode.value = 'password'
  clearCooldown()
  nextTick(() => usernameInput.value?.focus())
}

function toggleRegister() {
  isRegister.value = !isRegister.value
  error.value = ''
  resetMode.value = false
  resetSuccess.value = ''
  clearCooldown()
}

watch(() => props.visible, (v) => {
  if (v) {
    error.value = ''
    isRegister.value = false
    loginMode.value = 'password'
    resetMode.value = false
    resetResetPasswordForm()
    clearCooldown()
    needEmailBind.value = false
    tempToken.value = ''
    bindEmail.value = ''
    bindCode.value = ''
    nextTick(() => usernameInput.value?.focus())
  }
})

onMounted(() => {
  if (props.embedded) {
    nextTick(() => usernameInput.value?.focus())
  }
})

async function handleSendCode() {
  if (codeCooldown.value > 0 || !email.value.trim()) return
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailRegex.test(email.value.trim())) {
    error.value = '请输入正确的邮箱格式'
    return
  }
  error.value = ''
  try {
    const purpose = isRegister.value ? 'register' : 'login'
    await sendVerifyCode(email.value.trim(), purpose)
    startCooldown()
  } catch (e) {
    error.value = e.message || '发送失败'
  }
}

async function handleSendResetCode() {
  if (codeCooldown.value > 0 || !resetEmail.value.trim()) return
  if (!isEmailValid(resetEmail.value)) {
    error.value = '请输入正确的邮箱格式'
    return
  }
  error.value = ''
  resetSuccess.value = ''
  try {
    await sendVerifyCode(resetEmail.value.trim(), 'reset_password')
    startCooldown()
  } catch (e) {
    error.value = e.message || '发送失败'
  }
}

async function handleResetPasswordSubmit() {
  if (loading.value) return
  error.value = ''
  resetSuccess.value = ''

  if (!isEmailValid(resetEmail.value)) {
    error.value = '请输入有效的邮箱地址'
    return
  }
  if (resetCode.value.length < 6) {
    error.value = '请输入 6 位验证码'
    return
  }
  const passResult = validatePassword(resetNewPassword.value)
  if (!passResult.valid) { error.value = passResult.error; return }
  if (resetNewPassword.value !== resetConfirmPassword.value) {
    error.value = '两次输入的新密码不一致'
    return
  }

  loading.value = true
  try {
    await resetPassword(resetEmail.value.trim(), resetCode.value, passResult.value)
    resetSuccess.value = '密码已重置，请使用新密码登录'
    password.value = ''
    email.value = resetEmail.value.trim()
    resetCode.value = ''
    resetNewPassword.value = ''
    resetConfirmPassword.value = ''
    clearCooldown()
  } catch (e) {
    error.value = e.message || '重置失败'
  } finally {
    loading.value = false
  }
}

async function handlePasswordSubmit() {
  if (loading.value) return
  error.value = ''

  const userResult = validateUsername(username.value)
  if (!userResult.valid) { error.value = userResult.error; return }
  const passResult = validatePassword(password.value)
  if (!passResult.valid) { error.value = passResult.error; return }

  if (isRegister.value && !isEmailValid(email.value)) {
    error.value = '请输入有效的邮箱地址'
    return
  }

  loading.value = true
  try {
    const fn = isRegister.value ? authRegister : authLogin
    const args = isRegister.value
      ? [userResult.value, passResult.value, email.value.trim()]
      : [userResult.value, passResult.value, rememberMe.value]
    const data = await fn(...args)

    if (data.need_email_bind) {
      needEmailBind.value = true
      tempToken.value = data.tempToken || data.temp_token
      error.value = ''
      loading.value = false
      return
    }

    setAuthToken(data.token)
    triggerBrowserSavePassword()
    emit('login-success', data.user)
    emit('close')
    username.value = ''
    password.value = ''
  } catch (e) {
    error.value = e.message || '操作失败'
  } finally {
    loading.value = false
  }
}

async function handleEmailSubmit() {
  if (loading.value) return
  error.value = ''

  if (!email.value.trim() || verifyCode.value.length < 6) {
    error.value = '请输入邮箱和验证码'
    return
  }

  loading.value = true
  try {
    let data
    if (isRegister.value) {
      const userResult = validateUsername(username.value)
      if (!userResult.valid) { error.value = userResult.error; return }
      const passResult = validatePassword(password.value)
      if (!passResult.valid) { error.value = passResult.error; return }
      data = await authRegisterWithEmail(email.value.trim(), verifyCode.value, userResult.value, passResult.value)
    } else {
      data = await authLoginWithEmail(email.value.trim(), verifyCode.value)
    }
    setAuthToken(data.token)
    emit('login-success', data.user)
    emit('close')
    email.value = ''
    verifyCode.value = ''
    username.value = ''
    password.value = ''
  } catch (e) {
    error.value = e.message || '操作失败'
  } finally {
    loading.value = false
  }
}

async function handleSendBindCode() {
  if (codeCooldown.value > 0 || !bindEmail.value.trim()) return
  if (!isEmailValid(bindEmail.value)) {
    error.value = '请输入正确的邮箱格式'
    return
  }
  error.value = ''
  try {
    await sendVerifyCode(bindEmail.value.trim(), 'bind')
    startCooldown()
  } catch (e) {
    error.value = e.message || '发送失败'
  }
}

async function handleBindEmailSubmit() {
  if (loading.value) return
  error.value = ''
  if (!isEmailValid(bindEmail.value)) {
    error.value = '请输入有效的邮箱地址'
    return
  }
  if (bindCode.value.length < 6) {
    error.value = '请输入 6 位验证码'
    return
  }
  loading.value = true
  try {
    const data = await bindEmailWithToken(bindEmail.value.trim(), bindCode.value, tempToken.value)
    setAuthToken(data.token)
    emit('login-success', data.user)
    emit('close')
    needEmailBind.value = false
    tempToken.value = ''
    bindEmail.value = ''
    bindCode.value = ''
  } catch (e) {
    error.value = e.message || '绑定失败'
  } finally {
    loading.value = false
  }
}

function triggerBrowserSavePassword() {
  if (window.PasswordCredential && formEl.value) {
    try {
      const cred = new PasswordCredential(formEl.value)
      navigator.credentials.store(cred)
      return
    } catch { /* fallback below */ }
  }
  try { history.pushState(null, '', location.href) } catch {}
}

onUnmounted(() => {
  clearCooldown()
})
</script>

<style scoped>
.dialog-fade-enter-active {
  transition: opacity 0.25s ease;
}
.dialog-fade-leave-active {
  transition: opacity 0.18s ease;
}
.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}
.dialog-fade-enter-active > div:last-child {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.25s ease;
}
.dialog-fade-enter-from > div:last-child {
  opacity: 0;
  transform: scale(0.95) translateY(8px);
}

@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.animate-slide-up {
  animation: slide-up 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@media (prefers-reduced-motion: reduce) {
  .dialog-fade-enter-active,
  .dialog-fade-leave-active {
    transition-duration: 0.01ms !important;
  }
  .dialog-fade-enter-active > div:last-child {
    transition-duration: 0.01ms !important;
  }
  .animate-slide-up {
    animation: none;
  }
}
</style>
