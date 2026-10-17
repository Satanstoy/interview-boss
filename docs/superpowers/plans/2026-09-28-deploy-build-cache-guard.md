# 部署磁盘保护加固：让缓存清理每次部署都真正生效

**背景**：2026-09-28 一次正式 `update` 构建成功后因空间不足被拒。排查发现磁盘保护
机制存在"**失败即跳过、跳过即成功**"的缺陷，任何一步 flake 都会静默关闭保护。

**已确认的 4 类缺陷**（均有现场证据）：

| # | 缺陷 | 证据 |
|---|---|---|
| A | `prune_build_cache` 有 3 条"记日志 + `return 0`"的跳过路径 | 2026-09-28 03:35 维护日志：`builder 尚未创建，跳过其缓存清理` → 同份日志结尾 `存储维护完成`，缓存未动 |
| B | `light` 模式带 `--filter until=168h`，只挑过期条目，对刚用过的缓存永远清 0 | 手工执行输出 `Total: 0B`，当时缓存 3.0GB |
| C | 只有 `free < DEPLOY_HARD_MIN_FREE_MB` 才升级到无过滤清理 | 缓存允许从 1.5GB 涨到 3.0GB（cap 的 2 倍）并持续数小时 |
| D | 清理后无任何结果校验 | 只能靠 `free` 检查兜底；清不动就只是拒绝部署，不告警、不重试 |

**方案**（用户已批准）：方案 2 主动收敛作骨架 + 方案 1 结果校验 + 方案 3 可观测，
覆盖**全部**入口（`build` / `update` / `worker-up` / `worker-restart` / `test` /
`cleanup` / `storage-maintenance`）。

**核心不变量**：
1. 触发条件从「`free < 目标`」改为「**`cache > cap` 或 `free < 目标`**」
2. 不再有 light/aggressive 两级 —— 缓存收敛**不带年龄过滤**，直接收到 cap
3. 清理函数**不得静默跳过**：builder 真不存在才算合法 no-op，"读不到"一律返回失败
4. 每次清理后**读回校验**（`df` + `buildx du`），不达标 → 告警 + 拒绝

## 文件映射

| 文件 | 职责 |
|---|---|
| `deploy/docker-deploy.sh`（改） | 新增 `_size_to_mb` / `_buildkit_cap_mb` / `buildkit_cache_total_mb` / `buildkit_cache_reclaimable_mb` / `verify_disk_state` / `ensure_build_space` / `write_build_metrics`；重写 `prune_build_cache`；改 `ensure_disk_before_build`、`cleanup_after_build`、`do_maintenance`、`do_cleanup`；新增 `storage-self-check` 子命令 |
| `deploy/tests/test_build_cache_guard.sh`（新） | 行为测试：PATH 打桩假 `docker`/`df`，真跑子命令 |
| `deploy/tests/test_storage_controls_contract.sh`（改） | 静态契约断言同步 |
| `backend/tests/infra/test_docker_config.py`（改） | 同步静态断言 |
| `deploy/CLAUDE.md` / `CLAUDE.md`（改） | 文档同步 |

---

### Task 1: 行为测试骨架（RED）

**Files:**
- Create: `deploy/tests/test_build_cache_guard.sh`

- [ ] Step 1: 写打桩与 3 个场景断言
- [ ] Step 2: `sudo bash deploy/tests/test_build_cache_guard.sh` → 期望 FAIL（新函数不存在）

打桩要点（沿用 `test_test_lifecycle.sh` 范式）：

