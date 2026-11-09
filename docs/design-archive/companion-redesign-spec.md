> 歷史設計筆記,以程式碼為準。

# AI 陪伴專案 — 第四階段規劃:桌寵化與語音/視覺管線重構

**狀態:ready-for-agent**
**承接:** 第一~三階段(規格書 Part 1–5、票券 Part 2–6,票券 1–18)已完成的既有專案。本規劃建議 /to-tickets 產生的票券從 **第 19 張** 開始編號,延續既有編號慣例。
**產生方式:** 本文件綜合兩輪平行討論的結論撰寫,新開的實作對話不會有那兩輪討論的細節,所有結論已經收斂進本文件,不需要另外攜帶那兩輪討論的逐字紀錄或另一份平行 spec。

---

## Problem Statement

現有原型(pywebview 視窗、Gemini 語音直送、edge-tts 雲端語音、靜態圖片頭像)在兩輪使用者實測後,浮現出幾個結構性問題:

1. 要求模型自己在回覆文字最前面吐出一段 `<heard>逐字稿</heard>` 標籤,藉此讓伺服器知道「使用者剛才說了什麼」,這個作法很脆弱——模型只要有一次沒有從最前面開始就照格式輸出,整段判斷就會失準,之後串流收到的任何原始文字(包含真正的逐字稿標籤,如果它稍後才出現)都會被直接當成台詞顯示、甚至被念出來,而且這種壞掉的回覆一旦存進歷史紀錄,模型會學著在未來的回覆裡重複同樣的錯誤格式,問題因此會在某次之後持續發生、越來越常見。
2. 打斷(使用者在角色還在說話或還在思考時開口)沒有在伺服器端被乾淨地取消——被放棄的那一輪可能還是會跑完並寫入共用的歷史紀錄或狀態,而且每一次「成功的打斷」本身都被前端誤算成一次「語音辨識失敗」,導致連續幾次完全正常的打斷,就可能誤觸發把持續聆聽整個關掉的保護機制。
3. 語音合成遇到「這個片段完全沒有內容可以念」(例如切分後只剩一個獨立的刪節號)這種情況時,原本的例外處理把它誤判成「整個語音服務都壞了」,導致同一輪之後所有句子的聲音都被關掉。
4. 角色的呈現方式是一個方形的 pywebview 視窗、身體是一張靜態圖片,不是使用者想要的、像開源專案 airi 那樣可以自由擺放在桌面上的獨立角色物件。
5. 語音辨識與語音合成完全依賴雲端服務,沒有本地/免費的選項,口音與音質也無法控制,身體沒有任何嘴型或口型動態。
6. 沒有任何跨對話持久保存的好感度/心情數值,角色的語氣不會隨關係進展而改變;角色也永遠只能被動回應,不會自己開口。

## Solution

在盡量保留現有已經驗證過、有測試保護的部分(Python 後端、TurnEngine 事件驅動的回合狀態機、「外部服務都包成介面卡」的架構、既有的角色卡與長期記憶摘要機制)的前提下,針對上述脆弱的部分重新設計:

- 用一個獨立、免費、快速的語音辨識步驟(Groq 的 Whisper)取代 `<heard>` 這種要求模型自己吐逐字稿的作法,讓語音輸入在進入回合邏輯之前就已經是純文字,音訊與文字回合因此收斂成同一條路徑,徹底移除這整類 bug 的根源。
- 讓並行/被取代的回合在架構上就是安全的(沿用票券 18 已經完成並測試過的世代計數器設計),並且讓「被新一輪取代」跟「內容真的聽不清楚」在計數上分開,不再讓成功的打斷誤觸發保護機制。
- 語音合成新增重試與備援層,單一片段合成失敗時,同引擎重試一次、再不行才切換備援引擎,而不是直接放棄整輪的聲音。
- 把呈現方式從方形 pywebview 視窗換成無邊框、透明背景、可拖曳的 Electron 外殼,身體從單張靜態圖片換成一小組可無縫循環的短片(待機+五種情緒各一支「說話中」),依情緒切換整段短片而不是逐幀合成嘴型,迴避「素材有頭部動態時,疊圖式嘴型永遠對不準」這個根本問題。
- 導入兩個可離線/自架的引擎(PrimeTTS 為主要語音、edge-tts 降為自動備援),降低雲端依賴。
- 延伸既有「隨處掃描文字標籤」的機制(而不是新增另一套解析邏輯),讓角色多一組跨對話持久保存的好感度/心情數值,語氣隨數值自然變化。
- 新增可開關的主動發言模式,完全沿用既有的回合機制運作。
- 回音消除的進階作法、工具呼叫、逐幀臉部追蹤等項目,這次先不做。

