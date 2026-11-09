# 動畫製作教學

專案**不附任何角色**:角色的樣子與動畫都由你自己做。這份教學帶你從零做出一套服裝的全身動畫,並放進程式裡。還沒有動畫也能先用,角色會以表情符號代替,隨時可以回來補。

> 撰寫日期:2026-10 至 2026-11。第三方服務(ChatGPT、Google Vids)的選單、額度與規則常改版,下面「步驟」裡的畫面操作是作者當時的做法,請以服務目前的樣子為準。**任何「圖片轉影片」的工具都可以用**,只要能做到:指定第一格畫面、直式 9:16、鏡頭固定、背景是單一純色。

## 先看全貌

```
① 做一張純綠背景的全身底圖  →  ② 裁成 9:16  →  ③ 圖片轉影片(待機等動作)
   →  ④ 去背並做成無縫循環(make-clip.bat)  →  ⑤ 放進 clips\<服裝名>\
```

一套服裝至少要有 `idle.webm`(待機)才算數;其他動作可以慢慢補。做完的影片放在 `clips\<服裝名>\`,對角色說「換成睡衣」就會換上 `clips\睡衣\` 那一套。

## 角色的動畫是怎麼被程式找到的

### 資料夾與檔名

```
clips\
  日常\
    idle.webm
    thinking.webm
    talking-happy.webm
    base.png         ← 選用,自拍用的基底照(見後面「自拍用的基底照」)
    outfit.txt       ← 選用,一行英文外觀描述
  睡衣\
    idle.webm
    ...
