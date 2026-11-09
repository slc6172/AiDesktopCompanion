# 設定參考

這份文件列出**每一個**可以調整的東西:`config.json` 的每個設定與預設值、每個環境變數、每個命令列旗標,以及金鑰怎麼放。第一次安裝請先看 [安裝教學](install.md);這裡是安裝完之後想「改成自己想要的樣子」時查的。

> 撰寫與核對日期:2026-11-01。第三方服務(Gemini、Groq、Fish Audio、Cloudflare、TinyFish、Edge 語音)的名稱與額度可能改變,以各服務官方頁面為準。

## 1. `config.json` 怎麼用

- 它是專案資料夾裡的一個純 JSON 檔,用任何文字編輯器就能改。專案**沒有附**這個檔案:不設定就用內建預設值。要自訂,複製範本再改:

  ```powershell
  copy config.example.json config.json
  notepad config.json
  ```

- **只寫你想改的欄位**,沒寫的欄位用預設值。一個區塊(例如 `tts`)只寫其中一個欄位,同區塊的其他欄位仍是預設。
- **改完要重新啟動程式**才生效。
- **優先順序:環境變數 > `config.json` > 內建預設。**(金鑰的規則相同:環境變數 > Windows 憑證管理員。)
- 這是人手編輯的檔案,所以寫錯**不會讓程式起不來**:檔案不是合法 JSON,整個當成沒設;某個欄位的型別不對或超出範圍,只有那個欄位退回預設,其他照常。
- `config.json` 與 `persona.md`、`data\` 一樣是你自己的檔案,**不會被 git 追蹤**。**不要把金鑰寫進 `config.json`**(金鑰另有地方放,見第 3 節)。
- 視窗位置、置頂、縮放不在這裡:它們存在 `data\window-state.json`,由視窗工具列操作。

下面每個區塊先給**預設值**(這個區塊由自動測試與程式裡真正的預設值逐項比對,不會與程式不一致),再逐欄說明。

## 2. 命令列旗標

在專案資料夾用虛擬環境的 Python 執行,例如 `.venv\Scripts\python app.py --set-key`。平常用 `run.bat` 啟動就好,不需要任何旗標。

| 旗標 | 說明 |
|---|---|
| `--port` | 本機伺服器的起始連接埠(預設 8000,例如 `--port 8001`);被佔用時自動換一個。 |
| `--set-key` | 儲存 Gemini 金鑰後結束。 |
| `--set-key-groq` | 儲存 Groq 金鑰(語音辨識用)後結束。 |
| `--set-key-fish` | 儲存 Fish Audio 金鑰(選用 Fish 語音才需要)後結束。 |
| `--set-key-tinyfish` | 儲存 TinyFish 金鑰(上網查資料用)後結束。 |
| `--set-key-cloudflare` | 儲存 Cloudflare API Token(照片用)後結束。 |
| `--reset-state` | 把角色狀態(服裝、地點、身體狀態、持有物品)重設回起點後結束。**不會**動對話、記憶、好感度與照片額度。 |

> 顯示方式只有一種:Electron 桌寵視窗。

## 3. 金鑰

| 服務 | 用途 | 環境變數 | 存進憑證管理員 |
|---|---|---|---|
| Gemini | 對話模型(必要) | `GEMINI_API_KEY`(也接受 `GOOGLE_API_KEY`) | `--set-key` |
| Groq | 語音辨識(沒有就沒有麥克風,仍可打字) | `GROQ_API_KEY` | `--set-key-groq` |
| Fish Audio | 選用的雲端語音 | `FISH_API_KEY` | `--set-key-fish` |
| TinyFish | 上網查資料(選用) | `TINYFISH_API_KEY` | `--set-key-tinyfish` |
| Cloudflare | 照片生成(選用)的 API Token | `CF_API_TOKEN` | `--set-key-cloudflare` |
| Cloudflare 帳號 ID | 照片生成(它**不是**機密) | `CF_ACCOUNT_ID` | (寫在 `image.account_id`) |

- **查找順序:先看環境變數,再看 Windows 憑證管理員**(經由 `keyring`)。兩處都沒有,該功能就停用,程式照常啟動,並在聊天面板提示一次。
- 存進憑證管理員的金鑰不會出現在任何檔案裡;`--set-key*` 會跳出輸入視窗(沒有圖形環境時退回命令列輸入),貼上後存檔。
- **怎麼取得各服務的金鑰**請看 [安裝教學](install.md)。

## 4. `config.json` 的區塊

### 4.1 語音輸出 `tts`

<!-- config-defaults: tts -->
```json
{
  "tts": {
    "enabled": true,
    "engine": "auto",
    "fallback": true,
    "edge": {
      "voice": "zh-TW-HsiaoChenNeural",
      "rate": "+0%",
      "volume": "+0%",
      "pitch": "+0Hz"
    },
    "openai": {
      "url": null,
      "model": "primetts",
      "voice": "default",
      "format": "wav",
      "api_key": null,
      "timeout_s": 15
    },
    "fish": {
      "model": "s2.1-pro-free",
      "reference_id": null,
      "format": "mp3",
      "timeout_s": 20,
      "emotion_tags": {
        "neutral": "",
        "happy": "[happy]",
        "sad": "[sad]",
        "angry": "[angry]",
        "surprised": "[surprised]"
      }
    }
  }
}
```

| 欄位 | 說明 |
|---|---|
| `tts.enabled` | 總開關。`false` = 只顯示文字,下面所有語音設定與金鑰都不會被看。 |
| `tts.engine` | 語音引擎:`"auto"`(預設:有填 `tts.openai.url` 就用該伺服器,沒填就用 edge-tts)、`"edge"`、`"openai"`(也可寫成 `"primetts"`,兩者是同一個引擎)、`"fish"`、`"off"`。**`auto` 永遠不會自己選 `fish`**:它是有自己金鑰與資料條款的雲端服務,必須明確指定。 |
| `tts.fallback` | 主要引擎對某一句失敗(連不上、逾時、伺服器錯誤)時,是否改用另一個引擎。`false` = 只用主要引擎,失敗就沒聲音。 |
| `tts.edge.voice` | edge-tts 的聲音名稱,見下方「**角色的聲音是女聲還是男聲**」。 |
| `tts.edge.rate` / `volume` / `pitch` | 語速、音量、音高,例如 `"+20%"`(快兩成)、`"-10%"`、`"+5Hz"`、`"-10Hz"`。 |
| `tts.openai.url` | 你本機的 OpenAI 相容語音伺服器位址,**含 `/v1`**(例如 `"http://127.0.0.1:8880/v1"`,不含 `/audio/speech`);不填就不會用到它。 |
| `tts.openai.model` / `voice` | 送給你的伺服器的 `model` / `voice` 欄位,依你的伺服器支援的值填。 |
| `tts.openai.format` | 回傳的音訊格式:`"wav"`、`"mp3"`、`"opus"`、`"flac"`。 |
| `tts.openai.api_key` | 你的伺服器要求時才填,不需要就留 `null`。 |
| `tts.openai.timeout_s` | 等待合成的逾時秒數。 |
| `tts.fish.model` | Fish 模型,預設免費的 `"s2.1-pro-free"`。**Fish 對「沒帶標頭或不認得的型號」會改用付費的型號**,所以打錯字可能產生費用:型號不在已知清單時,程式仍會照你寫的送出,請自行確認。 |
| `tts.fish.reference_id` | 你在 Fish 挑選或複製的聲音模型 ID;`null` = Fish 的預設聲音。 |
| `tts.fish.format` | `"mp3"`(預設)或 `"wav"`;寫了別的退回 `mp3`。 |
| `tts.fish.timeout_s` | 逾時秒數,0 到 300 之間的數字;寫成文字、`null`、0、負數都退回 20。 |
| `tts.fish.emotion_tags` | 各情緒對應的 Fish 標籤,會加在每一句話前面再送去合成(例如 `[sad] …`)。**只有 Fish 會收到標籤**,edge-tts 與 OpenAI 相容伺服器不會(它們會把標籤念出來)。標籤內容可自由改,例如 `"[excited]"`;`""` = 不加標籤。動畫不受影響。 |

**自動切換備援:** 主要引擎失敗時,該句自動改用備援引擎,同一輪後面的句子直接用備援,下一輪再重新試主要引擎。Fish 連不上、逾時、被限流(429)或伺服器錯誤時也是這樣;但**金鑰錯誤、餘額不足(402)、聲音 ID 不存在**會直接顯示錯誤,不會悄悄換引擎。

#### 角色的聲音是女聲還是男聲

聲音由 `tts.edge.voice` 決定,**與人設檔無關**,而且**預設值 `zh-TW-HsiaoChenNeural` 是女聲**。這只是預設,不是限制。台灣中文(`zh-TW`)的 Edge 語音目前有三個:

| 聲音名稱 | 性別 |
|---|---|
| `zh-TW-HsiaoChenNeural`(預設) | 女 |
| `zh-TW-HsiaoYuNeural` | 女 |
| `zh-TW-YunJheNeural` | 男 |

改成男聲:

```json
{ "tts": { "edge": { "voice": "zh-TW-YunJheNeural" } } }
```

這份名單查證於 2026-11-01(Microsoft 的語音清單、`edge-tts` 專案的輸出範例與多個獨立來源一致)。語音清單會變動,**以你機器上實際列出的為準**:

```powershell
.venv\Scripts\python -m edge_tts --list-voices
```

輸出有 `Name`、`Gender` 欄位,找 `zh-TW-` 開頭的即可;想用其他語言或腔調(例如 `zh-CN-`、`zh-HK-`、`en-US-`)也一樣從這份清單挑。**語音的語言要和角色說話的語言一致。** 想臨時試別的聲音,可以不改檔案、直接設環境變數 `COMPANION_VOICE`。

### 4.2 語音輸入 `stt`

<!-- config-defaults: stt -->
```json
{
  "stt": {
    "enabled": true,
    "language": null,
    "filter": true,
    "allowed_languages": [
      "zh",
      "en",
      "ja"
    ],
    "ignore_phrases": [
      "thank you",
      "thanks",
      "okay",
      "yes",
      "music",
      "and the",
      "you",
      "bye"
    ],
    "prompt": null,
    "no_speech_prob_max": 0.6,
    "avg_logprob_min": -1.0,
    "debug_log": false
  }
}
```

| 欄位 | 說明 |
|---|---|
| `stt.enabled` | 總開關。`false` = 只能打字,沒有麥克風控制,下面的設定都不會被看。沒有 Groq 金鑰時也會自動關閉麥克風並提示一次。 |
| `stt.language` | 給辨識器的語言提示(例如 `"zh"`)。預設 `null` = 自動偵測。**不建議指定**:強制指定後,整句英文或日文可能被翻成中文或變成亂碼。 |
| `stt.filter` | 防呆總開關。`true` = 啟用下面幾種過濾;`false` = 完全不過濾。 |
| `stt.allowed_languages` | 你會說的語言(代碼或英文名稱,例如 `"zh"`、`"Japanese"`)。辨識結果被偵測成**其他語言**的錄音會被丟掉。`[]` = 不限制。**程式不認得的語言名稱不會被丟掉**(寧可放過一句,也不誤殺你真的說的話)。 |
| `stt.ignore_phrases` | 辨識器常從雜音或回音「無中生有」的短句。**整段**辨識結果(忽略大小寫與標點)剛好等於其中一項,**而且**被偵測成你的主要語言以外的語言時,整段丟掉。主要語言 = `stt.language`,沒設則是 `allowed_languages` 的第一個。代價:你只說一句英文的「Thank you.」也會被當成沒聽清楚。`[]` = 關閉。需要 `stt.filter` 開著。 |
| `stt.prompt` | 隨每段錄音送給辨識器的一小段提示文字,例如 `"使用者主要以繁體中文對話,也可能使用英文。只轉錄實際聽到的語音。"`。可以讓用字偏向繁體,但**也可能讓它更敢「聽出」字**,所以預設關(`null`)。Groq 最多讀約 224 個 token。 |
| `stt.no_speech_prob_max` / `avg_logprob_min` | 辨識器**自己的信心**:一段話如果它認為「很可能不是人聲」(超過 `no_speech_prob_max`)**而且**對自己寫的內容沒把握(低於 `avg_logprob_min`),就丟掉。兩個條件**必須同時成立**。調嚴(更容易丟掉):`no_speech_prob_max` 調小、`avg_logprob_min` 調大(例如 `-0.7`)。需要 Groq 回傳詳細結果;缺欄位時什麼都不丟。 |
| `stt.debug_log` | 開著時,每段錄音在 `data\app.log` 寫一行 `[stt]`(聽到什麼、有多確定、保留或丟掉),用來調上面的數字。**不存音檔。** 平常關著。 |

**症狀與原因:** 持續聆聽時,偶爾會出現「你根本沒說」的話,通常是外文。原因有兩層:①角色從喇叭放出的聲音又被麥克風收進去,被當成你在說話;②語音辨識(Whisper)遇到雜音或回音殘留時,會自己「編」出一句常見的話,而且常常是別國語言。**最直接有效的辦法是戴耳機**;不戴耳機時,上面的過濾能擋掉一部分。被丟掉的錄音,對話視窗會顯示「沒聽清楚,可以再說一次嗎?」,**連續 3 次**會自動關閉持續聆聽。

**怎麼收集資料調參數(查完就能關):**

1. 設 `"stt": { "debug_log": true }`,重新啟動。
2. 不戴耳機,開持續聆聽,正常聊一陣子。
3. 看 `data\app.log`(或用 `run-debug.bat` 啟動直接在視窗看),搜尋 `[stt]`。每行長這樣:

   ```
   [stt] dropped (language russian) | 48000 bytes | language=russian | no_speech_prob=0.71 | avg_logprob=-1.32 | 'Доброе утро!'
   [stt] kept | 60000 bytes | language=chinese | no_speech_prob=0.02 | avg_logprob=-0.31 | '今天天氣不錯'
   ```

4. 看**沒被丟掉的假對話**與**被誤丟的真話**,依數字調整。欄位值是 `?` 表示 Groq 沒回傳那個欄位;**如果每一行都是 `?`,代表過濾沒有生效**(此時 `stt.filter` 沒有東西可依據)。
5. 調好之後把 `debug_log` 改回 `false`。

你說的話本來就存在 `data\history.db`;這個日誌多出來的只是被丟掉的那些,而且只存在你的電腦上。

#### 量測回音:決定 `ui.speaking_boost` 該設多少(約 10 分鐘)

**為什麼要量測:** 不戴耳機時,角色的聲音從喇叭漏回麥克風,音量一超過門檻就會被當成你在說話。門檻在瀏覽器回報回音消除已啟用時是 0.02,回報不明時是 0.035,並會隨環境噪音自動微調。角色說話時偵測到聲音,不會立刻被切斷:角色的音量先被壓低(預設約 -8 dB,可用 `ui.duck_level` 調整),等辨識結果回來,確定是你說的話才打斷角色;結果是空的、被過濾掉、或是 "Thank you." 之類的幻聽,角色就恢復音量接著說。所以回音的代價是「角色的聲音短暫變小」。

`ui.speaking_boost` 的做法是「角色說話時,門檻提高 N 倍」。N 太小擋不住回音;N 太大你就得大聲吼才能插話。**合適的 N 在「回音有多響」與「你插話有多大聲」之間,這兩個數字只有你的機器量得到。**

**準備:** `stt.debug_log` 設 `true`,`ui.speaking_boost` 保持 `1`,**不戴耳機**、用平常的喇叭音量,開持續聆聽,重新啟動。每段錄音會有兩行(`[audio]` 緊接著 `[stt]`):

```
[audio] 29000 bytes | peak=0.051;during_speech=1;started_speaking=1;boost=1;duck=0.4
[stt] kept | 29000 bytes | language=Chinese | no_speech_prob=0 | avg_logprob=-0.27 | '好喔'
```

| 欄位 | 意思 |
|---|---|
| `peak` | 這段錄音期間麥克風**最大的音量**(0 到 1)。 |
| `during_speech` | `1` = 錄音期間角色在說話。 |
| `started_speaking` | `1` = 錄音**開始**時角色就在說話(被你插話,或被回音誤觸發)。 |
| `boost`、`duck` | 這段錄音當時的 `ui.speaking_boost`、`ui.duck_level`。 |

**做這四個情境,每個做 5 次,記下 `peak`:**

1. **只有回音:** 叫角色講一段長的(例如「講個故事」),**你一句話都不要說**,等角色講完。`during_speech=1` 的行,它們的 `peak` 就是你的機器上回音的音量。(完全沒有這種行 = 回音沒超過門檻,不需要加成。)
2. **正常音量插話:** 角色講到一半,你用平常的音量插話。
3. **小聲插話:** 同上,但用你覺得「插得進去的最小聲」。
4. **角色沒說話時正常講話:** 一般對話,當作你的正常音量基準。

**挑倍數:** 門檻是 0.02,倍數 N 表示角色說話時門檻變成 `0.02 × N`。要滿足:**回音最大的 peak < 0.02 × N < 小聲插話最小的 peak**。例如回音最大 0.055、小聲插話最小 0.14,就可以選 N = 4(門檻 0.08)。**如果回音的 peak 與插話的 peak 重疊**(回音比你小聲插話還大),單靠倍數分不開,請改戴耳機、降低喇叭音量,或把麥克風移遠一點。調好後把 `debug_log` 改回 `false`。

### 4.3 桌寵視窗 `ui`

<!-- config-defaults: ui -->
```json
{
  "ui": {
    "auto_listen": false,
    "on_top_level": "normal",
    "hit_width_ratio": 0.6,
    "speaking_boost": 1.0,
    "duck_level": 0.4
  }
}
```

| 欄位 | 說明 |
|---|---|
| `ui.auto_listen` | `true` = 程式啟動後自動開啟持續聆聽(只嘗試一次;麥克風被拒絕時會在對話紀錄說明,不會重複嘗試)。預設 `false`:會自己打開的麥克風應該是你要求的。 |
| `ui.on_top_level` | `"normal"`(預設,一般置頂)或 `"screen-saver"`(Windows 上會蓋過工作列與部分全螢幕程式,包括全螢幕簡報,**可能會擋到你**)。其他值當成 `"normal"`。 |
| `ui.hit_width_ratio` | 角色中間多寬的範圍會收滑鼠,0.2 到 1.0;角色身體兩側的透明空白讓點擊穿透。超出範圍當成 0.6。 |
| `ui.speaking_boost` | **角色說話時,你要比平常大聲幾倍才能插話**(角色的聲音從喇叭漏回麥克風,會被當成你在說話)。`1` = 關閉(預設);範圍 1 到 10。**先不要亂調**:合適的數字取決於你的喇叭與麥克風,請先照上面「量測回音」的步驟量測。 |
| `ui.duck_level` | **偵測到可能的插話時,角色的音量壓到多低**(在辨識結果回來、確定是不是你之前)。`1` = 完全不壓低,`0.4` = 約 -8 dB(預設),`0.2` = 約 -14 dB;範圍 0.1 到 1。壓得少,角色的聲音較不受影響,但角色自己的回音也比較容易混進那段錄音;壓得多則相反。 |

### 4.4 主動發言 `proactive`

<!-- config-defaults: proactive -->
```json
{
  "proactive": {
    "enabled": false,
    "min_minutes": 10,
    "max_minutes": 30
  }
}
```

角色主動開口這個功能**預設是關的**。`min_minutes` / `max_minutes` 是「雙方都閒置多久(分鐘)之後,角色才可能自己開口」,實際時間在這兩個數字之間隨機挑。時間落在 `time.quiet_hours` 內時,這次主動發言直接略過,之後照常再排下一次。目前沒有執行中即時開關的按鈕,只能改設定並重新啟動。

### 4.5 時間觀念 `time`

角色知道**現在幾點、星期幾**,也知道**跟你上一句話隔了多久**,所以隔了三天再說「早」,它不會把這句當成上一秒的下一句;早餐、午餐、晚餐、深夜也會有自然的反應。預設就是開的。

| 情況 | 角色的反應 |
|---|---|
| 連續聊天(隔不到 30 分鐘) | 視為接續,不提時間 |
| 隔了半小時到 6 小時 | 知道隔了一陣子,話題多半還接得上 |
| 隔了半天以上 | 不會硬接上一個話題 |
| 隔了好幾天 | 不會當成剛剛才說的,可能問候近況 |
| 隔了一個多禮拜 | 有「好久不見」的感覺 |
| 進入早餐 / 午餐 / 晚餐時段後的**第一句話** | 可能自然問你吃了沒(同一時段不會再問第二次) |
| 深夜(預設 23:00–07:00) | 角色**不會裝睡**,但發現太晚了會關心你怎麼還沒睡,語氣放輕 |
| 主動發言開著時 | 半夜到清晨(預設 00:00–07:00)**不會主動開口**;你自己開口不受限制 |
| 長期記憶 | 你說「下週要面試」,會被記成絕對日期,幾個月後不會還以為是下週 |

<!-- config-defaults: time -->
```json
{
  "time": {
    "enabled": true,
    "timezone": null,
    "gap_marker_minutes": 30,
    "routine": [
      {
        "name": "早餐",
        "start": "07:00",
        "end": "09:00",
        "hint": "這個時間通常會吃早餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"
      },
      {
        "name": "午餐",
        "start": "12:00",
        "end": "13:30",
        "hint": "這個時間通常會吃午餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"
      },
      {
        "name": "晚餐",
        "start": "18:00",
        "end": "19:30",
        "hint": "這個時間通常會吃晚餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"
      },
      {
        "name": "深夜",
        "start": "23:00",
        "end": "07:00",
        "hint": "現在是睡覺的時間。你自己維持醒著、不要裝睡,但發現太晚時可以自然地關心他怎麼還沒睡,語氣放輕一點。"
      }
    ],
    "quiet_hours": {
      "enabled": true,
      "start": "00:00",
      "end": "07:00"
    }
  }
}
```

| 欄位 | 說明 |
|---|---|
| `time.enabled` | **總開關。** `false` = 完全沒有以上任何行為。 |
| `time.timezone` | 時區,填 IANA 名稱,例如 `"Asia/Taipei"`;不填(`null`)就用這台電腦的時區。填錯名稱會自動退回電腦的時區,不會報錯。**Windows 需要 `tzdata` 套件才認得時區名稱**(已在 `requirements.txt`)。 |
| `time.gap_marker_minutes` | 兩句話隔多久以上,才讓角色知道「隔了一陣子」。 |
| `time.routine` | 作息清單:每一筆有 `name`、`start`、`end`(`"HH:MM"`,24 小時制,必須兩位數)、`hint`(給角色的一句提示)。**你填的清單會整個取代預設清單**(不是加在後面);填 `[]` 代表不使用作息。時段重疊時,**排在前面的**優先。某一筆寫錯(時間格式不對、缺名稱或提示、起迄相同)只會丟掉那一筆。`start` 比 `end` 晚(例如 22:30 到 07:00)代表跨午夜。 |
| `time.quiet_hours` | 主動發言的安靜時段。`enabled: false` 就不限制。 |

**範例:新增下午茶、並把深夜改成 22:30 開始。** 清單會取代預設,所以早餐、午餐、晚餐要自己寫進去:

```json
"routine": [
  {"name": "早餐", "start": "07:00", "end": "09:00", "hint": "這個時間通常會吃早餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"},
  {"name": "午餐", "start": "12:00", "end": "13:30", "hint": "這個時間通常會吃午餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"},
  {"name": "下午茶", "start": "15:00", "end": "16:00", "hint": "這是下午茶時間,可以隨口聊聊要不要喝點什麼。"},
  {"name": "晚餐", "start": "18:00", "end": "19:30", "hint": "這個時間通常會吃晚餐,可以自然地帶到(像是問他吃了沒),不必每次都提。"},
  {"name": "深夜", "start": "22:30", "end": "07:00", "hint": "現在是睡覺的時間。你自己維持醒著、不要裝睡,但發現太晚時可以自然地關心他怎麼還沒睡,語氣放輕一點。"}
]
```

同一個時段的提示只會在進入時段後的第一句話出現,而且**不會被存進對話紀錄**。

**資料與隱私:**「現在的時間」與「距上一句多久」會跟著對話一起送給 Gemini,沒有新增其他外傳。對話紀錄(`data\history.db`)裡**只存你真正說的話與角色真正的回覆**,「(距上一句約 3 天)」這類註記只存在於送給模型的那一份,所以規則改了(例如把 30 分鐘改成 60 分鐘),舊的對話紀錄馬上套用新規則。**已知限制:** 模型偶爾會把「(距上一句約…)」之類的字眼當成說話習慣念出來;發生時可以先把 `time.enabled` 設成 `false`。

### 4.6 服裝 `outfit`

<!-- config-defaults: outfit -->
```json
{
  "outfit": {
    "default": "日常",
    "aliases": {
      "睡衣": [
        "睡袍",
        "pajamas"
      ]
    }
  }
}
```

`clips\` 下每個不以底線開頭的子資料夾是一套服裝,資料夾名稱就是服裝名稱。對角色說「換成睡衣」就會換,重啟後仍是那一套。

| 欄位 | 說明 |
|---|---|
| `outfit.default` | 還沒選過任何服裝時穿的那一套(資料夾名稱)。 |
| `outfit.aliases` | 別名:`{"睡衣": ["睡袍", "pajamas"]}` 表示說「睡袍」也算睡衣。格式是 `{資料夾名稱: [別名…]}`。 |

服裝資料夾裡放什麼檔案、怎麼命名,見 [動畫製作教學](animation-tutorial.md)。沒有任何服裝時,角色以表情符號代替,仍然可以聊天。

### 4.7 照片 `image`

<!-- config-defaults: image -->
```json
{
  "image": {
    "enabled": false,
    "model": "flux-2-klein-9b",
    "account_id": null,
    "width": 576,
    "height": 1024,
    "max_per_day": 6,
    "cooldown_s": 30,
    "timeout_s": 120,
    "appearance": ""
  }
}
```

角色可以「拍照」給你看,使用 Cloudflare Workers AI 的圖像模型。**預設關閉。**

| 欄位 | 說明 |
|---|---|
| `image.enabled` | 總開關。 |
| `image.model` | 圖像模型名稱。 |
| `image.account_id` | Cloudflare 帳號 ID;也可用環境變數 `CF_ACCOUNT_ID`(環境變數優先)。它不是機密。 |
| `image.width` / `height` | 圖片尺寸,256 到 1920。 |
| `image.max_per_day` | 每天最多幾張(0 到 1000)。**以 UTC 日期計**,台灣早上 8 點換日。 |
| `image.cooldown_s` | 兩張之間至少隔幾秒。 |
| `image.timeout_s` | 等待生成的逾時秒數。 |
| `image.appearance` | 角色外觀的**英文**描述,在沒有基底照時使用。 |

**啟用步驟:**

1. 到 Cloudflare 建立 API Token(需要 Workers AI 權限),執行 `.venv\Scripts\python app.py --set-key-cloudflare` 存進憑證管理員(或設 `CF_API_TOKEN`)。
2. 帳號 ID 填 `image.account_id`,或設 `CF_ACCOUNT_ID`。
3. 把 `image.enabled` 改成 `true`,並安裝 Pillow:`.venv\Scripts\python -m pip install Pillow`(已在 `requirements.txt`;只有啟用照片時才會載入)。
4. **每套服裝放一張基底照 `base.png`,或填寫 `image.appearance`**;否則啟動時會警告,而且拍出來的人物每張可能不同。基底照的規格見 [動畫製作教學](animation-tutorial.md)。

Cloudflare 回報免費額度用完時,照片功能會停到下個 00:00 UTC。缺金鑰或帳號 ID 時功能自動停用,程式照常啟動,並在面板提示一次。

### 4.8 上網查資料 `tinyfish`

<!-- config-defaults: tinyfish -->
```json
{
  "tinyfish": {
    "enabled": false,
    "location": "TW",
    "language": "zh",
    "max_results": 5,
    "quarantine": true,
    "blocked_domains": []
  }
}
```

**預設關閉。** 啟用:`.venv\Scripts\python app.py --set-key-tinyfish`(或設 `TINYFISH_API_KEY`),再把 `tinyfish.enabled` 改成 `true`。

| 欄位 | 說明 |
|---|---|
| `tinyfish.location` / `language` | 搜尋的地區與語言。 |
| `tinyfish.max_results` | 每次最多取幾筆結果,1 到 10。 |
| `tinyfish.quarantine` | 網頁內容是否一律當成「不可信資料」處理(預設開):先清洗、用隨機分隔標記包起來;用過網頁內容的那一回合,角色只有心情標籤有效(不會因此換裝、拍照或改狀態),網頁內容也不會進入歷史與長期記憶。 |
| `tinyfish.blocked_domains` | 不想讓角色讀的網站(網域清單)。 |

### 4.9 記憶 `memory`

<!-- config-defaults: memory -->
```json
{
  "memory": {
    "enabled": true,
    "long_term_max_chars": 2000,
    "recent_notes_max_chars": 600,
    "retrieval_k": 3,
    "retrieval_snippet_chars": 200,
    "retrieval_min_message_chars": 3,
    "retrieval_min_score": 0.6,
    "archive_scan_limit": 20000
  }
}
```

聊過一定輪數後,舊對話會被整理成「當日日誌」與「長期事實」(事件用絕對日期記錄);之後聊到相關話題時自動檢索(只比對字面重疊,同義說法找不到)。長期事實分成固定的區段:使用者、共同經歷、角色自己的事、待跟進、更早的摘要。

| 欄位 | 說明 |
|---|---|
| `memory.enabled` | 總開關。環境變數 `COMPANION_MEMORY=off` 無論檔案怎麼寫都會關閉。 |
| `memory.long_term_max_chars` | 長期事實的總字數上限(200 到 20000);太長會被壓縮。 |
| `memory.recent_notes_max_chars` | 近期日誌放進提示的字數上限。 |
| `memory.retrieval_k` | 每次最多帶出幾條相關的舊記憶。 |
| `memory.retrieval_snippet_chars` | 每條相關記憶最多帶幾個字。 |
| `memory.retrieval_min_message_chars` | 你的訊息短於這個字數就不去檢索。 |
| `memory.retrieval_min_score` | 比對要多強才算相關;**越高越保守**(帶出的記憶更少、更準)。 |
| `memory.archive_scan_limit` | 檢索時最多往回掃幾則舊訊息。 |

> 記憶與對話存在 `data\history.db`。

### 4.10 角色狀態 `companion_state`

<!-- config-defaults: companion_state -->
```json
{
  "companion_state": {
    "enabled": true,
    "default_location": "家裡",
    "status_ttl_hours": {
      "微醺": 3,
      "酒醉": 8,
      "疲倦": 10,
      "感冒": 72
    },
    "default_status_ttl_hours": 12,
    "max_items": 20
  }
}
```

角色持續記得自己在哪裡、身體狀態(喝酒、感冒等,會依時間自動恢復)和持有的物品,並在對話中用標籤宣告變化。

| 欄位 | 說明 |
|---|---|
| `companion_state.enabled` | 總開關。 |
| `companion_state.default_location` | 起始地點。 |
| `companion_state.status_ttl_hours` | 各種身體狀態多久自動恢復(小時),格式 `{狀態詞: 小時}`;你寫的詞會**加進**預設清單。 |
| `companion_state.default_status_ttl_hours` | 沒列在上表的狀態詞預設多久恢復。 |
| `companion_state.max_items` | 最多持有幾件物品,1 到 100。 |

要把服裝、地點、身體狀態、持有物品重設回起點:`.venv\Scripts\python app.py --reset-state`(**不會**動對話、記憶、好感度與照片額度)。

## 5. 環境變數總表

全部都是**選用**的,不設就用預設值。**環境變數的優先權高於 `config.json`**;無效的值視同沒設,退回設定檔或預設。表中標「布林」的變數,`0`、`false`、`off`、`no` 與空字串是「關」,其他值是「開」。

### 模型與語音辨識

| 名稱 | 預設 | 說明 |
|---|---|---|
| `COMPANION_MODEL` | `gemini-3.5-flash-lite` | 對話使用的 Gemini 模型。換成更聰明的模型時,注意它們的免費額度通常少很多。 |
| `COMPANION_LLM_TIMEOUT_MS` | `20000` | 等待 Gemini 的逾時(毫秒)。 |
| `COMPANION_STT_MODEL` | `whisper-large-v3-turbo` | Groq 語音辨識使用的模型。 |
| `COMPANION_VAD_SILENCE_MS` | `700` | 持續聆聽:安靜超過這麼久視為一句話講完。 |
| `COMPANION_VAD_MIN_MS` | `500` | 錄到的聲音短於這麼久就忽略、不送出(按住說話與持續聆聽共用)。 |

### 語音輸出(對應 `tts.*`;平常建議改 `config.json`,這裡給臨時覆蓋或自動化部署用)

| 名稱 | 對應設定 | 說明 |
|---|---|---|
| `COMPANION_TTS` | `tts.engine` | `off` 關閉語音;`edge`、`openai`(或 `primetts`)、`fish`、`auto`。 |
| `COMPANION_TTS_FALLBACK` | `tts.fallback` | 設成 `off` 關掉備援引擎。 |
| `COMPANION_VOICE` | `tts.edge.voice` | edge-tts 的聲音。 |
| `COMPANION_RATE` | `tts.edge.rate` | 語速。 |
| `COMPANION_VOLUME` | `tts.edge.volume` | 音量。 |
| `COMPANION_PITCH` | `tts.edge.pitch` | 音高。 |
| `COMPANION_PRIMETTS_URL` | `tts.openai.url` | OpenAI 相容語音伺服器位址(含 `/v1`)。設了它,`auto` 就以它為主、edge-tts 為備援。 |
| `COMPANION_PRIMETTS_MODEL` | `tts.openai.model` | 送給伺服器的 `model` 欄位。(`PRIMETTS` 是沿用的舊稱,指的就是 OpenAI 相容伺服器。) |
| `COMPANION_PRIMETTS_VOICE` | `tts.openai.voice` | 送給伺服器的 `voice` 欄位。 |
| `COMPANION_PRIMETTS_FORMAT` | `tts.openai.format` | 回傳的音訊格式。 |
| `COMPANION_PRIMETTS_API_KEY` | `tts.openai.api_key` | 伺服器要求時才設,以 Bearer 帶出。 |
| `COMPANION_PRIMETTS_TIMEOUT_S` | `tts.openai.timeout_s` | 等待合成的逾時(秒)。 |
| `COMPANION_FISH_MODEL` | `tts.fish.model` | Fish 模型。 |
| `COMPANION_FISH_REFERENCE_ID` | `tts.fish.reference_id` | Fish 聲音模型 ID。 |
| `COMPANION_FISH_FORMAT` | `tts.fish.format` | `mp3` 或 `wav`。 |
| `COMPANION_FISH_TIMEOUT_S` | `tts.fish.timeout_s` | 逾時秒數(0 到 300)。 |

### 桌寵視窗與主動發言(平常建議改 `config.json`)

| 名稱 | 對應設定 | 說明 |
|---|---|---|
| `COMPANION_AUTO_LISTEN` | `ui.auto_listen` | 布林:啟動後自動開啟持續聆聽。 |
| `COMPANION_ON_TOP_LEVEL` | `ui.on_top_level` | `normal` 或 `screen-saver`。 |
| `COMPANION_HIT_WIDTH_RATIO` | `ui.hit_width_ratio` | 0.2 到 1.0。 |
| `COMPANION_SPEAKING_BOOST` | `ui.speaking_boost` | 1 到 10。 |
| `COMPANION_DUCK_LEVEL` | `ui.duck_level` | 0.1 到 1。 |
| `COMPANION_PROACTIVE` | `proactive.enabled` | 布林:開啟主動發言。 |
| `COMPANION_PROACTIVE_MIN_MINUTES` | `proactive.min_minutes` | 閒置門檻的下限(分鐘)。 |
| `COMPANION_PROACTIVE_MAX_MINUTES` | `proactive.max_minutes` | 閒置門檻的上限(分鐘);實際時間在下限與上限之間隨機挑。 |

### 記憶、好感度、檔案位置

| 名稱 | 預設 | 說明 |
|---|---|---|
| `COMPANION_MEMORY` | (開) | 設成 `off` 關閉長期記憶(優先於 `memory.enabled`)。 |
| `COMPANION_AFFECTION_GRACE_HOURS` | `24` | 好感度:離開不到這麼久(小時)不會衰減。 |
| `COMPANION_AFFECTION_HALF_LIFE_DAYS` | `14` | 好感度:超過寬限期後,與中性值(50)的差距每過這麼多天減半;設成 `0` 關閉衰減。 |
| `COMPANION_DB` | `data\history.db` | 對話紀錄與角色狀態的資料庫位置。 |
| `COMPANION_PERSONA` | `persona.md` | 人設檔名(放在專案資料夾)。 |

### 金鑰與帳號(見第 3 節)

`GEMINI_API_KEY`(或 `GOOGLE_API_KEY`)、`GROQ_API_KEY`、`FISH_API_KEY`、`TINYFISH_API_KEY`、`CF_API_TOKEN`、`CF_ACCOUNT_ID`。

### 開發與測試用

| 名稱 | 說明 |
|---|---|
| `COMPANION_FAKE` | 設成 `1` 進入**離線試玩**:假回覆、嗶聲當語音、不寫入你的真實紀錄(對話紀錄只留在記憶體),用來不花額度看畫面。 |
| `COMPANION_TINYFISH_TEST_URL` | 用一個**本機**的假服務代替 TinyFish,測試用(只接受本機位址,金鑰不會被送到別處)。 |

> 另外有兩個環境變數是程式自己傳給桌寵視窗用的(`COMPANION_URL`、`COMPANION_DATA_DIR`),**不是給你設定的**。