## User Stories

**語音輸入與回合統一**

1. As the app's owner, I want my spoken messages transcribed by a dedicated speech-to-text step before the character ever treats them as a conversation turn, so that a mistranscription or the model's own habits can no longer make a reply leak or read aloud a stray transcript tag.
2. As the app's owner, I want to see exactly what I said appear on screen before the character's reply starts appearing, every single time, so the conversation always reads in the order it actually happened.
3. As the app's owner, I want text-typed and voice-spoken turns to go through the exact same reply logic, so a bug fixed for one input mode is fixed for both.
4. As the app's owner, when speech recognition can't make out what I said, I want that turn to fail clearly and stop right there, rather than presenting a placeholder as though it heard me.

**打斷與並行安全**

5. As the app's owner, I want to interrupt the character mid-sentence and have it stop immediately and listen to my new message, so the conversation feels responsive.
6. As the app's owner, I want a successful interruption to never be counted as "the app couldn't understand me," so a run of normal interruptions doesn't wrongly disable continuous listening.
7. As the app's owner, I want a turn that gets superseded by a newer one to leave no trace in the conversation history, so an abandoned exchange never quietly influences future replies.
8. As the app's owner, when I interrupt the character while it is still "thinking" about my previous message, I want that older, unfinished reply to simply disappear rather than causing a visible glitch or a delayed answer to a stale message.

**語音合成韌性**

9. As the app's owner, when a fragment of the reply has nothing for the speech engine to actually say, I want the character to skip only that fragment's audio and keep speaking normally for the rest of the reply.
10. As the app's owner, when a sentence genuinely fails to produce audio, I want the app to retry it once and, if it's still silent, fall back to the other configured speech engine before giving up on audio for just that sentence.
11. As the app's owner, I want the character to speak primarily using a local, Taiwan-Mandarin-tuned voice, so it doesn't depend on my internet connection or a voice I have no control over.
12. As the app's owner, I want a cloud voice kept as an automatic backup, so a local-engine hiccup doesn't silence the character for an entire session.

**桌面呈現**

13. As the app's owner, I want the character to appear on my desktop as a free-floating figure with no window frame or background box, so it feels like an object sitting on my desktop rather than an app window.
14. As the app's owner, I want to click-and-drag the character to reposition it anywhere on my screen.
15. As the app's owner, I want to click through the transparent parts of the character's window onto whatever is behind it, so the character never blocks my other work.
16. As the app's owner, I want a way to reach settings/quit controls (e.g. a tray icon) even though the main window has no titlebar or menu.

**身體與嘴型**

17. As the app's owner, I want the character's body to visibly react to its current emotion, not just show one static photo the whole time.
18. As the app's owner, I want the character's body to look like it's talking while it's speaking, and return to an idle loop when it's not, without needing pixel-perfect lip synchronization.
19. As the app's owner, I want the switch between one mood's clip and another's to look reasonably smooth, especially when the emotion changes more than once within the same reply.
20. As the app's owner, I don't want the character's clips to visibly flicker between states if its emotion happens to change very quickly within a single reply.

**好感度與心情**

21. As the app's owner, I want the character to keep a persistent affection level that survives across sessions, so the relationship feels like it's progressing.
22. As the app's owner, I want the character's tone and intimacy to noticeably shift as affection changes, so the number isn't just cosmetic.
23. As the app's owner, I want the character's momentary mood to also be tracked and reflected in its tone within a session, separately from the longer-term affection level.
24. As the app's owner, I want affection to drift down slightly if I don't interact with the character for a long time, so the relationship doesn't feel static.

**主動發言**

25. As the app's owner, I want to turn on a mode where the character sometimes speaks first, unprompted, after I've been quiet for a while, so it feels more alive.
26. As the app's owner, I want to turn this mode off entirely if I don't want to be interrupted.
27. As the app's owner, if I start talking while a proactive message is being generated or spoken, I want that treated as an ordinary interruption, exactly like interrupting any other reply.
28. As the app's owner, I don't want the character to feel obligated to say something every time its timer goes off — it's fine for it to decide it has nothing to say and just wait for next time.

