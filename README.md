# Microsoft Rewards India Restock Sentinel

Automated, 0-risk sentinel running via GitHub Actions on a 5-minute cron schedule.
Monitors the public Microsoft Rewards India shop catalog and dispatches Discord embeds the instant high-value third-party gift cards (Amazon Pay, Flipkart, Croma, BookMyShow, etc.) drop back into stock.

## How it Works
- Runs serverless in the cloud using GitHub Actions.
- Zero credentials required: polls public catalog HTML, so your Microsoft account is never exposed to ban risks.
- Emits Discord Rich Embeds with `@everyone` alerts when restocks are detected.

## Setup
Add your Discord Webhook URL to GitHub Secrets:
1. Go to repository **Settings** -> **Secrets and variables** -> **Actions**.
2. Click **New repository secret**.
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: `https://discord.com/api/webhooks/...`
