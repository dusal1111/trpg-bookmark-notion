# 🎲 Twitter TRPG Scenario Bookmarks → Notion Auto-Organizer

A tool that automatically collects your Twitter(X) TRPG scenario bookmarks,  
classifies them by system, extracts info with AI, and saves them to Notion databases.

---

## ✨ What does it do?

- Fetches all your Twitter bookmarks at once
- Automatically classifies them by TRPG system (CoC / inSANe / Shinobigami, etc.)
- Uses AI to extract scenario name, player count, mood, and overview
- Creates a separate Notion DB for each TRPG system
- On subsequent runs, only fetches newly added bookmarks (no duplicates)

---

## 📋 Requirements

| Item | Required | Notes |
|------|----------|-------|
| Windows PC | Required | |
| Python 3.8+ | Required | See installation below |
| Twitter(X) account | Required | Must be logged in |
| Notion account | Required | |
| AI API key | Optional | Needed for AI field extraction (see below) |

---

## 🚀 Installation & Setup

### Step 1. Install Python

Skip this step if Python is already installed.

1. Go to https://www.python.org/downloads/
2. Click "Download Python 3.x.x"
3. Run the installer

> ⚠️ **Important:** Check **"Add Python to PATH"** at the bottom of the installer screen!

---

### Step 2. Download files

Click **Code → Download ZIP** at the top right of this page, then extract the archive.

> ⚠️ **If Windows blocks the file as "unsafe":** Right-click the zip → **Properties** → check **"Unblock"** at the bottom → OK. Then extract.

---

### Step 3. Initial setup (one time only)

Double-click **`setup.bat`** inside the extracted folder.

It will guide you through entering the required values one by one.

---

#### 🐦 How to get your Twitter tokens

> These are cookie values that keep you logged in. Do not share them with anyone.

1. Log in to **x.com** on Chrome or Edge
2. Press **F12** → **Application** tab → left sidebar **Cookies** → **https://x.com**
3. Find **`ct0`** and **`auth_token`** in the list and copy each value

> 💡 If your tokens expire (after logout or password change), re-run `setup.bat` to update them.

---

#### 📝 How to get your Notion token

1. Go to https://www.notion.so/my-integrations (Notion login required)
2. Click **"+ Create new integration"** → enter a name → **Submit**
3. Click **Show** next to **"Internal Integration Secret"** → copy the value

---

#### 📄 How to get your Notion page ID

You need a Notion page where the system DBs will be created.

1. Open the target page in Notion
2. Click **`...`** in the top-right → **Connections** → click your integration name to connect
3. Check the URL in your browser — the last 32 characters are the page ID:
   ```
   https://www.notion.so/page-name-abc123def456abc123def456abc123de
                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   ```

---

### Step 4. Run

After setup, just double-click **`run.bat`** every time.

```
====================================================
  Twitter Bookmark Pipeline
====================================================

  1. Sync bookmarks    (fetch new bookmarks from Twitter)
  2. Classify          (auto-classify by TRPG system)
  3. AI extract        (auto-extract name/players/mood/overview)
  4. Notion upload     (save to Notion DB)
  5. Run all           (1 → 2 → 3 → 4 at once)
  6. Full reclassify   (reset classifications and start over)
  0. Quit
```

First time? Select **5 (Run all)**. After that, run 5 periodically to add only new bookmarks.

---

## 🎲 Supported TRPG Systems

Defined in `trpg_systems.json`. Edit keywords to adjust classification rules.

| System | Notion DB Name |
|--------|----------------|
| Call of Cthulhu (CoC) | CoC 시나리오 정리 |
| inSANe | inSANe 시나리오 정리 |
| 비밀요원국 | 비밀요원국 시나리오 정리 |
| 설화학당 | 설화학당 시나리오 정리 |
| Magica Logia | 마기카로기아 시나리오 정리 |
| Shinobigami | 시노비가미 시나리오 정리 |
| Other | 기타 시나리오 정리 |

---

## 📊 Notion DB Fields

Fields saved to each system's database:

| Field | Description | Source |
|-------|-------------|--------|
| Scenario Name | Scenario title | AI extracted |
| Distribution URL | Scenario download link | Tweet link |
| Min / Max Players | Player count | AI extracted |
| Mood | Horror, Slice-of-life, Mystery, etc. (multi-select) | AI extracted |
| Overview | 1–2 sentence summary | AI extracted |
| Original Tweet | Source tweet URL | Auto |
| Image | Tweet media image | Auto |
| Saved Date / Tweet Date | Date info | Auto |

---

## 🤖 AI Field Extraction (optional)

AI automatically extracts scenario name, player count, mood, and overview.  
You only need **one** of the following (in priority order):

| AI | Key name | Where to get it |
|----|----------|-----------------|
| OpenAI | `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| Vertex AI | `VERTEX_PROJECT_ID` | GCP Console (requires gcloud CLI auth) |
| Gemini | `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey |

Re-run `setup.bat` to enter your key, or open `.env` in a text editor and add it directly:

```
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
VERTEX_PROJECT_ID=my-gcp-project
```

> Vertex AI requires running `gcloud auth application-default login` for authentication.

---

## ❓ FAQ

**Q. I get "python is not recognized as an internal or external command..."**  
→ You didn't check "Add Python to PATH" during installation. Reinstall Python and make sure to check that box.

**Q. Token error / bookmarks won't load**  
→ Logging out of Twitter or changing your password invalidates the tokens. Re-run `setup.bat` to enter new ones.

**Q. Notion upload isn't working**  
→ Make sure your Integration is connected to the Notion page. (Page `...` → Connections)

**Q. Old bookmarks are being uploaded again**  
→ The `uploaded_ids.json` file tracks what's been uploaded. If it gets deleted, duplicates will appear. Don't delete this file.

**Q. What happens if I upload without AI extraction?**  
→ The scenario name will use the first 50 characters of the tweet, and players/mood/overview will be empty. Re-uploading after extraction is not possible, so extract first if you can.

---

## 📂 File structure

```
trpg-bookmark-notion/
├── setup.bat                  ← Initial setup (run once)
├── run.bat                    ← Run this every time
├── setup_wizard.py            Setup wizard
├── run_menu.py                Main menu
├── bookmark_sync.py           Twitter bookmark fetcher
├── classify_bookmarks.py      TRPG system classifier
├── reclassify_ai.py           AI field extractor (OpenAI/Vertex/Gemini)
├── setup_and_upload.py        Notion DB creation & upload
├── trpg_systems.json          System definitions & keyword config
│
│   ← Files below are auto-generated (do not touch)
├── .env                       Saved tokens
├── bookmarks.jsonl            Fetched bookmarks
├── classified_bookmarks.jsonl Classified bookmarks
├── uploaded_ids.json          Notion upload log (deleting causes duplicates)
└── notion_db_ids.json         Generated Notion DB ID list
```

---

## ⚠️ Notes

- This tool uses Twitter's internal API. It may stop working if Twitter changes their API.
- Your Twitter tokens (`ct0`, `auth_token`) are equivalent to your login credentials. Never share your `.env` file or upload it to GitHub.
- For personal use only.

---

## 📜 License

MIT License — free for personal and non-commercial use.