**視覺輸入**

29. As the app's owner, I want to attach an image to a message so the character can see and react to it.
30. As the app's owner, I do not want the character to have any way to see my screen or camera on its own; it should only ever see an image I deliberately attached.

**開發流程**

31. As the developer, I want this project's Python dependencies installed inside a virtual environment, not the system Python.
32. As the developer, I want the parts of this redesign that touch already-tested code (the turn engine, the speech-synthesis adapter boundary) to keep their existing automated tests passing throughout the migration.

## Implementation Decisions

### A. 語音輸入與回合統一(取代 `<heard>` 機制)

- 音訊訊息一律先送 Groq(Whisper large-v3-turbo)取得逐字稿,取得後才視為一般文字訊息,循現有文字回合的邏輯處理。TurnEngine 的公開介面收斂成只接受純文字,不再有音訊專屬的訊息型別。
- 因此整組 `<heard>` 相關機制(要求模型自己輸出逐字稿標籤、對應的解析狀態機、防禦性清除邏輯)在音訊路徑統一之後不再需要,予以移除。**這不是推翻票券 18**——那張票裡的世代計數器並行修正、結尾標點連續切句、edge-tts 空語音例外修正三項都不受影響、原封不動保留;只有跟 `<heard>` 直接相關的部分變成死碼,隨這次重構一併移除,詳見 Further Notes。
- 「使用者說了什麼」這個畫面回饋維持為對外行為契約——順序上一樣要在角色開始回覆之前先顯示——但產生方式改成:先呼叫 Groq 拿到逐字稿、確定文字後才呼叫 TurnEngine,而不是像現在這樣一邊等模型吐字一邊解析。這讓「使用者的話該先出現」這個先前的顯示順序問題在架構上直接消失。
- 若 Groq 完全辨識不出內容(空逐字稿或服務失敗),這一輪直接以失敗收場,不建立佔位訊息,不呼叫 TurnEngine。
- 此設計刻意放棄「模型直接聽音訊、能感知語氣」這個特性,以換取「逐字稿的產生與角色回覆邏輯完全脫鉤」的可靠度,這是本次規劃明確做出、已與使用者對齊的取捨。

### B. 打斷與並行安全(承接票券 18)

- 沿用票券 18 已完成並測試過的設計:每次送出訊息都會佔用一個新的世代;較舊、還在處理中的一輪一旦發現自己被取代,安靜結束,不寫入歷史、不影響新一輪的計時或語音狀態。
- 前端「被新一輪取代」與「內容真的含糊不清」分開計數:前者永遠不計入「聽不清楚」的累計次數,只有後者才會累計並觸發持續聆聽的保護機制。
- 因為 A 項已把音訊處理收斂成「先轉文字、再走文字回合」,世代機制作用的對象單純化成純文字回合,不需要再處理音訊專屬的中途狀態。

### C. 語音合成:PrimeTTS 為主、edge-tts 為備援

- 主要語音引擎改為本地執行的 PrimeTTS(zh-TW+英文、CPU、onnxruntime);edge-tts 保留,角色降為自動備援。
- 沿用票券 18 已完成的修正:合成介面若拋出「沒有可念內容」這一類例外,一律當成空結果處理,不視為整個語音服務故障。
- 新增重試/備援層:一句話合成結果為空,先在同一顆引擎重試一次;仍為空才切換到備援引擎;備援也失敗,才真正略過這句的語音(維持「文字仍照常顯示,只是這句沒有聲音」的行為,不中斷整輪)。
- PrimeTTS 目前只有單一內建女聲、8kHz 輸出,腔調/口音沒有可調參數。若正式導入後主觀聽感不滿意「台灣腔/機械感」這兩項需求,後續可另外評估語音克隆方案(如以一段真人台灣腔錄音當參考音色的方案),但屬於後續獨立評估項目,不在本次實作範圍。

### D. 桌面呈現:Electron 無邊框透明可拖曳外殼

> 本節「桌面上可拖曳的非視窗角色」概念參考自開源專案 **airi**(GitHub:moeru-ai/airi)。airi 本身用 Tauri 搭配 Live2D/VRM 虛擬形象,跟本專案這次決定的 Electron+真人短片路線在技術選型與素材路線上都不同,不是直接移植對象,僅借用其「桌面上可拖曳的獨立角色物件」這個呈現概念。

