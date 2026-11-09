# 安裝教學

從一個空的 Windows 10 / 11 電腦,到跟角色講第一句話。看完這份就夠了;每個設定的細節在 [設定參考](configuration.md),出狀況請看 [疑難排解](troubleshooting.md)。

> 撰寫日期:2026-11-04,對應 Electron 45.2.2。第三方網站(Google AI Studio、Groq、GitHub 等)的畫面與流程可能改版,以它們的官方說明為準。
>
> 本文會標示每個步驟有沒有被專案維護者在 Windows 上實際走過:**實測**表示走過並確認可行,**尚未實測**表示依官方文件撰寫、還沒有人在真實環境走過。沒有標示的一般步驟(安裝 Python、建立虛擬環境等)是標準做法。

## 1. 需要準備

| 項目 | 說明 |
|---|---|
| Windows 10 或 11 | 僅支援這個平台 |
| Python 3.11 或更新 | <https://www.python.org/downloads/> |
| Node.js 22.12 或更新 | <https://nodejs.org>。只用來**安裝**桌寵視窗(Electron),裝好之後平常啟動不再需要 |
| Gemini API 金鑰 | 免費,見第 5 節 |
| 網路 | Gemini 與語音都需要連網 |
| 麥克風 + Groq 金鑰 | 只有想用語音輸入才需要 |

## 2. 取得專案

把專案放在一個固定的資料夾,例如 `D:\ai-friend\companion`。**路徑最好不要有中文或空格**:這是為了排除變數,不是硬性限制;如果你的路徑有中文而且能正常啟動也沒問題,但出了怪問題時請先從這點查起。

之後的指令都在專案資料夾裡用 PowerShell 執行(在資料夾空白處按住 Shift 再按右鍵,選「在此處開啟 PowerShell 視窗」,或在檔案總管網址列輸入 `powershell` 按 Enter)。

## 3. 安裝 Python 與套件

1. 到 <https://www.python.org/downloads/> 下載 Windows 安裝檔。安裝時**務必勾選「Add python.exe to PATH」**。
2. 確認安裝成功:

   ```powershell
   python --version
   ```

   看到 `Python 3.11.x`(或更新)即可。顯示找不到 python 時,把指令換成 `py -3` 試試。

3. 建立虛擬環境,並把套件裝進去(**不會動到系統的 Python**):

   ```powershell
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```

之後所有 Python 指令都用 `.venv\Scripts\python`,`run.bat` 也是用這個環境,所以不需要另外「啟用」虛擬環境。

## 4. 安裝桌寵視窗(Electron)

