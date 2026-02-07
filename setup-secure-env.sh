#!/bin/bash
# setup-secure-env.sh
# Secure local development environment setup
# This script helps you set up credentials safely without exposing them

set -e

echo "🔐 AALTOHUBv2 Secure Environment Setup"
echo "======================================"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env.local already exists
if [ -f .env.local ]; then
    echo -e "${YELLOW}⚠️  .env.local already exists${NC}"
    read -p "Do you want to overwrite it? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping .env.local creation"
        exit 0
    fi
fi

echo "📝 Creating .env.local template..."
cat > .env.local << 'EOF'
# ⚠️  LOCAL DEVELOPMENT ONLY
# This file is automatically ignored by git (.gitignore)

# === Supabase ===
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_JWT_SECRET=

# === Telegram API ===
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
ADMIN_PHONE=
ADMIN_USERNAME=

# === Encryption & JWT ===
SESSION_ENCRYPTION_KEY=
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# === API Configuration ===
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000,https://aaltohub.com

# === Third-party Services ===
SENTRY_DSN=
RESEND_API_KEY=

# === Environment ===
ENVIRONMENT=development
EOF

echo -e "${GREEN}✅ Created .env.local${NC}"
echo ""

# Set appropriate permissions
chmod 600 .env.local
echo -e "${GREEN}✅ Set secure permissions (600) on .env.local${NC}"
echo ""

# Check .gitignore
if [ -f .gitignore ]; then
    if grep -q ".env.local" .gitignore; then
        echo -e "${GREEN}✅ .env.local is already in .gitignore${NC}"
    else
        echo ".env.local" >> .gitignore
        echo -e "${GREEN}✅ Added .env.local to .gitignore${NC}"
    fi
else
    echo ".env.local" > .gitignore
    echo -e "${GREEN}✅ Created .gitignore with .env.local${NC}"
fi

echo ""
echo "📋 Next steps:"
echo "1. Open .env.local and add your credentials"
echo "2. DO NOT commit .env.local to git"
echo "3. For production, use AWS Secrets Manager, 1Password, or similar"
echo "4. Read CREDENTIALS_SETUP.md for best practices"
echo ""
echo -e "${GREEN}Setup complete!${NC}"