- 視窗設定:無邊框、透明背景、常駐最上層,搭配網頁內可拖曳區域取代標題列拖曳;非角色本體的透明區域要讓滑鼠事件穿透到桌面上被蓋住的其他視窗。
- 因為沒有標題列/選單,需要另外提供可觸及設定與結束程式的方式(如系統匣圖示的右鍵選單)。
- 現有以瀏覽器端音量閾值為基礎的持續聆聽/VAD 邏輯完全沿用,不因外殼從 pywebview 換成 Electron 而改變:`getUserMedia`/`AnalyserNode` 這類 Web API 跟視窗是否透明、無邊框、滑鼠穿透無關。唯一要處理的是 Electron 主行程要明確允許麥克風權限,以及確保可互動的介面元件(若有)不落在滑鼠穿透的遮罩範圍內。
- 回音消除維持現狀(仰賴瀏覽器內建的 echoCancellation 設定),不在本次規劃內加入額外的回音抵消引擎;理由見 Out of Scope。

### E. 身體與情緒素材:整段短片依狀態切換,不做逐幀嘴型合成

- 放棄在固定位置疊一張嘴型圖的做法(不論音素級或粗略的開合二態),因為角色影片素材(Veo 生成)預期會有頭部/鏡頭動態,疊圖式做法無法保證跟底下畫面對齊——嘴型狀態切得再細,只要底下的頭在動,對不準的根本問題都不會消失。
- 改為:每個狀態各自準備一支能無縫循環的短片,直接讓 Veo 在生成階段就把「說話中」的嘴部與頭部動作生成在同一段影片裡,不做任何後製對嘴。狀態集合:待機一支,加上現有五種情緒(neutral/happy/angry/sad/surprised)各一支「說話中」的短片,共六支循環短片。
- 切換時機:以既有逐句情緒事件為依據,句與句之間偵測到情緒改變就切換對應短片,而不是整輪只看一個主要情緒切一次一一因為系統已經有逐句情緒,身體不跟著換就是做半套。
- 為避免同一輪內情緒變化過密造成切換顯得雜亂,切換需要有最短停留時間的防抖動保護,精神上比照既有嘴型防閃爍的設計,套用對象換成整段短片的切換。
- 切換手感:用兩個疊放的影片元件做透明度交叉淡出(約 150–200 毫秒),不額外產生「過渡片段」素材(情緒兩兩過渡的組合數太大,不划算)。素材製作時建議讓每支短片的起訖姿態盡量接近,降低交叉淡出時的鬼影感,這是素材產製上的紀律,不是額外工程。
- 影片需要透明背景才能達到「角色本身站在桌面上」而非「一個方形色塊」的效果:Veo 生成階段盡量取得乾淨的純色背景以利後製去背;生成後統一走去背後製流程(乾淨純色背景可用色鍵去背,背景不夠乾淨則需要用影片去背模型逐幀處理)。最終輸出格式訂為帶 alpha 通道的 WebM(VP9 編碼、yuva420p 像素格式)——這是目前 Chromium/WebView2 能原生播放透明影片的標準做法,一般的 mp4/H.264 不具備這個能力,不適用。播放時影片元素本身的背景也要透明,跟視窗本身的透明設定疊加才是完整的「角色浮在桌面上」效果,兩者缺一不可。

### F. 好感度與心情數值(延伸既有標籤機制,不新增解析器)

- 沿用現有「隨處掃描 `[...]` 括號標籤」的機制——這個機制本身已經比逐字稿那種「開頭嚴格比對」的做法穩健很多,不會有「模型沒有從頭開始按格式輸出」就整段失敗的問題——新增兩種標籤:好感度增減量,以及當下心情。
- 好感度是跨對話持久保存的數值(建議範圍 0–100,越高分越難再往上加,呈漸進飽和曲線),存放在跟現有摘要/長期記憶同一份資料結構裡;心情是比較短期、會話內的狀態,可以每次對話重新評估,不必像好感度一樣長期保存。
- 每一輪最多套用一次好感度變化,即使模型在同一輪回覆裡多次輸出好感度標籤,也只取用一次,避免單輪暴衝。
- 好感度與心情的目前數值要寫回系統提示詞(延伸現有負責組裝這段文字的機制即可),讓模型的語氣/親密度自然受這段文字影響,不需要額外的規則邏輯去手動調整語氣。
- 好感度應該有隨時間緩慢向中性值衰減的機制,避免關係數值只漲不跌顯得不真實;衰減的觸發時機建議跟既有背景摘要工作共用排程,不必另開一個計時器。
- 實際的計算公式、衰減速率、以及影響語氣的具體規則,留給實作階段(/to-tickets、/tdd)時細部訂定,本規劃只確立機制的形狀。

