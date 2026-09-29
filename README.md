# BioTech PR Monitor

A simple tool that watches for press releases and public coverage about biotech companies on your watchlist, then surfaces the ones that matter so you can review them quickly.

## What it does

- Follows a short list of trusted biotech news sources
- Looks for posts that mention companies you care about
- Pulls out the press-release or investor-relations link when one is available
- Alerts you in chat when something new shows up
- Quietly tracks which source tends to post first (for learning over time)

The goal is straightforward: know when a PR is out, read it, and decide if it is worth acting on.

## Prerequisites (before you start)

Have these ready. You do not need to be technical — just an account for each.

1. **1Password** — an account (and the 1Password app on the computer that will run the monitor). This is where you will store X API keys so they never sit in plain text in the project folder.
2. **An X (Twitter) account** — the same one you will use for the X Developer Portal.
3. **X API access** — you will create this below (developer account → Project → App → keys). Filtered Stream / Pay Per Use needs enough credits or a plan that allows live stream reading; X bills per matched post on that path.
4. **A ticker watchlist** — for example a Google Sheet with a column of stock symbols you follow (this project reads that list; it does not edit the sheet unless you explicitly allow it).
5. **Optional but helpful** — Google Drive access so the monitor can refresh tickers from your Trade Plan sheet; GitHub if you want to clone this repo yourself.

Never put real passwords, API keys, or tokens into this README, into chat, or into git.

## Basic setup (once credentials exist)

1. Keep your ticker watchlist up to date.
2. Store X credentials in 1Password (steps below).
3. Copy `.env.example` to `.env` and point the `op://…` lines at your 1Password item (no plaintext keys).
4. Install dependencies, then start the monitor so it can listen and write alerts.

## Setting up X (Twitter) API credentials from scratch

This walkthrough is for someone who has never opened the X Developer Portal. Take it one screen at a time. You will create a Project, an App inside it, then copy five secret values into 1Password.

### Step A — Open the developer site and apply

1. On a computer, open a browser and go to: **https://developer.x.com/**  
   (Older bookmarks may say developer.twitter.com — that redirects to the same place.)
2. Sign in with your normal X username and password.
3. If X asks you to apply for a developer account, complete the short form. Pick a use case that matches “reading public posts / building a tool that monitors public content.” Be honest; you are reading public posts, not posting spam.
4. Accept the developer agreement when prompted.
5. Wait until you land in the **Developer Portal** dashboard (you should see a place to create a Project or App).

### Step B — Create a Project

1. In the Developer Portal, look for **Projects & Apps** (or **+ Add Project**).
2. Click to create a **new Project**.
3. **Name suggestion:** `BioTech PR Monitor` (any clear name is fine).
4. Choose a use case if asked (monitoring / research / tooling is fine).
5. Add a short description if asked, for example: “Alerts me when trusted biotech news accounts post press releases about tickers I follow.”
6. Finish the Project wizard until the Project exists. You should now see the Project on your dashboard.

### Step C — Create an App inside that Project

1. Open the Project you just created.
2. Choose **Create App** (or **Add App**) inside that Project.
3. **App name suggestion:** `biotech-pr-monitor` (App names must be unique across X, so add your initials if taken, e.g. `biotech-pr-monitor-mvw`).
4. Save / continue until the App is created.
5. You should land on an App page with tabs such as **Settings** and **Keys and tokens**.

### Step D — Generate the keys (copy carefully)

Open the App’s **Keys and tokens** (sometimes labeled **Keys and tokens** under the App).

You will deal with these one at a time. X often shows a secret **only once** — if you leave the page without saving it, you may need to regenerate.

#### 1) API Key and API Key Secret (also called Consumer Key / Consumer Secret)

1. Find the section for **API Key and Secret** (or Consumer Keys).
2. If keys already exist, you can reveal them; if not, click **Generate**.
3. Copy the **API Key** (shorter public-ish identifier).
4. Copy the **API Key Secret** (longer secret). Treat this like a password.
5. Paste both into 1Password **immediately** (Step E). Do not email them to yourself or paste them into Slack/chat.

#### 2) Bearer Token

1. On the same Keys and tokens page, find **Bearer Token**.
2. Click **Generate** (or Regenerate if you are starting fresh and understand the old one will stop working).
3. Copy the **Bearer Token**.
4. Paste it into 1Password right away (Step E).

#### 3) Access Token and Access Token Secret (user tokens)

1. Still on Keys and tokens, find **Access Token and Secret** (sometimes under “Authentication Tokens” for your account).
2. Click **Generate** if they are not created yet.
3. Copy the **Access Token**.
4. Copy the **Access Token Secret**.
5. Paste both into 1Password (Step E).  
   This project mainly needs the API Key, API Secret, and Bearer Token for reading the live stream; Access Token / Secret are optional extras you may want later for user-context calls.

**Tip:** If the portal offers app permissions, **Read** is enough for monitoring. You do not need Write unless you plan to post from this App.

### Step E — Where to paste each value (1Password)

Do this in 1Password — not in the public GitHub repo, and not in chat.

1. Open **1Password**.
2. Create a new item (Login or API Credential is fine).
3. **Name it exactly:** `X API – BioTech PR Monitor` (so it is easy to find later).
4. Save these fields on that one item:

| What X called it | Where to put it in 1Password |
| --- | --- |
| API Key | Username field, **or** a custom field named `api_key` |
| API Key Secret | Password / credential field |
| Bearer Token | A custom field named exactly `bearer` |
| Access Token (optional) | Custom field `access_token` |
| Access Token Secret (optional) | Custom field `access_token_secret` |

5. Save the item. Note which **vault** it lives in (for example Private) and the item’s ID if 1Password shows one — you will only need those for `op://` references, not the secret values themselves.

### Step F — Point the project at 1Password (no plaintext keys)

1. In the project folder, copy `.env.example` to a new file named `.env`.
2. Fill the secret lines with **references**, not the raw keys. Example shape (replace vault name and item id with yours):

```bash
OP_X_API_ITEM_ID=YOUR_ITEM_ID_HERE
X_API_KEY=op://Private/YOUR_ITEM_ID_HERE/username
X_API_SECRET=op://Private/YOUR_ITEM_ID_HERE/credential
X_BEARER_TOKEN=op://Private/YOUR_ITEM_ID_HERE/bearer
# Optional:
# X_ACCESS_TOKEN=op://Private/YOUR_ITEM_ID_HERE/access_token
# X_ACCESS_TOKEN_SECRET=op://Private/YOUR_ITEM_ID_HERE/access_token_secret
```

3. Install / sign in to the **1Password CLI** on that computer so the app can read those `op://` references at runtime.
4. Run the project’s verify script (`scripts/verify_op_secrets.py`) to confirm secrets load. It should say OK without printing the actual keys.

If anything fails, double-check field names (`bearer`, credential/password field) and that you are signed into 1Password on that machine.

## Privacy & secrets

- Never commit `.env`, real keys, Bearer tokens, or alert logs.
- Prefer 1Password (or another vault) over leaving secrets in files.
- If a key leaks, regenerate it in the X Developer Portal and update the 1Password item.
