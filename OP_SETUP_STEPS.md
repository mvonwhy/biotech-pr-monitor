# 1Password setup — X PR Monitor

Follow these in order. Pause after each step if you need to. **Never paste secret values into chat.**

## Step 1 — Create the 1Password item

1. Open 1Password.
2. Create a new item (Login or API Credential).
3. Name it exactly: **X API – BioTech PR Monitor**
4. Add three fields:
   - **API Key** (consumer key) — e.g. username or a custom field
   - **API Secret** (consumer secret) — use the password / credential field
   - Custom field named exactly: `bearer` (for the Bearer token)
5. Leave the values blank for now if you don’t have the X keys yet.
6. Save the item.
7. Note (for yourself only):
   - The item’s **UUID** (item details / private link)
   - Which **vault** it lives in  
   Do **not** paste any secret values into chat.

When Step 1 is done, you’re ready for Step 2.

---

## Step 2 — Install and sign in to the 1Password CLI

On the computer that will run the monitor:

1. Install the 1Password CLI (`op`):  
   https://developer.1password.com/docs/cli/get-started/
2. Sign in: `op signin`  
   (Or enable CLI integration with the 1Password desktop app.)
3. Confirm: `op whoami`

---

## Step 3 — Wire the item into app config

In `/workspace/x-pr-monitor/.env` (copy from `.env.example` if needed), use **op://** references only — no plaintext keys:

```bash
OP_X_API_ITEM_ID=<your-item-uuid>
X_API_KEY=op://<Vault>/<your-item-uuid>/username
X_API_SECRET=op://<Vault>/<your-item-uuid>/credential
X_BEARER_TOKEN=op://<Vault>/<your-item-uuid>/bearer
```

Replace `<Vault>` and `<your-item-uuid>` with yours. Field names must match what you created in Step 1 (`credential` / password field, and `bearer`).

The app resolves these at runtime via `src/secrets.py` (`op read`). Nothing secret is written back to disk.

---

## Step 4 — Verify the app can read the key

```bash
cd /workspace/x-pr-monitor
source .venv/bin/activate   # if you use the venv
python scripts/verify_op_secrets.py
```

You should see OK for loaded secrets (values are hidden). Then start the receiver; it refuses to boot without `X_API_SECRET`:

```bash
uvicorn src.app:app --host 127.0.0.1 --port 8787
```

---

File location on the box: `/workspace/x-pr-monitor/OP_SETUP_STEPS.md`