### G. 長期記憶摘要改用結構化輸出

- 既有的定期背景摘要機制(把舊對話濃縮成摘要+事實清單,只送最近 N 輪原文給模型)本身保留,不重做;只是這個呼叫產生 JSON 的方式,從現在手動找大括號邊界的克難解析法,換成模型 API 層真正支援的結構化輸出(明確定義摘要+事實清單的 schema)。
- 這個呼叫本來就不是即時串流的低延遲路徑,換成結構化輸出沒有「串流 JSON 解析」的顧慮(見 Further Notes 對這個備選方案的討論),是低風險、高確定性的改善。
- 不新增人類可讀的 `memory.md` 快照檔——評估過後認為現有存放方式已經足夠,額外維護一份快照只是重複的檔案 I/O 負擔,沒有對應到明確的需求。

### H. 角色卡

- 角色卡(性格設定的 md 檔)延用現有做法,不需要新的機制或格式。

### I. 主動發言模式

- 新增一個可由使用者開關的「主動發言」設定;開啟時,在雙方都閒置超過一段隨機時間後,由背景排程觸發一則系統驅動的訊息,循跟一般使用者訊息完全相同的回覆路徑生成並播出。
- 系統提示詞要讓模型知道這是自己主動開口,不是使用者觸發的,並允許模型判斷「這次沒有特別想講的話」就不輸出、直接等下一次時機,避免每次計時器到都硬講話。
- 若使用者在主動發言生成或播放中開口,視為一般的打斷情境處理,套用 B 項的世代機制,不需要另外設計一套邏輯。
- 關閉開關後,不應該有任何背景排程繼續嘗試觸發。

### J. 視覺輸入

- 使用者可以在訊息中手動附加一張圖片,讓角色針對圖片內容回應。
- 角色不具備任何形式的螢幕擷取或攝影機存取能力;所有視覺輸入都必須是使用者主動附加的圖片。因為完全不做背景式的螢幕觀察,先前討論過的「螢幕內容改用第二組帳號分流」這個安全邊界設計目前沒有對應的需求,不需要實作;若未來真的要做背景視覺觀察功能,屆時再重新評估帳號分流的必要性。

### K. 開發環境

- 這次重構開始的開發工作,Python 相依套件一律安裝在虛擬環境(venv)裡,不安裝在系統預設的 Python 環境。

## Testing Decisions

- 好的測試只驗證外部可觀察的行為,不綁實作細節——延續本專案既有的慣例:外部服務(LLM、STT、TTS)一律包成介面卡,測試時用假的介面卡替身頂替,只在最外緣(介面卡本身)測「這個介面卡真的照文件行為做事」,核心邏輯(TurnEngine)完全不碰真正的網路服務。
- 預期需要測試覆蓋的模組:
  - **TurnEngine**(公開介面收斂成純文字後更單純):延用既有的測試接縫與既有的假物件,驗證回合取代/安靜放棄的行為、好感度/心情標籤的解析與「每輪最多套用一次」的上限、標籤解析跟既有分句邏輯的互動。
  - **Groq STT 介面卡**:比照現有 `EdgeTTS`/Gemini LLM 介面卡的做法,一個薄的介面卡類別,測試時用假的網路呼叫替身頂替。
  - **語音合成重試/備援層**:在 TurnEngine 的測試接縫內驗證,用假的 TTS 替身模擬「主要引擎回傳空結果、備援引擎回傳有效音訊」等情境,延續現有測試裡已經在用的「空語音合成」測試案例精神。
  - **記憶摘要的結構化輸出呼叫**:比照現有摘要測試的做法,只是斷言的對象換成新 schema 解析出來的結果,而不是舊的手動大括號解析。
