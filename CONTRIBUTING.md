# 貢獻指南

謝謝你願意幫忙。這份文件說明怎麼把開發環境架起來、怎麼跑每一種測試、改了什麼東西要多做什麼檢查,以及相依套件與 Electron 版本的維護方式。

> 撰寫日期:2026-11-03。下面每一個指令都實際執行過才寫進來;**請照原樣使用**,尤其是引號。

## 開發環境

需要 Python 3.11 或更新、Node.js 22.12 或更新(安裝 Electron 與跑前端測試都需要)。安裝桌寵視窗(Electron)的方法見 [安裝教學](docs/install.md)。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install pytest pip-audit vulture
```

`pytest`、`pip-audit`、`vulture` 是開發工具,不在 `requirements.txt` 裡(使用者不需要它們)。

## 測試

### Python 測試(日常最常跑)

```powershell
.venv\Scripts\python -m pytest tests
```

不需要任何金鑰,也不會呼叫真實的服務:對話模型、語音辨識、語音合成都用離線替身。

### 前端(Node)測試

```powershell
node --test "tests_js/*.test.js"
```

- **一定要用萬用字元指定檔案,而且整個加上雙引號。** 只給資料夾(`node --test tests_js`)會失敗,Node 會說 `Cannot find module`。
- 加引號是為了讓 **Node 自己展開**萬用字元:Windows PowerShell 不會替原生程式展開 `*`。這個寫法需要 **Node 22** 或更新;Node 20 的 `--test` 只接受實際的路徑,不認萬用字元。

### 真實 Electron 的頁面情境(`tests_electron/`)

這些是**非自動測試**:用真實的 Electron 視窗驗證穿透、系統匣、語音插話等頁面層行為,需要 Linux 的虛擬螢幕(Xvfb)、視窗管理員(openbox)與 `xdotool`,不能在 Windows 上直接跑。用法、環境變數,以及**沙盒驗證不到的東西**(真實麥克風與喇叭、真實的回音消除、真實的語音辨識)都寫在 `tests_electron/README.md`,請先讀它。

### 靜態檢查與文件檢查

`tests/test_repo_static_checks.py` 掃描整個倉庫:

- **用詞不預設角色的性別**:送給模型或顯示給使用者的文字、範例人設與所有文件都受檢查(註解與 docstring 不在範圍)。例外必須寫進白名單**並附理由**,沒有理由的白名單項目會讓測試失敗。
- **已移除的功能不得殘留**:用精確字串比對,不會掃 `edge`、`pet` 這種到處都有的單字。

文件也有測試:`tests/test_docs_config_examples.py` 讓設定參考與程式裡真正的預設值、旗標、環境變數一致;`tests/test_readme.py`、`tests/test_readme_en.py`、`tests/test_install_guide.py`、`tests/test_troubleshooting.py`、`tests/test_animation_tutorial.py` 讓各份文件與程式實際的行為一致。**改了程式,對應的文件測試會告訴你哪份文件要跟著改。**

## 改了送給模型的文字:提示詞回歸

只要改了送給模型的文字(系統提示、標籤說明、狀態區塊、記憶摺疊提示),請在**改動前**和**改動後**各跑一次:

```powershell
.venv\Scripts\python smoke_state.py
```

- 需要**真實的 Gemini 金鑰**(見 [安裝教學](docs/install.md));免費額度緊的時候可以加 `--pause 8` 拉長呼叫間隔。
- 兩個數字都要 **≥ 90%**:「該宣告時有宣告」與「不該宣告時沒亂宣告」。
- 429 或網關錯誤造成的空白回答**不計分**,會自動重試;報告出現「⚠ API 錯誤」時,等一下再重跑,不要拿它當結果。
- 在提交說明或 PR 描述裡貼上改動前與改動後兩次的完整輸出。通過率下降時,先停下來討論,不要硬調提示詞去追分數。

## 突變測試腳本

想確認某個測試真的守得住某個行為,故意弄壞一個地方,看測試會不會變紅:

- `tools/pymut.sh`:針對 Python 程式。用法寫在檔案開頭的說明。結果 `KILLED` 表示至少一個測試變紅(好),`SURVIVED` 表示測試沒發現這個錯誤(請補測試)。**`KILLED` 要確認是為你想的那個原因而紅。**
- `tools/pmut.sh`:針對頁面(`static/index.html`),使用上面的真實 Electron 情境,環境需求相同。

兩者都是 bash 腳本(Linux、WSL 或 Git Bash)。它們會在跑完後還原被改的檔案,但**執行前請先提交你的工作**。

## 相依套件稽核

```powershell
.venv\Scripts\pip-audit -r requirements.txt
cd electron
npm audit
cd ..
```

- 前者檢查 Python 套件,後者檢查 `electron\` 的 npm 套件(主要是 Electron 本身)。**發佈前與每個月至少各跑一次**,結果貼在 PR 或議題裡。
- `requirements.txt` 目前**沒有固定版本**,所以 `pip-audit` 檢查的是「現在安裝會裝到的最新版」。
- `npm audit` 對釘住的 Electron 版本列出通報時,見下一節。

## Electron 升版政策

**為什麼要管:** Electron 內含一整個瀏覽器引擎(Chromium)。Electron 官方只支援**最新三個**穩定主版本,而且大約每 **8 週**就出一個新的主版本(跟著 Chromium 的節奏),所以任何一個被釘住的主版本,大約半年後就會落到支援範圍之外,不再有安全修補。專案把 Electron 釘在確切版本是為了讓行為可重現,代價是**升版必須由人刻意去做**。

**現況:** 目前釘在 **45.2.2**。依 endoflife.date(2026-11-04 查詢),45 的官方支援到 **2027-04-27**;`npm audit` 沒有通報。這個日期一定會到,所以**要在它之前升版**,不要等到過期。

**多久檢查:** 每個月看一次 Electron 官方的發佈時程(<https://releases.electronjs.org/schedule>)與 `npm audit`。釘住的主版本離終止支援不到兩個月、或 `npm audit` 出現 high 以上的通報,就開升版 PR。Dependabot(`.github/dependabot.yml`)也會替 Electron 開 PR;**它會讓 `tests/test_electron_pin.py` 失敗,這是刻意的**:升版不只是改一個數字。

**升版 PR 一定要做的事:**

1. 把 `electron/package.json` 與 `electron/package-lock.json` 根節點改成**同一個精確版本**(`npm install --save-exact --ignore-scripts electron@<版本>`),再用 `npm ci` 確認鎖檔自洽。
2. 改 `tests/test_electron_pin.py` 裡的 `EXPECTED`。
3. 更新 `docs/install.md` 的版本號、壓縮檔名、檔案大小與 **SHA-256**(取自套件內的 `checksums.json`,並和官方 release 的 `SHASUMS256.txt` 交叉核對;測試會比對),以及 `docs/troubleshooting.md` 裡同樣的版本與檔名。
4. **重新確認安裝行為有沒有變。** 不同主版本的安裝方式不一樣(例如 Electron 42 起,`npm install` 不再下載執行檔,所以 `electron/package.json` 用 `postinstall` 呼叫套件的 `install-electron`,好讓安裝仍是一行指令;套件要求的 Node 版本也會變)。比對新版套件的 `scripts`、`engines`、`index.js` 與 `install.js`,必要時調整 `electron/package.json`,並重新實測 `docs/install.md` 的三條路線與 `docs/troubleshooting.md` 引用的第三方錯誤訊息(測試會拿它們對照已安裝的套件)。Node 需求若變了,README、英文 README 與安裝教學要一起改(測試會比對)。
5. 讀該版本的重大變更(breaking changes),檢查 `electron/main.js` 與 `electron/preload.js`。
6. 跑 Python 測試、Node 測試與 `tests_electron/` 的情境(例如 `s43`、`s57`)。
7. 在 Windows 上人工驗收:單視窗啟動、退出鈕、穿透、系統匣、麥克風,以及手動下載流程。
8. 更新 `SECURITY.md` 的「已知風險」與 `CHANGELOG.md`。

## 提交

- 先寫測試再改程式;測試只驗證外部可觀察的行為,不綁實作細節。
- 文件裡**不要寫測試數量**,也不要把金鑰、`config.json`、`persona.md`、`data\` 的內容放進提交(它們已經被 `.gitignore` 擋住,請不要用 `-f` 強制加入)。
- 一個提交做一件事,提交說明寫清楚為什麼。

## 回報問題

一般問題請開 GitHub issue,附上 `data\app.log` 最下面的幾行(**先拿掉金鑰與私人對話**)。**安全問題請不要開公開的 issue**,依 `SECURITY.md` 的方式回報。