```bash
cat > "$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DOCKER_CALLS"
case "$*" in
  "buildx ls")          printf 'NAME/NODE   DRIVER/ENDPOINT   STATUS   BUILDKIT   PLATFORMS\ninterview-boss   docker-container\n \\_ interview-boss0   \\_ unix:///var/run/docker.sock   running   v0.32.2\n'; exit 0 ;;
  *"buildx inspect interview-boss"*) printf 'Driver: docker-container\n'; exit "${FAKE_INSPECT_RC:-0}" ;;
  "buildx du --builder interview-boss") printf 'abc\tfalse\t500.5MB\t1 hour ago\nReclaimable:\t%s\nTotal:\t\t%s\n' "${FAKE_DU_RECLAIM:-500MB}" "${FAKE_DU_TOTAL:-3000MB}"; exit "${FAKE_DU_RC:-0}" ;;
  *"buildx prune --builder interview-boss"*) exit "${FAKE_PRUNE_RC:-0}" ;;
  *) exit 0 ;;
esac
EOF

cat > "$fake_bin/df" <<'EOF'
#!/usr/bin/env bash
printf 'Filesystem 1M-blocks Used Available Capacity Mounted on\n/dev/vda2 40960 35000 %s 90%% /\n' "${FAKE_FREE_MB:-6000}"
EOF
```

三个场景：
1. **缓存超 cap → 触发不带年龄过滤的 prune，且校验通过**：`FAKE_DU_TOTAL=3000MB`、prune 后需让二次 `du` 返回 ≤cap → 用 `FAKE_DU_SEQ` 文件按调用次数返回。
2. **读不到缓存/驱动 → 不得静默成功**：`FAKE_DU_RC=1` 或 `FAKE_INSPECT_RC=1` → 断言守卫退出非 0。
3. **清理后仍低于硬阈值 → 告警并拒绝**：`FAKE_DU_TOTAL=100MB`、`FAKE_FREE_MB=1000` → 断言退出非 0 且日志含 `ALERT`。

---

### Task 2: 尺寸解析与缓存用量读取

**Files:**
- Modify: `deploy/docker-deploy.sh`（在 `_buildx_driver` 之后插入）

- [ ] Step 1: 实现 `_size_to_mb` / `_buildkit_cap_mb` / `buildkit_cache_total_mb` / `buildkit_cache_reclaimable_mb`
- [ ] Step 2: 跑 Task 1 场景 2，确认"读不到即失败"变绿

```bash
# docker 尺寸（1.5GB / 1536MB / 500.5kB / 1.2GiB）→ 整数 MB；无法解析返回非 0
_size_to_mb() {
  local raw="$1" num unit
  num=$(printf '%s' "$raw" | sed -n 's/^\([0-9][0-9.]*\)\([A-Za-z]*\)$/\1/p')
  unit=$(printf '%s' "$raw" | sed -n 's/^\([0-9][0-9.]*\)\([A-Za-z]*\)$/\2/p')
  [ -n "$num" ] || return 1
  case "$unit" in
    B)          awk -v n="$num" 'BEGIN{printf "%d", n/1048576}' ;;
    kB|KB|KiB)  awk -v n="$num" 'BEGIN{printf "%d", n/1024}' ;;
    MB|MiB|"")  awk -v n="$num" 'BEGIN{printf "%d", n}' ;;
    GB|GiB)     awk -v n="$num" 'BEGIN{printf "%d", n*1024}' ;;
    *) return 1 ;;
  esac
}

_buildkit_cap_mb() { _size_to_mb "$BUILDKIT_MAX_USED_SPACE"; }

# docker buildx du 输出落盘再解析（同 _buildx_driver：管道方式不稳定）
_buildx_du_field() {
  local field="$1" probe_file raw
  probe_file=$(mktemp 2>/dev/null) || return 1
  if ! docker buildx du --builder "$BUILDKIT_BUILDER" >"$probe_file" 2>/dev/null; then
    rm -f "$probe_file"; return 1
  fi
  raw=$(awk -F'\t' -v f="${field}:" '$1 == f {gsub(/[[:space:]]/, "", $2); print $2; exit}' "$probe_file")
  rm -f "$probe_file"
  [ -n "$raw" ] || return 1
  _size_to_mb "$raw"
}

buildkit_cache_total_mb()       { _buildx_du_field "Total"; }
buildkit_cache_reclaimable_mb() { _buildx_du_field "Reclaimable"; }
```

**注意**：读不到一律 `return 1`，**绝不回退成 `0`** —— 把"读不到"当成"没缓存"正是缺陷 A。

---

### Task 3: `prune_build_cache` 重写（消除静默跳过）

