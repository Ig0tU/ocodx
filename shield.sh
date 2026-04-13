#!/bin/bash

# --- CONFIGURATION ---
RED='\033[00;31m'
GREEN='\033[00;32m'
CYAN='\033[00;36m'
YELLOW='\033[00;33m'
RESTORE='\033[0m'

echo -e "${CYAN}--- STARTING SECURITY SHIELD SCAN ---${RESTORE}"

# 1. Check for sensitive files that shouldn't exist in a repo
echo -e "\n${YELLOW}[1/4] Checking for forbidden filenames...${RESTORE}"
FORBIDDEN=(".env" "credentials.json" ".pem" ".key" "id_rsa" "auth.json" "secrets.yml")
for file in "${FORBIDDEN[@]}"; do
    if find . -maxdepth 2 -name "$file" | grep -q .; then
        echo -e "${RED}CRITICAL: Found $file in directory!${RESTORE}"
    fi
done

# 2. Gitleaks: Scan untracked local files
echo -e "\n${YELLOW}[2/4] Gitleaks: Scanning local filesystem (untracked)...${RESTORE}"
gitleaks detect --source . --no-git -v
if [ $? -eq 0 ]; then
    echo -e "${GREEN}PASS: No secrets found in local files.${RESTORE}"
else
    echo -e "${RED}FAIL: Secrets detected in local files!${RESTORE}"
fi

# 3. Gitleaks: Scan full git history
echo -e "\n${YELLOW}[3/4] Gitleaks: Scanning entire git history...${RESTORE}"
gitleaks detect --source . -v
if [ $? -eq 0 ]; then
    echo -e "${GREEN}PASS: No secrets found in history.${RESTORE}"
else
    echo -e "${RED}FAIL: Secrets found in git history!${RESTORE}"
fi

# 4. TruffleHog: Verify active secrets
if command -v trufflehog &> /dev/null; then
    echo -e "\n${YELLOW}[4/4] TruffleHog: Verifying secrets...${RESTORE}"
    trufflehog filesystem . --fail
else
    echo -e "\n${CYAN}SKIP: TruffleHog not installed. Skipping verification.${RESTORE}"
fi

echo -e "\n${CYAN}--- SCAN COMPLETE ---${RESTORE}"