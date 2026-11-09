# AI Animated Companion

[繁體中文 README](README.md) · This page is a short English overview.

A desktop AI companion for Windows. The character lives in a frameless, truly transparent, always-on-top pet window, shown with **photo-style full-body animation** that you make yourself. You can type or simply talk to it. It remembers what you told it, has its own emotions and an affection level, can change outfits on command, and can send you selfies.

> **Only supports Windows 10 / 11.** macOS and Linux are not supported.
>
> **The interface, the built-in prompts and all documentation are in Traditional Chinese (繁體中文).** The character's own language follows its persona file, but the default voice is Taiwanese Mandarin and other languages are untested. This page and its install commands are all you get in English; the detailed guides linked below are Chinese-only.

## Features

- **Photo-style full-body animation.** The project ships no character. You provide short clips (idle, listening, thinking, and talking in five emotions) and the pet switches between them by itself. Without clips it falls back to emoji and is still fully usable.
- **Outfit changes by command.** Tell the character "change into pajamas" and it switches to the matching outfit folder. The choice survives restarts.
- **Selfies** (optional). The character can take a photo for you; a base photo per outfit keeps the person consistent.
- **Voice conversation.** Hold a button (or F2) to talk, or turn on continuous listening and interrupt at any time. Speech output defaults to the free Edge voices (a male voice is one setting away); a local OpenAI-compatible speech server or Fish Audio also work. Speech recognition uses Groq. Typing always works.
- **Memory.** Everything stays on your computer. Old conversations are folded into a journal and long-term facts that are recalled when relevant.
- **Items and state.** The character keeps track of where it is, its physical state (it recovers over time) and the items it holds.
- **Affection and emotion.** Every sentence carries an emotion that drives the animation. Affection is a 0-100 value that rises and falls with your interactions and drifts back to neutral when you are away.
- **Also:** time awareness, optional proactive messages, optional web search, and you can show it pictures.
- **You define the character.** Name, personality, tone, gender and pronouns all live in your own persona file; nothing is assumed.

## Requirements

| | |
|---|---|
| OS | Windows 10 or 11 only |
| Python | 3.11 or newer |
| Node.js | 22.12 or newer. Used only to **install** the pet window (Electron) |
| Gemini API key | Required (a free tier exists) |
| Groq API key + microphone | Only for voice input |

## Quick start

In PowerShell, from the project folder:

```powershell
python -m venv .venv                                       # 1. create a virtual environment
.venv\Scripts\python -m pip install -r requirements.txt    # 2. install the packages (into .venv only)
cd electron; npm install; cd ..                            # 3. install the pet window (Electron), once
.venv\Scripts\python app.py --set-key                      # 4. paste your Gemini key (stored in Windows Credential Manager)
copy persona.example.md persona.md                         # 5. create your own persona file, then edit it
.\run.bat                                                  # 6. start
```

For voice input, also run `.venv\Scripts\python app.py --set-key-groq`.

**If step 3 is extremely slow:** the install downloads an Electron executable (about 150 MB) from GitHub. The [install guide](docs/install.md) (in Chinese, but the commands are plain PowerShell and cmd) describes three routes: the default one, a download mirror, and a **manual download** in which you fetch the zip yourself, verify its SHA-256 and unpack it. The manual route is the one the maintainer used.

## Starting and quitting

- **Start:** double-click `run.bat`. It checks the installation and then opens only the pet window (no console window). Use `run-debug.bat` instead to keep a console with the program's output.
- **Quit:** the exit button at the top of the toolbar (press once, it turns red and asks to be pressed again), or right-click the tray icon and choose the quit entry.

## Making the character

Put each outfit in its own folder, `clips\<outfit name>\`, with at least `idle.webm`. Optional clips are `thinking`, `listening` and `talking-neutral` / `-happy` / `-sad` / `-angry` / `-surprised`; a missing one falls back to a similar clip and finally to `idle`. The tools in `animation-tools` remove the green-screen background and make seamless loops. The step-by-step guide, with ready-to-paste image and video prompts, is [docs/animation-tutorial.md](docs/animation-tutorial.md) (Chinese). Make sure you have the right to use any photos or videos you build the character from, especially real people's likeness.

## Privacy

Your text messages (and any images you attach) go to Google Gemini. Voice recordings go to Groq for transcription, and Gemini only receives the transcript. Sentences to be spoken go to Microsoft's Edge voice service by default. Optional features send data to their own providers (Fish Audio, Cloudflare, TinyFish). Conversations and memory are stored only in `data\history.db` on your computer, and API keys live in Windows Credential Manager or environment variables, never in a file. The free Gemini tier may be used by Google to improve its products, so avoid very private topics.

## Documentation (Chinese)

- [Install guide](docs/install.md)
- [Configuration reference](docs/configuration.md): every setting, environment variable and command-line flag
- [Animation tutorial](docs/animation-tutorial.md)
- [Troubleshooting](docs/troubleshooting.md)

## License

[MIT](LICENSE).
