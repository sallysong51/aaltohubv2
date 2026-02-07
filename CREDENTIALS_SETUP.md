# Secure Credentials Setup Guide

## Overview
This guide explains how to properly manage credentials and secrets in the AALTOHUBv2 project without exposing them to version control.

## What NOT to Do ❌
- ❌ Never commit `.env` files to git
- ❌ Never hardcode credentials in source code
- ❌ Never paste credentials in shell configuration files (`.bashrc`, `.zshrc`)
- ❌ Never share credentials via email, chat, or unencrypted channels
- ❌ Never use the same credentials across development, staging, and production

## Local Development Setup ✅

### 1. Use `.env.local` for local development
```bash
# Copy the template to your local .env file
cp .env.local ~/.env.local
```

The `.env.local` file is:
- ✅ Excluded from git (see `.gitignore`)
- ✅ Only visible on your machine
- ✅ Not tracked by version control

### 2. Load credentials from secure sources

#### Option A: 1Password (Recommended for teams)
```bash
# Install 1Password CLI
brew install 1password-cli

# Load secrets from 1Password
eval $(op signin my.1password.com email@example.com)
```

#### Option B: AWS Secrets Manager (Recommended for AWS projects)
```bash
# Install AWS CLI
brew install awscli

# Configure AWS credentials
aws configure

# Retrieve secrets
aws secretsmanager get-secret-value --secret-id aaltohub/dev
```

#### Option C: dotenv-cli for local development
```bash
# Install dotenv
npm install -g dotenv-cli

# Run your app with .env.local
dotenv -e .env.local node your-app.js
```

### 3. Backend (Python) Setup
```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Load environment variables from .env.local
# Python will automatically load from .env.local if you're using python-dotenv
python app.py
```

### 4. Frontend (Node.js) Setup
```bash
cd client

# Install dependencies
pnpm install

# Create .env.local with frontend-specific variables
cp .env.example .env.local

# Start development server
pnpm dev
```

## Environment Secrets by Service

### Supabase
- 🔑 **SUPABASE_URL**: Database connection URL
- 🔑 **SUPABASE_KEY**: Service role key (keep private!)
- 🔑 **SUPABASE_JWT_SECRET**: JWT signing key

**Rotation**: Every 90 days or if compromised
**Storage**: AWS Secrets Manager / 1Password

### Telegram API
- 🔑 **TELEGRAM_API_ID**: From https://my.telegram.org
- 🔑 **TELEGRAM_API_HASH**: From https://my.telegram.org

**Rotation**: When credentials are compromised
**Storage**: AWS Secrets Manager / 1Password

### JWT & Session
- 🔑 **JWT_SECRET_KEY**: Use a strong random string (min 32 chars)
- 🔑 **SESSION_ENCRYPTION_KEY**: Use a strong random string

**Generation**:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Third-party Services
- 🔑 **SENTRY_DSN**: Error tracking (can be semi-public)
- 🔑 **RESEND_API_KEY**: Email service API key

**Rotation**: When compromised

## CI/CD Environment Variables

### GitHub Actions
Store secrets in: **Settings → Secrets and variables → Actions**

```yaml
# .github/workflows/deploy.yml
- name: Deploy to production
  env:
    SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
    SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
    JWT_SECRET_KEY: ${{ secrets.JWT_SECRET_KEY }}
  run: npm run deploy
```

### Vercel (if used)
1. Go to Project Settings → Environment Variables
2. Add secrets for each environment (development, preview, production)
3. Use different values for each environment

## Credential Rotation Checklist

When you need to rotate credentials:
- [ ] Generate new credential in the service (Supabase, AWS, etc.)
- [ ] Update the credential in your secrets manager (1Password, AWS Secrets Manager)
- [ ] Update in CI/CD (GitHub Actions, Vercel, etc.)
- [ ] Verify all environments are updated
- [ ] Revoke/delete old credential
- [ ] Test that services still work

## Troubleshooting

### "Module not found: dotenv"
```bash
pip install python-dotenv  # Python
npm install dotenv         # Node.js
```

### Environment variables not loading
1. Check that `.env.local` is in the root directory
2. Verify you're not running with a parent directory's `.env`
3. Check file permissions: `ls -la .env.local`
4. Restart your development server after creating `.env.local`

### Need to share a test credential with a team member?
1. Use your organization's secure credential sharing (1Password, LastPass, etc.)
2. Set an expiration time on temporary credentials
3. Never share via email or unencrypted channels

## Additional Resources

- [OWASP: Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [12 Factor App: Config](https://12factor.net/config)
- [GitHub: Security best practices](https://docs.github.com/en/code-security)
