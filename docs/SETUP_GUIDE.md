# Setup Guide (no coding needed)

This guide shows how to put TokenVault AI files into GitHub using only your web browser.

## One-time: create the repository

1. Go to github.com and sign in (create a free account if needed).
2. Click the **+** at the top right, then **New repository**.
3. Name it `tokenvault-ai`.
4. Choose **Private** (recommended until you are ready).
5. Click **Create repository**.

## Adding a file

1. In your repository, click **Add file**, then **Create new file**.
2. In the name box, type the full path exactly as given, for example `docs/ARCHITECTURE.md`. Typing a `/` automatically creates a folder.
3. Paste the file's complete contents into the large text area.
4. Click **Commit changes**, then **Commit changes** again.

Alternative: on a computer, **Add file**, then **Upload files** lets you drag many files at once. Folders keep their structure.

## Important rules

- Never upload a file named `.env`. It holds secrets. Only `.env.example` (placeholders) belongs in GitHub.
- Never paste a real API key into any file, chat, or GitHub page.
- If a file is updated later, you will receive the complete replacement. Open the existing file, click the pencil icon, delete everything, paste the new contents, and commit.
- If you are unsure, ask before committing.

## Batch 1 checklist

- [ ] `README.md`
- [ ] `.gitignore`
- [ ] `.env.example`
- [ ] `docs/SETUP_GUIDE.md`
- [ ] `docs/ARCHITECTURE.md`
- [ ] `docs/SECURITY.md`
- [ ] `LICENSE` (after you choose a license)

## What happens next

Batches 2 to 7 add the working code. Nothing needs to be run by you until Batch 6, where a guided local start is provided. No paid service is required at any point before deployment.