**Files:**
- Modify: `deploy/docker-deploy.sh`（替换第 316 行起的整个函数）

- [ ] Step 1: 替换函数体
- [ ] Step 2: 跑场景 1，确认"超 cap → 收敛 + 校验"变绿

```bash
# 把 BuildKit 缓存收敛到 BUILDKIT_MAX_USED_SPACE。
# 返回 0 仅当：builder 确实不存在（合法 no-op），或清理后已校验 ≤ cap。
# 任何"读不到/清不动/校验不过"一律返回非 0 —— 不再有 exit-0 的静默跳过。
prune_build_cache() {
  local cap_mb before_mb after_mb driver
  cap_mb=$(_buildkit_cap_mb) || { err "无法解析 BUILDKIT_MAX_USED_SPACE=${BUILDKIT_MAX_USED_SPACE}"; return 1; }

  if ! docker buildx ls >/dev/null 2>&1; then
    err "docker buildx 不可用，无法确认 BuildKit 缓存状态"; return 1
  fi
  if ! docker buildx ls 2>/dev/null | awk '{print $1}' | grep -qx "$BUILDKIT_BUILDER"; then
    log "BuildKit builder ${BUILDKIT_BUILDER} 不存在，无缓存需清理"; return 0
  fi
  if ! driver=$(_buildx_driver "$BUILDKIT_BUILDER"); then
    err "无法读取 ${BUILDKIT_BUILDER} 的 driver，拒绝静默跳过缓存清理"; return 1
  fi
  if [ "$driver" != "$BUILDKIT_BUILDER_DRIVER" ]; then
    err "拒绝清理非隔离 BuildKit builder: $BUILDKIT_BUILDER (driver=$driver)"; return 1
  fi
  if ! docker buildx inspect "$BUILDKIT_BUILDER" --bootstrap >/dev/null 2>&1; then
    err "${BUILDKIT_BUILDER} 无法启动，无法清理缓存"; return 1
  fi

  if ! before_mb=$(buildkit_cache_total_mb); then
    err "无法读取 BuildKit 缓存用量，拒绝在未知状态下继续"; return 1
  fi
  if [ "$before_mb" -le "$cap_mb" ]; then
    log "BuildKit 缓存 ${before_mb}MB 未超上限 ${cap_mb}MB，无需清理"; return 0
  fi

  warn "BuildKit 缓存 ${before_mb}MB 超过上限 ${cap_mb}MB，收敛中（无年龄过滤）..."
  if ! docker buildx prune --builder "$BUILDKIT_BUILDER" -f \
      --max-used-space "${BUILDKIT_MAX_USED_SPACE}" \
      --min-free-space "${DEPLOY_TARGET_FREE_MB}MB"; then
    err "docker buildx prune 执行失败"; return 1
  fi
  if ! after_mb=$(buildkit_cache_total_mb); then
    err "清理后无法读取 BuildKit 缓存用量，无法校验"; return 1
  fi
  if [ "$after_mb" -gt "$cap_mb" ]; then
    err "清理后 BuildKit 缓存仍为 ${after_mb}MB > 上限 ${cap_mb}MB"; return 1
  fi
  log "BuildKit 缓存已收敛: ${before_mb}MB → ${after_mb}MB（上限 ${cap_mb}MB）"
}
```

- [ ] Step 3: 同步改 3 处调用点：`prune_unused_docker` 内、`cleanup_after_build`、
      `do_maintenance` —— 去掉 `light|aggressive` 参数

---

### Task 4: `verify_disk_state` + 告警

**Files:**
- Modify: `deploy/docker-deploy.sh`

- [ ] Step 1: 实现校验函数
- [ ] Step 2: 跑场景 3，确认"清不动 → ALERT + 非 0"变绿

