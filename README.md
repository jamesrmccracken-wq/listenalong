# ListenAlong

A private audiobook app for your own documents. Import a file or folder, listen anywhere, and follow the highlighted text while it plays.

Hosted on the public internet, so your phone does not need to be on the same Wi‑Fi as your computer.

## Local

```powershell
cd $HOME\listenalong
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Optional password for local use:

```
APP_PASSWORD=your-password
APP_SECRET=long-random-string
```

## Phone

Open the hosted URL, sign in, then **Add to Home Screen**. Use **Save offline** on a title before a commute if you might lose signal.

## Import

PDF, EPUB, Word, markdown, text, code, zip, or a folder. On iPhone, zip the folder first.