- 前端部分:任何新增的純邏輯(例如短片切換的最短停留時間防抖動,精神上比照既有嘴型防閃爍的做法)應該抽成純函式並用 node:test 覆蓋,延續 VAD 門檻測試已經立下的先例;其餘短片切換的畫面串接、Electron 主行程視窗設定、拖曳/滑鼠穿透行為,預期維持人工驗收,不強行寫自動測試,這跟本專案目前對待前端膠水碼的一貫做法一致。
- 明確不自動化的項目:任何需要真正呼叫 Groq/PrimeTTS/edge-tts/Gemini 網路服務的情境(比照既有 smoke script 的做法用人工跑一次驗證)、影片轉場與透明背景的視覺正確性(用眼睛判斷)、Electron 作業系統層級的視窗行為。

## Out of Scope

- 工具呼叫(tool calling)。
- 進階回音消除(如參考訊號抵消的 AEC 引擎)。先前「持續聆聽誤判聽不清楚」的現象有很大成分其實是 `<heard>` 解析壞掉跟誤算次數造成的,不是真的回音問題;決定先讓 A、B 項上線並重新實測,真的還有明顯殘留回音再另外評估。
- 逐幀嘴型合成/臉部追蹤(如以聲學分析驅動嘴型時間軸、或以臉部關鍵點追蹤驅動疊圖)。已經決定改走整段短片切換,除非之後發現「說話中」整段短片的效果不夠好,才重新評估。
- 背景螢幕擷取/攝影機視覺輸入,以及對應的第二組帳號分流機制。
- 用語音克隆(如以真人錄音當參考音色的方案)取代 PrimeTTS 的預設聲音,列為後續獨立評估項目。
- 人類可讀的 `memory.md` 快照檔。
- Discord/Telegram 等外部聊天平台整合。
- 多 LLM 供應商切換。

## Further Notes

- 票券 18(使用者實測持續聆聽時回報的五個 bug)已經完成並通過測試。其中三項在這次重構後原封不動保留,並且是這次規劃的基礎:並行回合的世代計數器設計(對應本次 B 項)、結尾標點連續出現時視為同一句尾的分句修正(不受這次規劃影響)、edge-tts 對「沒有可念內容」例外的處理修正(對應本次 C 項的基礎)。另一項——為了不讓 `<heard>` 標籤外洩而新增的防禦性清除邏輯,以及 `<heard>` 機制本身——會隨著本次 A 項的決定變成死碼。**執行 /to-tickets 時建議安排一張票專門移除這些不再需要的程式碼與對應測試**,避免留下沒人維護的殭屍邏輯。
- 這次規劃過程中考慮過、但最後沒有採用的方案,列在這裡以免之後重複討論同樣的權衡:
  1. **音訊直送 Gemini、同時保留 Groq 逐字稿的混合路線**(為了保留模型對語氣的感知)——為了架構單純、降低整體 bug 面而放棄,改成音訊一律先轉文字再走統一路徑。
  2. **Tauri 作為桌面殼**——功能上做得到跟 Electron 一樣的透明/無邊框/可拖曳效果,但 Electron 在「桌寵式點擊穿透+可拖曳」這個特定情境的既有範例更成熟,且完全不需要碰 Rust,最後選 Electron。
  3. **逐幀嘴型疊圖**(不論音素級的時間軸驅動或簡單的開合二態)——因為角色短片預期有頭部動態,疊圖對不準的問題兩者都無法解決,改採整段短片切換。
  4. **即時對話回覆改用結構化輸出**——技術上可行,但串流出來的是 JSON 文字本身而非欄位,要保留現有「第一句講完就先開始念」的低延遲設計,得自己寫一個容忍 JSON 未收完整的解析器,投入產出比不如維持現有標籤式做法;只在低延遲要求不高的記憶摘要呼叫上採用結構化輸出。
  5. **先做進階回音消除**——判斷先前的「持續聆聽誤判聽不清楚」有很大成分是 `<heard>` 解析壞掉跟誤算次數造成的假象,不是真的回音問題,決定先讓 A、B 項上線重新實測,真的還有明顯殘留回音再處理。
  6. **Kokoro 作為 TTS 選項**——官方自己的語音品質分級表把中文評為所有語言中最低的等第,且聲音的口音風格也不是台灣腔,評估後直接排除,沒有進一步採用。