桌寵視窗由 Electron 提供,只要安裝一次。先安裝 Node.js(<https://nodejs.org>,**22.12 或更新**;Electron 45 的 npm 套件就要求這個版本),再進入 `electron` 資料夾安裝。**專案把 Electron 固定在 45.2.2**;`npm install` 的最後一步會下載一個約 150 MB 的執行檔(`electron-v45.2.2-win32-x64.zip`),從 GitHub 的官方 release 取得,**這一步在某些網路環境下會非常慢**。

下面有三條路,結果相同,擇一即可:

| 路線 | 適合 | 狀態 |
|---|---|---|
| A. 預設 | 網路到 GitHub 夠快 | 最省事;維護者所在的網路下載**非常慢**(實測) |
| B. 鏡像站 | 你有信任的下載鏡像 | **尚未實測** |
| C. 手動下載 | 預設太慢、也不想用鏡像 | 實測(下載、核對雜湊、解壓縮、`path.txt`);其中「略過下載」一步用的是 `npm install --ignore-scripts`,已在 Linux 驗證,尚待 Windows 確認 |

> 註:`npm install` 還會從 npm 的套件庫抓十幾個小套件,那一段通常很快;慢的是 Electron 執行檔那一包,它不是從 npm 抓,而是從 GitHub。所以設定 npm registry 鏡像**幫不到**這個問題。

### 路線 A:預設

```powershell
cd electron
npm install
cd ..
```

### 路線 B:鏡像站(尚未實測)

Electron 的下載網址是「鏡像位址 + `v45.2.2/` + 檔名」,用環境變數 `ELECTRON_MIRROR` 換掉預設的 GitHub 位址(**結尾要有 `/`**)。鏡像站要和官方用同樣的資料夾結構。請自己挑一個你信任的來源,下面的位址只是格式示意:

PowerShell:

```powershell
cd electron
$env:ELECTRON_MIRROR = "https://你信任的鏡像站/electron/"
npm install
Remove-Item Env:ELECTRON_MIRROR
cd ..
```

cmd(命令提示字元):

```bat
cd electron
set ELECTRON_MIRROR=https://你信任的鏡像站/electron/
npm install
set ELECTRON_MIRROR=
cd ..
```

也可以改成永久設定:在 `electron` 資料夾放一個 `.npmrc`,內容一行 `electron_mirror=https://你信任的鏡像站/electron/`。

**關於安全:** Electron 套件自己帶了每個下載檔的 SHA-256(在套件內的 `checksums.json`),安裝程式會用它檢查下載的檔案。所以就算來源是鏡像站,檔案若和官方的不同,安裝會失敗而不是悄悄裝上去。

### 路線 C:手動下載(實測)

做法是:先讓 `npm install` **略過**執行檔下載,自己用你偏好的方式把壓縮檔下載下來,**核對雜湊**之後解壓縮到正確位置。

**C1. 安裝套件,但略過執行檔下載**

PowerShell 與 cmd 的指令相同:

```powershell
cd electron
npm install --ignore-scripts
```

`--ignore-scripts` 是 npm 的標準旗標:不執行任何安裝腳本,其中也包括專案那個「下載 Electron 執行檔」的步驟(它是 `electron\package.json` 裡的 `postinstall`)。不需要設定任何環境變數。

**C2. 下載壓縮檔**

用瀏覽器打開官方 release 頁面 <https://github.com/electron/electron/releases/tag/v45.2.2>,在 Assets 裡找 **`electron-v45.2.2-win32-x64.zip`**(要 `win32-x64`;不是 `ia32`、`arm64`,也不是 `ffmpeg`、`chromedriver`、`mksnapshot`、`symbols`、`toolchain-profile` 這些)。直接網址是:

```
https://github.com/electron/electron/releases/download/v45.2.2/electron-v45.2.2-win32-x64.zip
```

用瀏覽器、下載管理員或任何你信任的方式下載都可以,檔案存在專案資料夾裡的 `electron` 就好(下面的指令假設檔案在那裡)。

**C3. 核對完整性(強烈建議)**

這個檔案的 SHA-256 應該是:

```
a234388419ccbcb18dd2feec856e4ae1832499e200837f23f8e653bd51ff3be5
```

這個值和 Electron 官方 release 的 `SHASUMS256.txt`、以及你剛裝好的套件裡的 `checksums.json` 一致(2026-11-04 核對)。**請以你自己機器上的 `checksums.json` 為準**,用下面的指令比對,輸出 `True` 就代表下載完整、沒被改過:

```powershell
$want = (Get-Content node_modules\electron\checksums.json | ConvertFrom-Json).'electron-v45.2.2-win32-x64.zip'
(Get-FileHash .\electron-v45.2.2-win32-x64.zip -Algorithm SHA256).Hash -eq $want
```

**C4. 解壓縮到 `dist`,並寫入 `path.txt`**

```powershell
Expand-Archive -Path .\electron-v45.2.2-win32-x64.zip -DestinationPath node_modules\electron\dist
Set-Content -Path node_modules\electron\path.txt -Value "electron.exe" -NoNewline
cd ..
```

兩個容易出錯的地方:

- 解壓縮之後,`electron.exe` 必須**直接**在 `node_modules\electron\dist\` 底下。如果你用檔案總管的「解壓縮到 `electron-v45.2.2-win32-x64\`」,就會多一層資料夾,請把裡面的東西移上來。
- `path.txt` 的內容只有 `electron.exe` 這一行字,**結尾不能有換行**。Electron 套件會把它當成「還沒裝好」,之後的 `npm install` 甚至會重新下載一次。用上面的 `Set-Content ... -NoNewline` 寫入最保險;用記事本手寫的話,打完字不要按 Enter。

放好之後,再執行一般的 `npm install` 也不會重複下載:Electron 套件看到 `dist` 與 `path.txt` 都在,就會當成已經安裝。

### 確認 Electron 裝好了

不論走哪一條路,在專案資料夾執行:

```powershell
Test-Path electron\node_modules\electron\dist\electron.exe
Get-Content electron\node_modules\electron\path.txt
```

第一行應該印出 `True`,第二行應該印出 `electron.exe`。不要用 `require` 去問 Electron 套件來確認:它在找不到執行檔時會開始下載,而不是回報錯誤。

## 5. 取得並設定金鑰

### Gemini 金鑰(必要)

1. 打開 Google AI Studio 的 API 金鑰頁面:<https://aistudio.google.com/apikey>。
2. 用 Google 帳號登入,建立一把 API 金鑰,複製起來。使用免費額度即可。
3. 存進 Windows 憑證管理員(**推薦,一次設定永久有效**):

   ```powershell
   .venv\Scripts\python app.py --set-key
   ```

   會跳出一個視窗,貼上金鑰按確定。

不想存進憑證管理員的話,也可以設成環境變數 `GEMINI_API_KEY`:永久設定用 `setx GEMINI_API_KEY "你的金鑰"`(設完要**關閉並重開** PowerShell 才生效),只在目前視窗暫時有效用 `$env:GEMINI_API_KEY = "你的金鑰"`。同時設了兩者時,**環境變數優先**。金鑰不要貼到聊天室、截圖或上傳到網路。

### Groq 金鑰(只有要用語音輸入才需要)

到 <https://console.groq.com/keys> 申請,然後:

```powershell
.venv\Scripts\python app.py --set-key-groq
```

(環境變數是 `GROQ_API_KEY`。)沒有這把金鑰,程式照常運作,只是沒有麥克風,仍然可以打字。

### 其他選用金鑰

Fish Audio(另一種語音)、Cloudflare(照片)、TinyFish(上網查資料)的金鑰都是選用的,沒有金鑰時對應功能自動停用,程式照常啟動(面板會提示一次)。

- **Fish Audio:** 到 <https://fish.audio/app/api-keys> 申請(以 Fish Audio 官網為準),存放用 `.venv\Scripts\python app.py --set-key-fish`。它的免費模型是 Fair Use、沒有 SLA 也不保證延遲,請求可能被用來改進模型,不要拿來講敏感內容。要用它還需要把 `tts.engine` 明確設成 `"fish"`。
- **Cloudflare(照片):** 在 Cloudflare 建立有 Workers AI 權限的 API Token,存放用 `--set-key-cloudflare`;還需要帳號 ID(`image.account_id` 或環境變數 `CF_ACCOUNT_ID`)。
- **TinyFish(上網查資料):** 在 TinyFish 的官方網站申請,存放用 `--set-key-tinyfish`。

存放方式、環境變數與啟用步驟都在 [設定參考](configuration.md) 的第 3 節與各功能的段落。

## 6. 建立你的角色

人設檔是你自己的檔案(不會被 git 追蹤)。先複製範例,再用記事本改成你想要的角色:

```powershell
copy persona.example.md persona.md
notepad persona.md
```

範例檔下半部有「寫人設的說明」,改完請把分隔線以下那一整段刪掉(整個檔案都會被送給模型)。角色的名字、性別、代名詞、個性與口吻都寫在這裡,程式不預設任何一種。

## 7. 驗證(照順序做,先確認每一段都通)

請在專案資料夾執行。`smoke_gemini.py` 會讀取同資料夾的 `persona.md`,所以要先完成第 6 節。

### 7.1 驗證 Gemini

```powershell
.venv\Scripts\python smoke_gemini.py "嗨,你今天好嗎?"
```

成功的樣子:依序印出情緒、每一句文字,最後一行是**首句延遲**(通常 1 到 2 秒內)。

### 7.2 驗證語音輸出

```powershell
.venv\Scripts\python smoke_tts.py
```

成功的樣子:印出合成耗時,並產生 `hello.mp3`。雙擊播放,聽到中文語音即成功。預設聲音是女聲,想換成男聲見 [設定參考](configuration.md) 的「角色的聲音是女聲還是男聲」。

### 7.3 啟動完整程式

雙擊 `run.bat`。它會先檢查安裝是否完整,然後開出桌寵視窗:畫面上只有角色(還沒放動畫時是表情符號),右下角有一顆小小的半透明 ⚙。點 ⚙ 展開工具列,再點 💬 打開對話面板,跟角色打字聊幾句。每則回覆的下方會顯示:

- **首句**:第一句文字出現的時間。
- **首音**:第一段聲音開始播放的時間,是你實際感受到的等待,通常 2 到 3 秒。

**要離開:** 工具列最上方的退出鈕,按一次變紅、再按一次結束;或在系統匣圖示按右鍵 →「結束程式」。

啟動出了問題想看輸出,改雙擊 `run-debug.bat`(它會保留命令列視窗);記錄檔在 `data\app.log`。

### 7.4 驗證麥克風(要用語音輸入才做)

需要先完成第 5 節的 Groq 金鑰。在桌寵視窗:打開對話面板,**按住**「🎤 按住說話」(或按住鍵盤 F2),說一句話,放開。畫面上會先顯示逐字稿(你說的話),再顯示角色的回覆。逐字稿和你說的一致,就代表麥克風和語音辨識都正常。

桌寵視窗會直接使用麥克風,不會再跳出詢問權限的視窗。沒有反應的話,請看 [疑難排解](troubleshooting.md)。

沒有錄音可以按的環境(例如要驗證辨識本身),也可以用 `smoke_stt.py` 對任何一個錄音檔(`.webm`、`.wav`、`.mp3`、`.m4a`、`.ogg`、`.flac`)做辨識測試:

```powershell
.venv\Scripts\python smoke_stt.py 你的錄音檔.wav
```

## 8. 接下來

- 讓角色動起來、換裝:[動畫製作教學](animation-tutorial.md)
- 調整語音、記憶、時間觀念、照片等:[設定參考](configuration.md)
- 遇到問題:[疑難排解](troubleshooting.md)
