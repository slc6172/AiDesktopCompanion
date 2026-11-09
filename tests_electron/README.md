# tests_electron — 真實 Electron 的頁面層情境(非自動測試,人工/半自動驗證)

環境變數 `PY` 指定要用哪個 Python(要裝好 `requirements.txt`,預設 `python`);`ELECTRON` 指定 Electron 執行檔(預設 `../electron/node_modules/electron/dist/electron`,先在 `electron/` 跑 `npm install`)。需要 `xvfb-run`、`openbox`、`xdotool`、`curl`。

用法(在 `scenarios/` 目錄):

    PROJ=<專案目錄> CTXISO=0 ../run.sh s_burst2.js ../stub-osc.js

- `PROJ`:含 `companion/` 套件與 `static/` 的目錄(我們的專案根,或 Part-15 的 `.../companion`)。
- `CTXISO=0`:`contextIsolation:false`,stub 才能改 `navigator.mediaDevices`。
- 伺服器(`serve.py`,離線 `COMPANION_FAKE=1`)與 Electron 在**同一個指令內**啟動與收掉;結束時 `kill -9`(SIGTERM 會被長駐的 `/chat/proactive` SSE 卡住)。
- 每次執行都用**全新 userData**,並關閉 HTTP 快取(Electron 磁碟快取會跨次留存,曾讓兩個專案互相拿到對方的頁面)。腳本應先檢查載入的是哪一份頁面(`s_burst2.js` 有做)。
- `COMPANION_STT_MODE_FILE=<檔>`:`serve.py` 每次轉錄讀此檔:`text`(預設)/`empty`(STT 聽不到 → `stt_empty`)/`say:<文字>`。**只改 harness,不動正式程式。**
- 其他環境變數:`COMPANION_SPEAKING_BOOST`、`COMPANION_AUTO_LISTEN`、`GUM_FAIL=1`、`PAGE_LOG=1`、`OUT=<截圖目錄>`。

## 沙盒驗證不到的(不要當成已驗證)

- Windows 真實麥克風/喇叭;Chromium 真實的 AEC 狀態(假麥克風不回報)。
- 真實 Groq。假 STT 只是回固定字串/空字串。
- `setIgnoreMouseEvents(..., {forward:true})` 在 Linux 不支援:穿透只能驗「頁面送出的訊息」。
- 沒有音訊輸出裝置:播放音訊的情境用 `player.handle(...)` 假造「角色在說話」。
- 腳本內寫死的視窗座標是舊 Xvfb 1920×1080(+openbox)的值;不同請先懷疑環境。

## 尚未建立

- (已建立)`run-main.sh` + `main-launch.js`:用真實 `electron/main.js` 跑 s40a/s40b/s41/s42/s43/s_cache4。掛鉤只攔 `Menu.buildFromTemplate`(`global.__menus`)與 IPC `set-ignore-mouse-events`(`global.__ignoreMsgs`),不改 main.js。用法:`COMPANION_DATA_DIR=/tmp/x PROJ=<專案> ../run-main.sh s43.js`(要 openbox + xdotool)。
- (已實作)`s57_probation.js` 取代舊的 `s_probation_TEMPLATE.js`:候選→確認→恢復的 10 個情境,`CASES=1,3` 可只跑指定情境。

## 基線(票 53,各跑 2 次,結果相同)

角色「在說話」時出現 0.12 RMS 的雜訊,量 `stopAudio` 呼叫次數:

| 雜訊長度 | Part-15 頁面 | 我們(part11e)頁面 |
|---|---|---|
| 150 ms | 0 次(不切) | 0 次(不切) |
| 350 ms | **1 次,狀態變 `listening`(永久切斷)** | **0 次,仍 `talking:*`** |
| 900 ms | 2 次(切斷,之後回覆) | 2 次(切斷,之後回覆) |

這是只用「單一音量 0.12、單一設備(假麥克風)」量到的,不是真實喇叭回音。
