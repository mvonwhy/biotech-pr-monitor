# BioTech PR Monitor

A simple tool that watches for press releases and public coverage about biotech companies on your watchlist, then surfaces the ones that matter so you can review them quickly.

## What it does

- Follows a short list of trusted biotech news sources
- Looks for posts that mention companies you care about
- Pulls out the press-release or investor-relations link when one is available
- Alerts you in chat when something new shows up
- Quietly tracks which source tends to post first (for learning over time)

The goal is straightforward: know when a PR is out, read it, and decide if it is worth acting on.

## Basic setup

1. Keep a ticker watchlist (for example, a spreadsheet column of symbols you follow).
2. Connect your X (Twitter) API access and store credentials securely (never commit secrets).
3. Install dependencies and copy `.env.example` to `.env`, then fill in local settings.
4. Start the monitor so it can listen for matching posts and write alerts.

Details for developers live in the repo’s scripts and config folders. Do not put passwords, API keys, or `.env` files into git.

## Privacy & secrets

This project is meant to run with secrets kept outside the repository (for example, a password manager or environment variables). The public repo should never contain live credentials or alert logs.
