# 架構導覽

給想看懂這個程式怎麼運作、或想動手改它的人。從程式碼寫成,不是設計規格;細節以程式碼為準。想看歷史上的設計討論,在 [設計歸檔](design-archive/README.md)。

## 1. 大圖:兩個行程

```
run.bat ──► pythonw.exe app.py ──► launcher.py ──┬─► 本機伺服器(FastAPI + uvicorn,127.0.0.1)
                                                 │      server.py ──► 回合引擎 engine.py ──► 模型 / 語音 / 記憶 / 狀態
                                                 └─► electron\main.js ──► 透明視窗 ──► static\index.html(整個畫面)
                                                              ▲                                  │
                                                              └────── HTTP 與事件串流(SSE) ◄────┘
```

- **Python 後端**做所有「思考」:對話、記憶、狀態、語音合成與辨識、照片。它在 `127.0.0.1` 開一個 HTTP 伺服器。
- **Electron** 只負責視窗(無邊框、透明、置頂、穿透、系統匣、退出)。畫面本身是後端提供的 `static\index.html`,視窗只是把它顯示出來。
- `launcher.py` 先開伺服器,再開 Electron;Electron 一結束,就關閉伺服器、整個程式結束。沒有命令列視窗時(`run.bat`),輸出寫進 `data\app.log`。

## 2. 一輪對話發生了什麼

你按下 Enter(或放開說話鍵)之後:

1. **頁面** 把訊息 `POST` 到 `/chat`(語音則把錄音送到 `/chat/audio`,先由 `groq_stt.py` 轉成文字,再當成普通訊息)。
2. **`server.py`** 把它交給 `TurnEngine.send()`,並把引擎吐出的每個事件轉成一行 JSON,用 SSE 串流回頁面。
3. **`engine.py`** 組出這一輪給模型的系統提示:人設 + 回覆格式規則 + 角色現在的狀態與好感度(`statebox.py`)+ 記憶(`memoryblock.py` 的長期事實與近兩天日誌、`retrieval.py` 找出的相關舊事)+ 時間感(`timesense.py`)+ 啟用中的功能的標籤說明。好感度在這時才依「離開了多久」計算衰減,沒有計時器。
4. 若你的話是在叫角色查資料,且有啟用:先去查(`tinyfish_adapter.py`),查回的網頁文字經過 `websafety.py` 隔離,再讓模型第二次回答。這一輪會被標成「受污染」(polluted)。
5. **模型串流**(`gemini_llm.py`)回來的文字,由引擎內部的斷句器切成「(情緒, 一句話)」;標籤從文字裡拿掉,交給標籤處理(下一節)。
6. **每一句**依序:合成語音(`_say` → 語音轉接器)→ 吐出 `Sentence` 事件(文字與情緒),有聲音時再吐出 `Audio`。頁面收到後同時顯示文字、播放聲音、切換動畫。
7. **存檔**(只有走到這一步才存):對話寫進資料庫,好感度與最後互動時間更新,狀態標籤這時才生效,必要時在背景把舊對話摺疊進記憶(`_fold`)。最後吐出 `Done`。
8. **失敗**(模型逾時、額度用完…)吐出 `Failure`,附上角色口吻的道歉;**這一輪什麼都不存**,所以重試不會重複。

沒有人說話時,`engine.py` 的排程器在閒置夠久之後(若啟用主動發言)會自己跑一輪,事件走 `/chat/proactive` 這條推送管道。

## 3. 引擎吐出的事件

| 事件 | 意思 |
|---|---|
| `Transcript` | 語音辨識出來的你說的話 |
| `Sentence` | 角色的一句話與它的情緒 |
| `Audio` | 那一句的語音 |
| `Notice` | 給使用者看的提示(功能停用、查詢中…) |
| `OutfitChange` | 換了服裝,附上新服裝的片段清單 |
| `Photo` | 一張新照片做好了 |
| `Failure` | 這一輪失敗了 |
| `Done` | 這一輪結束 |

## 4. 標籤機制

模型的回覆裡可以夾帶方括號標籤。**只有一個解析器**(引擎裡的斷句器),所有標籤種類登錄在 `tags.py` 的一張表;要新增一種標籤,是加一列,不是加一個解析器。

- **情緒標籤**:`[neutral]`、`[happy]`、`[angry]`、`[sad]`、`[surprised]`,標示接下來那段文字的情緒,不在登錄表裡。
- **狀態類(meta)**:`[好感…]`、`[心情…]`、`[地點…]`、`[狀態…]`、`[得到…]`、`[失去…]`。出現在回覆的哪裡都算,從文字中拿掉,**只有這一輪被存檔時才生效**。太長的會被丟掉而不是念出來。
- **動作類(action)**:`[換裝…]`、`[搜尋…]`、`[照片…]`。這些會對對話之外造成後果,所以**只在回覆開頭**才被認,每種每輪最多一個;放在別處會被拿掉但**不執行**。
- **防護:** 用過網頁內容的那一輪(polluted),除了心情,其他標籤一律忽略。這是防止網頁內容「說服」模型去換裝、拍照或改狀態的結構性做法。