```bash
# 读回真实状态并断言。stage 只用于日志/告警前缀。
# 返回 0 = 达标；非 0 = 不达标（已发告警）。
verify_disk_state() {
  local stage="$1" free_mb cache_mb cap_mb rc=0
  free_mb=$(root_free_mb)
  cap_mb=$(_buildkit_cap_mb) || cap_mb=0
  if ! cache_mb=$(buildkit_cache_total_mb); then cache_mb=""; fi

  if [ -n "$cache_mb" ] && [ "$cap_mb" -gt 0 ] && [ "$cache_mb" -gt "$cap_mb" ]; then
    err "[$stage] BuildKit 缓存 ${cache_mb}MB 仍超上限 ${cap_mb}MB"
    storage_emit_alert "error" "[$stage] BuildKit 缓存 ${cache_mb}MB 超上限 ${cap_mb}MB"
    rc=1
  fi
  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    err "[$stage] 根分区可用 ${free_mb}MB 低于硬阈值 ${DEPLOY_HARD_MIN_FREE_MB}MB"
    storage_emit_alert "critical" "[$stage] 根分区可用 ${free_mb}MB 低于硬阈值"
    rc=1
  elif [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    warn "[$stage] 根分区可用 ${free_mb}MB 低于目标 ${DEPLOY_TARGET_FREE_MB}MB"
  fi
  log "[$stage] 磁盘状态: 可用 ${free_mb}MB / BuildKit 缓存 ${cache_mb:-未知}MB"
  write_build_metrics || true
  return "$rc"
}
```

---

### Task 5: `ensure_build_space` 统一前置关卡

**Files:**
- Modify: `deploy/docker-deploy.sh`（替换 `ensure_disk_before_build`）

- [ ] Step 1: 实现并替换；两处调用点（`guarded_compose_build` / `guarded_compose_build_project`）改为调用它
- [ ] Step 2: 跑全部 3 个场景确认绿

```bash
# 构建前/后的唯一磁盘关卡。触发条件：cache 超 cap 或 free 低于目标。
# 与旧版差异：不再"只有 free < 硬阈值才动手"，也不再依赖 age 过滤。
ensure_build_space() {
  local stage="${1:-pre-build}" free_mb cache_mb cap_mb need=0
  free_mb=$(root_free_mb)
  cap_mb=$(_buildkit_cap_mb) || cap_mb=0
  if ! cache_mb=$(buildkit_cache_total_mb); then cache_mb=""; fi

  if [ -n "$cache_mb" ] && [ "$cap_mb" -gt 0 ] && [ "$cache_mb" -gt "$cap_mb" ]; then
    log "[$stage] BuildKit 缓存 ${cache_mb}MB 超上限 ${cap_mb}MB"; need=1
  fi
  if [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    log "[$stage] 根分区可用 ${free_mb}MB 低于目标 ${DEPLOY_TARGET_FREE_MB}MB"; need=1
  fi

  if [ "$need" -eq 1 ]; then
    prune_unused_docker || warn "[$stage] 本项目资源清理未完全成功"
  fi

  if ! verify_disk_state "$stage"; then
    show_disk_usage
    return 1
  fi
}
```

`guarded_compose_build` / `_project` 中 `ensure_disk_before_build` → `ensure_build_space "pre-build"`；
`cleanup_after_build` 整个函数删除，改为 `ensure_build_space "post-build"`。

---

### Task 6: 指标 + 自检子命令

**Files:**
- Modify: `deploy/docker-deploy.sh`

- [ ] Step 1: 新增 `write_build_metrics`（写到 `storage.prom` 同目录的 `interview-boss-build.prom`）
- [ ] Step 2: 新增 `storage-self-check` 子命令并加入 usage / case