```

- `clips\` 底下**每個子資料夾是一套服裝**,資料夾名稱就是服裝名稱。
- 每套服裝裡,**檔名 = 狀態名稱**,副檔名是 `.webm` 或 `.mp4`(兩者都有時用 `.webm`)。
- 直接放在 `clips\` 這一層的影片**不會被使用**,請放進服裝資料夾。

| 檔名 | 什麼時候播 |
|---|---|
| `idle.webm` | 待機(循環)。**必要**:沒有它的資料夾不會被當成服裝 |
| `thinking.webm` | 你送出訊息、角色在想的時候(循環) |
| `listening.webm` | 你按住說話的時候(可省略) |
| `talking-neutral.webm` | 說話,平靜 |
| `talking-happy.webm` | 說話,開心 |
| `talking-sad.webm` | 說話,難過 |
| `talking-angry.webm` | 說話,生氣 |
| `talking-surprised.webm` | 說話,驚訝 |

**缺哪個就自動退回:** 任何缺少的 `talking-*` 片段會退回 `talking-neutral`,再退回 `idle`;缺少 `thinking` 或 `listening` 則直接退回 `idle`。最後都沒有時用表情符號代替。退回只會發生在**同一套服裝**裡,不會借用別套服裝的影片。所有片段都請做成可以**無縫循環**。

### 其他規則

- 資料夾名稱以**底線**開頭(例如 `_草稿`)的會被忽略,可以拿來放做到一半的東西。
- 預設穿哪一套:`config.json` 的 `outfit.default`(預設 `日常`);找不到就用名稱排序第一套。換過衣服之後,重新啟動仍是上次穿的那套。
- 說「睡袍」也算睡衣之類的別名,在 `config.json` 的 `outfit.aliases` 設定,見 [設定參考](configuration.md)。
- 角色的畫面寬度中只有**正中間約 60%** 會接收滑鼠(可用 `ui.hit_width_ratio` 調整),人物最好在這個範圍內。

## 準備(只做一次)

1. 安裝 ffmpeg。開 PowerShell,執行 `winget install Gyan.FFmpeg`,裝完**關掉重開**視窗,輸入 `ffmpeg -version`,看到版本號就成功。
2. 工具在專案的 `animation-tools\` 資料夾:
   - `make-clip.bat`:把影片**去背**並做成**無縫循環**,輸出到 `clips\<服裝名>\`。
   - `crop-916.bat`:把圖片裁成 9:16。
3. 確認你用的影片生成服務這個月還剩多少生成次數。

## 步驟 1:做一張純綠背景的全身底圖

在你的圖片生成工具開一個新對話(**之後所有表情圖都要在同一個對話裡做**,角色才會一致),貼上下面的 prompt,把 `[ ]` 裡換成你想要的角色:

```
Create a photorealistic full-body photograph of [角色描述,例如:a 25-year-old person with short dark hair, friendly expression, wearing a casual hoodie and jeans],
head to toe with both feet visible, standing relaxed facing the camera, neutral expression, mouth closed,
arms hanging naturally at the sides, legs together. Vertical frame, the character centered and filling the height with a small margin above the head and below the feet; the body is narrow, taking up about 35% of the frame width.
Background: one flat, solid pure green (#00FF00) only. No gradient, no floor, no ground shadow, no reflection,
no vignette, no green light or rim light on the character. No green anywhere on the character.
```

角色的性別、年齡、風格都由你在 `[ ]` 裡決定。想要**真人照片風格**就保留 `photorealistic` 與 `photograph`;想要插畫或動漫風格,把它們換成你要的風格即可。生成之後檢查:

- 背景是一整片純綠,沒有漸層、地板、陰影。
- 角色身上沒有綠色,邊緣沒有綠色反光。
- 從頭到腳完整入鏡,雙手自然下垂,人物在畫面正中間,左右留有空白。
- 腳底沒有地板或陰影(有陰影,去背會留下髒影子)。

不滿意就在同一個對話說明問題,請它重畫。滿意後下載,存成 `green-base.png`。

> 注意:這張 `green-base.png` 只是**做動畫用的工作檔**(綠背景)。它和後面「自拍用的基底照」`base.png` 不是同一個東西,不要放在一起。

## 步驟 2:把底圖裁成 9:16

動畫是直式 9:16,大多數圖片轉影片的工具也只接受 9:16;比例不對會補黑邊,黑邊不是綠色,去不掉。常見的圖片生成預設是 2:3,所以要裁掉左右兩側(全身站姿的左右本來就是空白,不會裁到人)。

- 看圖片尺寸:高 ÷ 寬 ≈ 1.78 就已經是 9:16,直接做步驟 3。
- 否則:把圖片**拖到 `animation-tools\crop-916.bat` 上**。它會在原圖旁邊產生 `檔名_916.副檔名`(例如 `green-base_916.png`),從中心裁切,不動原檔。一次可以拖很多張。
- 後面都用 `green-base_916.png`。

## 步驟 3:生成第一個片段(idle)

下面以 Google Vids 為例(作者的做法);別的工具照同樣的原則做。

**3-1 先把場景調成 9:16(每開一個新影片都要做)**

- 開 <https://docs.google.com/videos/create> 建立新影片 → 選單「檔案(File)」→「影片大小(Video size)」→「直式 9:16(Vertical)」→「套用(Apply)」。
- 確認編輯畫面變成高大於寬的直式長方形,再往下做。

為什麼一定要做:新影片預設是橫式。直式片段放進橫式場景,輸出的 MP4 左右會留白,而且角色只佔中間一小塊,畫質大幅下降。AI 短片面板裡的 Portrait 是另一個設定,**兩邊都要選直式**。

**3-2 生成片段**

- 開啟 AI 短片(Create AI videos)面板 → 側邊欄選 Animate → 比例選 Portrait → 長度依下表選擇。
- 按 Add image,選 `green-base_916.png`。
- 貼 prompt:先「共用前綴」,後面接 idle 的動作句。

| 片段 | 建議長度 | 原因 |
|---|---|---|
| idle | 8 秒 | 會連續播很久,長一點比較不容易看出重複 |
| thinking、listening | 4 秒 | 只播短短一段,動作簡單 |
| 所有 talking-* | 5 秒 | 每次切換都從頭播,短一點動作比較不會漂移 |

(這是作者的建議,不是官方數字。先確認你的服務是不是一次生成只算一次額度、不管長度;如果長度會多扣額度,就統一選短的。)

共用前綴:

```
Use the image as the first frame. Locked static camera, no zoom, no pan, no cut. The character stays exactly in place and the same size, feet planted on the same spot. The background stays flat solid green with no lighting change. Very subtle movement only. No sound, no dialogue.
```

idle 的動作句:

```
Gentle slow breathing, a slow natural blink every few seconds, very slight body sway. Mouth stays closed.
```

生成後檢查:背景一直是同一種純綠(沒有變亮、變暗、漸層);第一格跟你上傳的底圖一樣;鏡頭沒動、角色沒有變大變小或位移;臉和衣服沒有變形、動作很輕微。不合格就改 prompt 再生成(會再扣一次額度),所以 idle 值得多花一點時間調到滿意再往下。合格後 hover 在影片上按 Insert。

## 步驟 4:下載並改名

- 確認場景是直式 9:16,片段填滿整個畫面,左右沒有留白,也沒有多餘標題或其他場景。
- 選單 File → Download → MP4(或 Export to Drive 再從雲端硬碟下載)。
- **把檔案改名成狀態名稱**,例如 `idle.mp4`。檔名會決定輸出的 webm 名稱,**程式靠檔名找片段**。
- 看一下影片角落有沒有浮水印(有些方案的輸出會有,依你的帳號而定);有的話見步驟 5 的調整表。

## 步驟 5:去背並做成循環

**5-1 先量背景色(很重要)。** AI 生成的「綠」通常不是純 `#00FF00`,填錯會去不乾淨,背景變成霧霧的半透明。

1. 在 `idle.mp4` 所在的資料夾開 PowerShell,執行:`ffmpeg -i idle.mp4 -frames:v 1 frame.png`。
2. 用小畫家打開 `frame.png`,用滴管點背景(離角色和角落遠一點),再開「編輯色彩」看紅、綠、藍三個數字。
3. 轉成十六進位。例如 40, 190, 70 → `0x28BE46`。不想手算,PowerShell 可以直接轉:

   ```powershell
   '0x{0:X2}{1:X2}{2:X2}' -f 40,190,70
   ```

4. 用記事本打開 `animation-tools\make-clip.bat`,把 `KEY` 改成你量到的值。

**5-2 設定這個影片屬於哪一套服裝。** 在同一個檔案裡改 `OUTFIT`(預設 `日常`,也就是程式預設穿的那一套)。做完的影片會放進 `clips\<OUTFIT>\`。想做睡衣,就把它改成 `睡衣`。

> `make-clip.bat` 是 UTF-8 存檔,裡面的說明是英文;**請用記事本存檔時保持「UTF-8」編碼**(另存新檔時編碼選 UTF-8,不要選 ANSI),否則中文的服裝名稱會變成亂碼。如果你的環境對中文資料夾名稱有問題,可以先輸出到英文名稱的資料夾,再自己在檔案總管裡改名。

**5-3 先用預覽遮罩調整。** 把 `PREVIEW` 改成 `1`,把 `idle.mp4` 拖到 `make-clip.bat` 上,會在 bat 旁邊產生 `idle_mask.png`:黑色 = 透明、白色 = 實心、灰色 = 霧狀。**背景要全黑、角色要全白。** 調好後把 `PREVIEW` 改回 `0`。

**5-4 正式輸出。** 把 `idle.mp4` 拖到 `make-clip.bat` 上放開。跑完會在 `clips\<OUTFIT>\` 出現 `idle.webm`:透明背景、正放加倒放(長度是原片的兩倍)的無縫循環,聲音已移除。

**調整方法:** 用記事本改 `make-clip.bat` 最上面的數值,再重新拖一次。

| 症狀 | 怎麼改 |
|---|---|
| 背景霧霧的、半透明 | 先確認 `KEY` 是實際量到的背景色;還有霧就把 `SIM` 一次加 0.02(0.16、0.18),用遮罩圖看。不要一次加太多,深色衣服、頭髮和膚色會被一起吃掉 |
| 角色邊緣還有綠邊 | `SIM` 小幅加 0.02,或讓 despill 保持開啟 |
| 角色邊緣被吃掉、變得破碎 | `SIM` 調小(例如 0.10) |
| 角色本身有綠色 | 底圖改用藍色背景,`KEY=0x0000FF`、`SPILL=blue` |
| 右下角有浮水印 | 把 `WM=0` 改成 `WM=1`,再調 `WM_W`(寬)、`WM_H`(高),單位是原始影片的像素;沒貼邊再調 `WM_MX`、`WM_MY` |
| 想要更清晰或更省空間 | `HEIGHT`:960 是預設,1280 更清晰,720 更輕 |

檔案裡還有一行 `lut=a=...`:這是一道亮度曲線,把去背後殘留的淡淡霧狀透明度收乾淨(很淡的當成完全透明,很實的當成完全不透明)。一般不需要動它。

## 步驟 6:實際測試

雙擊 `run.bat` 看看(沒有影片的服裝也能開,這一步是為了檢查動畫),確認:

- 背景完全透明,看得到桌面。
- 角色邊緣乾淨,沒有綠色或白色光暈。
- 循環接點沒有跳動或卡頓。
- 動作自然,倒放的部分沒有怪異。
- 腳底貼近視窗底部,滑鼠點身體左右邊緣也點得到。

這一關通過,後面才值得花生成次數。不通過就先回去調 prompt 或去背參數。

## 步驟 7:第一輪剩下的兩個片段

同樣用 `green-base_916.png`,做法跟步驟 3 到 5 一樣,只換動作句。

**thinking**(長度 4 秒,改名成 `thinking.mp4`):

```
Eyes drift up and to the side, slight head tilt, one slow blink. Mouth stays closed.
```

**talking-neutral**(長度 5 秒,改名成 `talking-neutral.mp4`):

```
Speaking casually to the camera, lips moving naturally, small head nods, occasional blink.
```

做完這三個(idle、thinking、talking-neutral)先用一陣子。缺的表情片段程式會自動退回 `talking-neutral` 或 `idle`。

## 步驟 8:第二輪(額度夠再做)

### 8-1 表情底圖

回到步驟 1 **同一個**圖片生成對話,每種表情各問一次,把括號換成對應的表情描述:

```
Keep the exact same character, outfit, pose, framing and green background.
Only change the expression to: [happy: warm smile / sad: downcast eyes, slight frown / angry: furrowed brows, narrowed eyes, tightly pressed lips / surprised: wide eyes, raised eyebrows]
```

每張都要重做步驟 2 裁成 9:16,存成 `happy_916.png`、`sad_916.png` 等。

### 8-2 各表情的動作句(首幀用對應的表情底圖,長度 5 秒)

**talking-happy**

```
Talking cheerfully with a smile, lips moving, small bouncy head movements.
```

**talking-sad**

```
Talking softly, eyes slightly downcast, lips moving slowly, small slow head movements.
```

**talking-angry**

```
Talking while annoyed, furrowed brows, lips moving, small sharp head movements.
```

**talking-surprised**

```
Talking with wide eyes and raised eyebrows, one tiny startled movement, lips moving.
```

**listening**(用中性底圖,長度 4 秒)

```
Attentive, leaning very slightly forward, tiny nod, eyes on the camera. Mouth stays closed.
```

### 檔名對照

| 輸出檔 | 用哪張底圖 | 批次 |
|---|---|---|
| `idle.webm` | `green-base_916.png` | 第一輪 |
| `thinking.webm` | `green-base_916.png` | 第一輪 |
| `talking-neutral.webm` | `green-base_916.png` | 第一輪 |
| `talking-happy.webm` | `happy_916.png` | 第二輪 |
| `talking-sad.webm` | `sad_916.png` | 第二輪 |
| `talking-angry.webm` | `angry_916.png` | 第二輪 |
| `talking-surprised.webm` | `surprised_916.png` | 第二輪 |
| `listening.webm` | `green-base_916.png` | 最後(可省略) |

## 做更多服裝

每多一套服裝,就重複一次整個流程:在**同一個圖片生成對話**裡請它「只換衣服」(其餘姿勢、構圖、綠背景都不變),把 `make-clip.bat` 裡的 `OUTFIT` 改成新服裝的名字,影片就會進到 `clips\<新名字>\`。同一個角色的每套服裝請保持**人物位置與大小一致**,換裝時畫面才不會跳。

## 自拍用的基底照(選用)

如果你啟用了照片功能(`image.enabled`,見 [設定參考](configuration.md)),每套服裝可以多放兩個檔案,讓拍出來的人物與這套服裝保持一致。它們跟上面的動畫**不是**同一回事,放在同一個服裝資料夾裡:

| 檔案 | 用途 |
|---|---|
| `base.png` | 角色穿這套服裝的**一般照片**(也接受 `base.jpg`、`base.jpeg`、`base.webp`),**不是**綠背景的工作檔。拍照時當成人物參考圖,讓每張照片的臉、髮型、身形與這套服裝保持一致。程式送出前會自動縮小(長寬都不超過 511 像素),不會改你的原檔;有透明背景的圖會墊白底。 |
| `outfit.txt` | 一行**英文**外觀描述,例如 `a soft pajama set`。沒有基底照時,拍照會用它(再加上 `image.appearance`)當作純文字描述。 |

沒有 `base.png` 的服裝也能拍照,只是人物一致性較差;如果 `image.appearance` 也是空的,啟動時會有警告。

## 常見問題

- **鏡頭在動、或背景變色:** 在動作句後面加上 `Do not move the camera. Keep the background perfectly flat green.` 再重試。
- **影片服務拒絕生成:** 這是**寫實的真人臉**比較常遇到的狀況,卡通或插畫風格通常比較順利。角色看起來太年輕也可能被拒絕,即使你在圖片生成時指定成年,影片服務仍依畫面判斷;這時請讓角色的臉和身形更成熟,並避免鼓腮幫子、大眼圓臉這類孩子氣的表情。不同服務的規則不一樣,被拒絕就換一個工具試試。
- **切換表情時有鬼影:** 所有底圖裡角色的位置、大小要完全一致,這就是每張表情圖都要「只改表情」的原因。
- **使用條款與肖像權:** 請確認你有權使用所用的照片與影片,**特別是真人的形象**;也請確認你的生成服務對輸出內容的使用規定。某些服務註明生成內容只能在該服務內使用,自己用沒問題,要公開發佈前請先看清楚使用條款。

## 思考短音(選用)

把預錄的思考短音放進專案的 `fillers\`(`.mp3`、`.wav` 或 `.ogg`),例如「嗯…」「讓我想想」。等待回覆超過約 2 秒時,會隨機播放其中一個;沒放任何檔案就不播。建議每段 1 秒左右,聲音要和角色的聲線接近。
