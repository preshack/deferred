#!/bin/bash
# ======================================================================
# 🚀 DEFERRED API: 16-DIGIT EMERGENCY OFFLINE PAYMENT DEMO 🚀
# ======================================================================
set -e
API_URL="http://localhost:8000"
ENV_FILE="demo_creds.env"

# ----------------------------------------------------------------------
# STEP 0: LOAD OR CREATE CREDENTIALS
# ----------------------------------------------------------------------
JWT=""
WALLET_ID=""

if [ -f "$ENV_FILE" ]; then
    echo -e "\033[36mLoading credentials from $ENV_FILE...\033[0m"
    source "$ENV_FILE"
fi

if [ -z "$ALICE_JWT" ] || [ -z "$ALICE_WALLET_ID" ]; then
    echo -e "\033[33mCredentials missing. Generating new JWT and Wallet...\033[0m"
    
    # 1. Generate a permanent JWT
    RANDOM_ID=$RANDOM
    CUSTOMER_BODY="{\"customer_id\": \"alice_demo_$RANDOM_ID\", \"secret\": \"test_secret\"}"
    JWT=$(curl -s -X POST "$API_URL/auth/token" -H "Content-Type: application/json" -d "$CUSTOMER_BODY" | grep -o '"access_token": "[^"]*' | grep -o '[^"]*$')
    
    # 2. Create Wallet
    IDEMP_KEY=$(uuidgen)
    WALLET_BODY="{\"type\":\"personal\", \"offline_allowance_cents\":10000, \"customer_reference\":\"alice_demo_ref_$RANDOM_ID\"}"
    WALLET_ID=$(curl -s -X POST "$API_URL/wallets" -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -H "Idempotency-Key: $IDEMP_KEY" -d "$WALLET_BODY" | grep -o '"id": "[^"]*' | grep -o '[^"]*$')

    # 3. Save to env file permanently
    echo "ALICE_JWT=$JWT" > "$ENV_FILE"
    echo "ALICE_WALLET_ID=$WALLET_ID" >> "$ENV_FILE"
    echo -e "\033[32m✅ Created Wallet $WALLET_ID and saved to $ENV_FILE\n\033[0m"
else
    JWT=$ALICE_JWT
    WALLET_ID=$ALICE_WALLET_ID
    echo -e "\033[32m✅ Found existing Wallet: $WALLET_ID\n\033[0m"
fi

# ----------------------------------------------------------------------
# STEP 1: CHECK BALANCE
# ----------------------------------------------------------------------
read -p "Press Enter to execute: Check Alice's initial balance..."
echo -e "\n\033[36m---[ STEP 1. CHECK ALICE'S BALANCE ]---\033[0m\n"
curl -s -X GET "$API_URL/wallets/$WALLET_ID" -H "Authorization: Bearer $JWT" | grep -o '"balances": {[^}]*}' || true

# ----------------------------------------------------------------------
# STEP 2: TOP-UP OFFINE FUNDS
# ----------------------------------------------------------------------
read -p "Press Enter to execute: Top up Alice's account (\$150 Online, \$50 Offline)..."
echo -e "\n\033[36m---[ STEP 2. TOP-UP ALICE'S ACCOUNT ]---\033[0m\n"
IDEMP_KEY=$(uuidgen)
TOPUP_BODY="{\"amount_cents\": 20000, \"offline_allocation_cents\": 5000, \"wallet_id\": \"$WALLET_ID\", \"source\": {\"type\": \"card\", \"id\": \"tok_mastercard\"}}"
curl -s -X POST "$API_URL/topups" -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -H "Idempotency-Key: $IDEMP_KEY" -d "$TOPUP_BODY" | grep -o '"amount_cents": [0-9]*\|"offline_allocation_cents": [0-9]*\|"status": "[^"]*"' || true

# ----------------------------------------------------------------------
# STEP 3: CHECK BALANCE AGAIN
# ----------------------------------------------------------------------
read -p "Press Enter to execute: Verify top-up applied to offline balance..."
echo -e "\n\033[36m---[ STEP 3. CHECK ALICE'S BALANCE AFTER TOP-UP ]---\033[0m\n"
curl -s -X GET "$API_URL/wallets/$WALLET_ID" -H "Authorization: Bearer $JWT" | grep -o '"balances": {[^}]*}' || true

# ----------------------------------------------------------------------
# STEP 4: GENERATE OTP
# ----------------------------------------------------------------------
read -p "Press Enter to execute: Generate 16-Digit Emergency OTP to buy a \$5.00 Coffee... "
echo -e "\n\033[36m---[ STEP 4. GENERATE 16-DIGIT EMERGENCY OTP (\$5.00) ]---\033[0m\n"
IDEMP_KEY=$(uuidgen)
EMERGENCY_BODY="{\"wallet_id\": \"$WALLET_ID\", \"amount_cents\": 500}"
EMERGENCY_RESULT=$(curl -s -X POST "$API_URL/payments/emergency" -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -H "Idempotency-Key: $IDEMP_KEY" -d "$EMERGENCY_BODY")
OTP_CODE=$(echo "$EMERGENCY_RESULT" | grep -o '"otp_code": "[^"]*' | grep -o '[^"]*$' || true)

echo -e "\n\033[32m🚨🚨🚨 ALICE'S EMERGENCY CODE GENERATED 🚨🚨🚨\033[0m"
echo -e "\033[97mPayment Amount: \$5.00\033[0m"
echo -e "\033[31m16-Digit Code : ====================\033[0m"
echo -e "\033[31m                 $OTP_CODE\033[0m"
echo -e "\033[31m====================\033[0m\n"
echo -e "\033[33m👉 INSTRUCTIONS FOR JUDGES:\033[0m"
echo -e "\033[33m   1. Open merchant_pos.html in your browser\033[0m"
echo -e "\033[33m   2. Type '5.00' into the Amount input\033[0m"
echo -e "\033[33m   3. Type '$OTP_CODE' into the Code input\033[0m"
echo -e "\033[33m   4. Click 'Verify & Settle Payment'!\033[0m"

# ----------------------------------------------------------------------
# STEP 5: POST-PAYMENT BALANCE
# ----------------------------------------------------------------------
read -p "
Press Enter AFTER Bob has settled the payment on the POS to check Alice's remaining balance..."
echo -e "\n\033[36m---[ STEP 5. CHECK ALICE'S BALANCE POST-PAYMENT ]---\033[0m\n"
curl -s -X GET "$API_URL/wallets/$WALLET_ID" -H "Authorization: Bearer $JWT" | grep -o '"balances": {[^}]*}' || true

echo -e "\n\033[32m✅ Demo Complete!\033[0m"