```bash
write_build_metrics() {
  local dir target tmp free_mb cache_mb cap_mb
  dir="$(dirname "${STORAGE_METRICS_FILE:-/data/interview-boss/storage.prom}")"
  target="$dir/interview-boss-build.prom"
  mkdir -p "$dir" || return 1
  free_mb=$(root_free_mb)
  cache_mb=$(buildkit_cache_total_mb) || cache_mb=0
  cap_mb=$(_buildkit_cap_mb) || cap_mb=0
  tmp="${target}.tmp.$$"
  {
    printf '# HELP interview_boss_root_free_bytes Free bytes on the root filesystem.\n'
    printf '# TYPE interview_boss_root_free_bytes gauge\n'
    printf 'interview_boss_root_free_bytes %s\n' "$((free_mb * 1024 * 1024))"
    printf '# HELP interview_boss_buildkit_cache_bytes Current buildx cache size.\n'
    printf '# TYPE interview_boss_buildkit_cache_bytes gauge\n'
    printf 'interview_boss_buildkit_cache_bytes %s\n' "$((cache_mb * 1024 * 1024))"
    printf '# HELP interview_boss_buildkit_cache_cap_bytes Configured buildx cache cap.\n'
    printf '# TYPE interview_boss_buildkit_cache_cap_bytes gauge\n'
    printf 'interview_boss_buildkit_cache_cap_bytes %s\n' "$((cap_mb * 1024 * 1024))"
  } > "$tmp" || { rm -f -- "$tmp"; return 1; }
  chmod 644 "$tmp" && mv -f -- "$tmp" "$target"
}

do_storage_self_check() {
  log "存储自检：收敛 BuildKit 缓存并校验"
  prune_unused_docker || warn "本项目资源清理未完全成功"
  if ! prune_build_cache; then err "自检失败：BuildKit 缓存无法收敛"; return 1; fi
  if ! verify_disk_state "self-check"; then err "自检失败：磁盘状态未达标"; return 1; fi
  log "自检通过"
}
```

---

### Task 7: 契约测试与文档同步

**Files:**
- Modify: `deploy/tests/test_storage_controls_contract.sh`、`backend/tests/infra/test_docker_config.py`、`deploy/CLAUDE.md`、`CLAUDE.md`

- [ ] Step 1: `prune_build_cache light|aggressive` 断言改为新函数名；新增断言：
  `ensure_build_space` / `verify_disk_state` / `write_build_metrics` / `storage-self-check` 存在，
  且**禁止** `prune_build_cache() {` 内出现 `return 0` 之外的跳过（用 `not_contains` 断言
  `尚未创建，跳过`、`跳过本轮缓存清理` 等旧文案已消失）
- [ ] Step 2: 文档写清新不变量（cap 收敛 / 不静默跳过 / 清理后校验 / 指标文件）
- [ ] Step 3: 跑 `sudo bash deploy/tests/test_storage_controls_contract.sh` +
  `uv run pytest -q backend/tests/infra/test_docker_config.py`（预期：只剩既有的
  `test_cleanup_supports_dry_run_and_aggressive` 预存失败，其余全绿）

---

### Task 8: 真机验证与提交

**Files:** 无新增

- [ ] Step 1: `sudo ./deploy/docker-deploy.sh storage-self-check` → 期望：缓存从当前值收敛到 ≤1536MB，退出 0
- [ ] Step 2: `cat /data/interview-boss/interview-boss-build.prom` → 3 个指标齐全
- [ ] Step 3: 制造超 cap 场景（临时把 `BUILDKIT_MAX_USED_SPACE` 调小），确认守卫**非 0 退出并告警**，
      而不是静默通过
- [ ] Step 4: `sudo ./deploy/docker-deploy.sh update` → 确认构建后自动收敛且部署完成（不再被拒）
- [ ] Step 5: 提交（`fix(deploy): 磁盘保护改为结果校验，清理不再静默跳过`）

---

## 验收标准

1. `prune_build_cache` 在任何"读不到/清不动/校验不过"的情况下都返回非 0
2. 每次构建前，缓存超过 `BUILDKIT_MAX_USED_SPACE` 就会被收敛，不再涨到 2× cap
3. 清理后必有读回校验；不达标发 `storage_emit_alert` 且拒绝继续
4. 5 条路径（build/update/worker-up/worker-restart/test）+ cleanup/storage-maintenance 共用同一关卡
5. 新增行为测试覆盖 3 个场景；契约测试全绿
6. 真机 `update` 一次通过，且日志里能看到"收敛 X→Y"而不是"跳过"

## 回滚

全部改动集中在 `deploy/`（root 属主），回滚即 `git revert` 对应提交；
`docker-deploy.sh` 是纯 shell，无数据迁移，回滚不需要动容器或数据库。
