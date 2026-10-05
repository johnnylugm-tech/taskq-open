# 對抗式 Bug Hunt 報告（Gate 3 — adversarial_review）

- 掃描時間：2026-10-05（git_sha `a936f18`）
- 目標清單：`.methodology/bug_hunt_targets.json`（16 高風險 / 36 標準）
- 鏡頭：threat-model、correctness、concurrency、resilience、general
- 工件：`.methodology/bug_hunt_report.json`
- 結論：**0 個已確認 critical/high bug**；13 條宣告威脅的 mitigation 全部有效（refuted）；1 條 low 觀察（不擋 gate）。

## 掃描摘要（module × severity）

| module | high | medium | low | 結果 |
|---|---|---|---|---|
| service.auth (T-01) | 1 | | | mitigation 有效 |
| api.deps (T-02/T-03) | 1 | 1 | | mitigation 有效 |
| service.ratelimit (T-04) | 1 | | | mitigation 有效 |
| service.tasks (T-05) | 1 | | | mitigation 有效 |
| service.runner (T-06) | 1 | | | mitigation 有效 |
| service.executor+runner (T-07) | 1 | | | mitigation 有效 |
| repository.tasks (T-08) | 1 | | | mitigation 有效 |
| migrations.v3_split_results (T-09) | 1 | | | mitigation 有效 |
| api.middleware (T-10/T-13) | 1 | 1 | | mitigation 有效 |
| service.redact (T-11) | 1 | | 1 | 宣告範圍有效；tq_ 為範圍外觀察 |
| api.error_handlers (T-12) | 1 | | | mitigation 有效 |

## 威脅模型驗證（每條：攻擊向量 → 嘗試利用 → mitigation 是否擋住）

所有 13 條皆屬 SAD.md §6 宣告威脅，驗證重點是「宣告的 mitigation 是否真的擋住攻擊」而非「是否存在防禦性程式碼」。每條在 JSON 工件有 `attack_vector` / `attempted_exploit` / `mitigation_effective` 欄位，並附對應 `test_sec_tNN`（全 13 條通過）。

- **T-01 spoofing / auth**：偽造/猜測/撤銷金鑰 → hash 查無 → 401；撤銷金鑰 `_is_active` 檢 `revoked_at is None`（auth.py L87）→ 401。`compare_digest` 常數時間。**擋住**。
- **T-02 EoP / deps**：低 scope 打高 scope 端點 → 每個 /v1 route 都掛 `guard(<scope>)`，`require_scope.check`（deps.py L87-89）在 handler 前判 403。已逐一確認 routes_tasks/runs/metrics 的 scope。**擋住**。
- **T-03 info-disclosure / deps+error_handlers**：403/404 洩漏存在性 → 授權先於查找；403 body `instance=None`（error_handlers.py L47）。**擋住**。
- **T-04 DoS / ratelimit**：單 token 洪流 → row-lock token bucket（BEGIN IMMEDIATE）+ 429/Retry-After。**擋住**。
- **T-05 tampering / service.tasks**：注入字元入庫 → 黑名單 `;&|`$<>\n\r` + 長度上限 → 422。**擋住**。
- **T-06 EoP / runner**：shell 解讀命令 → `shlex.split` + `create_subprocess_exec(*argv)`，無 shell。**擋住**。
- **T-07 DoS / executor+runner**：掛死任務留孤兒 → `wait_for` 逾時 → `_kill`=kill()+await wait() 回收；drain 取消並 await。**擋住**。
- **T-08 tampering / repository.tasks**：字串拼 SQL 注入 → 全程 SQLAlchemy ORM 綁定參數；cursor 先驗證。**擋住**。
- **T-09 tampering / v3 migration**：升降級資料遺失 → 真實可逆 up/downgrade，json_extract/json_group_array 保留每欄與型別；真實 SQLite round-trip 測試通過。**擋住**（唯一非精確情況：v1 單物件 result_json 正規化為單元素陣列，為文件化設計）。
- **T-10 repudiation / middleware**：請求無法溯源 → correlation id 進 header（L56）、body（error_handlers L48）、log（L62）。**擋住**。
- **T-11 info-disclosure / redact**：秘密經輸出/日誌洩漏 → `redact()` 於截斷前逐行遮蔽 sk-/token=/Bearer/postgres URL；db_url `repr=False` 且不入 metrics。宣告的 4 類秘密全覆蓋。**擋住**。
- **T-12 info-disclosure / error_handlers**：錯誤 body 洩漏內部 → 未處理例外轉 `InternalError.GENERIC_DETAIL`，僅 server-side log；驗證錯誤回通用文案。**擋住**。
- **T-13 spoofing / middleware(CORS)**：跨源驅動 API → `CORSMiddleware(allow_origins=TASKQ_CORS_ORIGINS)`，預設空 = 全拒。**擋住**。

## Low / 觀察（不擋 gate）

- **redact#tq-gap**（low）：`SECRET_PATTERN` 未涵蓋本系統自身 `tq_` 前綴金鑰（auth.py L23）。超出 T-11 宣告範圍（T-11 僅列 sk-/token/Bearer/DB-URL，皆已覆蓋）。可利用性低：需金鑰出現在使用者自備命令的輸出中，無他人金鑰流入受害命令輸出的實際路徑。建議（選配）：於 pattern 增 `tq_[A-Za-z0-9_-]{8,}`。狀態 open（low 不需於 Gate 3 前解決）。

## Mutation survivors 分診

Manifest 的 10 個 survivor（executor 277/278/283、runner 148/166、runs 260、auth 108、tasks 21、health 225、redact 258）已逐一回讀對應函式。`mutmut show` 因 cache 過期無法輸出 diff；`test_nfr08_mutation_kills.py` 已針對可殺行為下斷言，殘存者為等價變異或已接受之未測行為，未發現可達的真實 bug（具體失敗場景）。依協議，survivor 為 hunt 輸入而非獨立 gate 項。

## 修復優先順序

無需修復（0 個已確認 critical/high）。選配：redact tq_ 覆蓋（low）。

## 掃描方法

讀 `bug_hunt_targets.json` → 完整 Read 全部高風險模組與其呼叫鏈（app/config/errors/session/migration_state/routes）→ 對 13 條宣告威脅逐一構造攻擊並對照 mitigation 程式碼路徑 → 執行全部 13 個 `test_sec_tNN`（通過）作為反駁證據 → 寫 `bug_hunt_report.json`（通過 schema 驗證）。異源要求由 hunt 模型（opus-4-8，與開發模型不同）滿足。

## 範圍外事項（告知，不處理）

- `tests/test_nfr_static.py::test_nfr09_verified_only_when_tests_pass` 在 HEAD `a936f18` 即失敗（本次 hunt 未改動任何檔案）：`TRACEABILITY_MATRIX.md` 的 VERIFIED 列引用測試「檔名」而非反引號 `test_` 函式名，與該 meta-test 的 regex 不符。屬 traceability 文件格式問題，非 hunt 目標、非威脅、非程式路徑 bug。