## 5. 模組地圖

### 後端(`companion\`)

| 領域 | 模組 |
|---|---|
| 啟動與設定 | `launcher.py`(啟動伺服器與 Electron)、`server.py`(路由與事件轉 JSON)、`config.py`(預設值與各設定的解析)、`paths.py`、`apikey.py`(金鑰查找)、`debuglog.py` |
| 回合引擎 | `engine.py`(整輪流程、事件、斷句、排程)、`tags.py`(標籤登錄表)、`errors.py`(模型錯誤的種類)、`features.py`(這次執行有哪些選用功能) |
| 記憶 | `history.py`(對話與記憶的儲存)、`memoryblock.py`(放進提示的記憶文字)、`retrieval.py`(找出相關的舊事) |
| 角色狀態 | `state.py`(服裝、地點、身體狀態、物品的儲存)、`statebox.py`(放進提示的狀態區塊)、`outfits.py`(掃描 `clips\`、換裝) |
| 時間 | `timesense.py`(純函式,不碰時鐘) |
| 模型與語音轉接器 | `gemini_llm.py`、`groq_stt.py`、`edge_tts_adapter.py`、`primetts_adapter.py`(OpenAI 相容的本機語音伺服器)、`fish_adapter.py` |
| 選用功能 | `photos.py`、`cloudflare_adapter.py`、`imageprep.py`(照片);`tinyfish_adapter.py`、`websafety.py`、`searchintent.py`(查資料) |
| 離線試玩 | `fake_llm.py`、`fake_stt.py`、`fake_tts.py`(`COMPANION_FAKE=1` 時取代真實服務) |
| 開發用 | `latencysmoke.py`、`statesmoke.py`(給根目錄的 `smoke_*.py` 用) |

### 前端(`static\`)

`index.html` 是整個畫面(角色、工具列、對話面板、語音),其餘是從中抽出來、可以單獨測試的純邏輯:

| 檔案 | 職責 |
|---|---|
| `player.js` | 角色狀態機(待機、聆聽、思考、說話) |
| `clipswitch.js` | 什麼時候該切換動畫、缺檔時退回哪一個 |
| `shell.js` | 視窗排版、滑鼠命中判斷、退出鈕的兩段式確認 |
| `probation.js` | 角色說話時偵測到聲音(可能是插話)的處理 |
| `vad.js` | 偵測你有沒有在說話 |
| `audio-capture-policy.js`、`aec-capture-worklet.js` | 麥克風擷取與回音消除 |

### Electron(`electron\`)

`main.js`(視窗、系統匣、穿透、結束)、`preload.js`(只暴露給頁面最小的一組視窗功能)、`windowstate.js`(視窗位置與縮放,存在 `data\window-state.json`)。

### 伺服器的路由

| 路由 | 用途 |
|---|---|
| `/` | 頁面 |
| `/chat`、`/chat/audio` | 一輪對話(文字、錄音),回應是事件串流 |
| `/chat/proactive` | 主動發言的推送管道 |
| `/avatar` | 目前的服裝與各狀態的影片位址 |
| `/config` | 給頁面的設定:語音偵測參數、視窗操作設定、語音辨識是否可用 |
| `/history` | 先前的對話 |
| `/photos/<檔名>` | 拍好的照片 |
| `/static`、`/clips`、`/fillers` | 頁面檔案、角色動畫、思考短音 |

## 6. 資料夾結構

```
app.py              程式入口(run.bat 用 pythonw 啟動它)
companion\          後端
static\             前端(由伺服器提供)
electron\           桌寵視窗
clips\  fillers\    你的角色動畫、思考短音(內容不入庫)
data\               對話與記憶(history.db)、視窗位置、記錄檔(不入庫)
config.json         你的設定(不入庫);範本是 config.example.json
persona.md          你的人設(不入庫);範本是 persona.example.md
animation-tools\    做動畫用的批次檔
smoke_*.py          連真實服務的手動檢查
tests\  tests_js\  tests_electron\   Python、前端、真實 Electron 情境的測試
tools\              開發用小工具(突變測試、記錄分析)
docs\               文件;docs\design-archive\ 是歷史設計筆記
```

## 7. 想改什麼,先看哪裡

- **加一種標籤:** `tags.py` 加一列,再在 `engine.py` 的 `_handle_tags` 加它的處理。
- **換一個語音引擎:** 照 `edge_tts_adapter.py` 寫一個轉接器,在 `config.py` 的 `resolve_engine` 登記引擎名稱,並在 `server.py` 的 `build_tts` 建立它。
- **改角色說話的方式:** 人設檔(`persona.md`);回覆格式規則與標籤說明在 `engine.py`。改了送給模型的文字,要做「提示詞回歸」,見 [貢獻指南](../CONTRIBUTING.md)。
- **加一個設定:** `config.py` 的預設值與解析,再補 [設定參考](configuration.md);文件測試會提醒你。
- **動畫怎麼被找到:** `outfits.py` 與 `clipswitch.js`,規則見 [動畫製作教學](animation-tutorial.md)。
