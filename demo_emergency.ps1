# ======================================================================
# 🚀 DEFERRED API: 16-DIGIT EMERGENCY OFFLINE PAYMENT DEMO 🚀
# ======================================================================
$ErrorActionPreference = "Stop"
$API_URL = "http://localhost:8000"
$ENV_FILE = "demo_creds.env"

# ----------------------------------------------------------------------
# STEP 0: LOAD OR CREATE CREDENTIALS
# ----------------------------------------------------------------------
$JWT = $null
$WALLET_ID = $null

if (Test-Path $ENV_FILE) {
    Write-Host "Loading credentials from $ENV_FILE..." -ForegroundColor Cyan
    $envContent = Get-Content $ENV_FILE
    foreach ($line in $envContent) {
        if ($line -match "^ALICE_JWT=(.*)") { $JWT = $matches[1] }
        if ($line -match "^ALICE_WALLET_ID=(.*)") { $WALLET_ID = $matches[1] }
    }
}

if (-not $JWT -or -not $WALLET_ID) {
    Write-Host "Credentials missing. Generating new JWT and Wallet..." -ForegroundColor Yellow
    
    # 1. Generate a permanent JWT using the proper Auth endpoint
    $CustomerBody = @{ customer_id = "alice_demo_$(Get-Random)"; secret = "test_secret" } | ConvertTo-Json
    $TokenOutput = Invoke-RestMethod -Uri "$API_URL/auth/token" -Method Post -Headers @{ "Content-Type" = "application/json" } -Body $CustomerBody
    $JWT = $TokenOutput.access_token

    # 2. Create Wallet
    $WalletBody = @{ type="personal"; offline_allowance_cents=10000; customer_reference="alice_demo_ref_$(Get-Random)" } | ConvertTo-Json
    $WalletResult = Invoke-RestMethod -Uri "$API_URL/wallets" -Method Post -Headers @{"Authorization"="Bearer $JWT"; "Content-Type"="application/json"; "Idempotency-Key"=[guid]::NewGuid().ToString()} -Body $WalletBody
    $WALLET_ID = $WalletResult.id

    # 3. Save to env file permanently
    "ALICE_JWT=$JWT`nALICE_WALLET_ID=$WALLET_ID" | Set-Content $ENV_FILE
    Write-Host "✅ Created Wallet $WALLET_ID and saved to $ENV_FILE`n" -ForegroundColor Green
} else {
    Write-Host "✅ Found existing Wallet: $WALLET_ID`n" -ForegroundColor Green
}

# ----------------------------------------------------------------------
# STEP 1: CHECK BALANCE
# ----------------------------------------------------------------------
Read-Host "Press Enter to execute: Check Alice's initial balance..."
Write-Host "`n---[ STEP 1. CHECK ALICE'S BALANCE ]---`n" -ForegroundColor Cyan
Invoke-RestMethod -Uri "$API_URL/wallets/$WALLET_ID" -Method Get -Headers @{ "Authorization" = "Bearer $JWT" } | Select-Object -ExpandProperty balances | Format-List


# ----------------------------------------------------------------------
# STEP 2: TOP-UP OFFINE FUNDS
# ----------------------------------------------------------------------
Read-Host "Press Enter to execute: Top up Alice's account ($150 Online, $50 Offline)..."
Write-Host "`n---[ STEP 2. TOP-UP ALICE'S ACCOUNT ]---`n" -ForegroundColor Cyan
$TopUpBody = @{
    amount_cents = 20000
    offline_allocation_cents = 5000
    wallet_id = $WALLET_ID
    source = @{ type = "card"; id = "tok_mastercard" }
} | ConvertTo-Json

Invoke-RestMethod -Uri "$API_URL/topups" -Method Post -Headers @{ "Authorization" = "Bearer $JWT"; "Content-Type" = "application/json"; "Idempotency-Key" = [guid]::NewGuid().ToString() } -Body $TopUpBody | Select-Object id, status, amount_cents, offline_allocation_cents | Format-Table


# ----------------------------------------------------------------------
# STEP 3: CHECK BALANCE AGAIN
# ----------------------------------------------------------------------
Read-Host "Press Enter to execute: Verify top-up applied to offline balance..."
Write-Host "`n---[ STEP 3. CHECK ALICE'S BALANCE AFTER TOP-UP ]---`n" -ForegroundColor Cyan
Invoke-RestMethod -Uri "$API_URL/wallets/$WALLET_ID" -Method Get -Headers @{ "Authorization" = "Bearer $JWT" } | Select-Object -ExpandProperty balances | Format-List


# ----------------------------------------------------------------------
# STEP 4: GENERATE OTP
# ----------------------------------------------------------------------
Read-Host "Press Enter to execute: Generate 16-Digit Emergency OTP to buy a `$5.00 Coffee... "
Write-Host "`n---[ STEP 4. GENERATE 16-DIGIT EMERGENCY OTP (`$5.00) ]---`n" -ForegroundColor Cyan
$EmergencyPaymentBody = @{
    wallet_id = $WALLET_ID
    amount_cents = 500
} | ConvertTo-Json

$EmergencyResult = Invoke-RestMethod -Uri "$API_URL/payments/emergency" -Method Post -Headers @{ "Authorization" = "Bearer $JWT"; "Content-Type" = "application/json"; "Idempotency-Key" = [guid]::NewGuid().ToString() } -Body $EmergencyPaymentBody

Write-Host "`n🚨🚨🚨 ALICE'S EMERGENCY CODE GENERATED 🚨🚨🚨" -ForegroundColor Green
Write-Host "Payment Amount: `$5.00" -ForegroundColor White
Write-Host "16-Digit Code : $('=' * 20)" -ForegroundColor Red
Write-Host "                 $($EmergencyResult.otp_code)" -ForegroundColor Red
Write-Host "$('=' * 20)`n" -ForegroundColor Red
Write-Host "👉 INSTRUCTIONS FOR JUDGES:" -ForegroundColor Yellow
Write-Host "   1. Open merchant_pos.html in your browser" -ForegroundColor Yellow
Write-Host "   2. Type '5.00' into the Amount input" -ForegroundColor Yellow
Write-Host "   3. Type '$($EmergencyResult.otp_code)' into the Code input" -ForegroundColor Yellow
Write-Host "   4. Click 'Verify & Settle Payment'!" -ForegroundColor Yellow


# ----------------------------------------------------------------------
# STEP 5: POST-PAYMENT BALANCE
# ----------------------------------------------------------------------
Read-Host "`nPress Enter AFTER Bob has settled the payment on the POS to check Alice's remaining balance..."
Write-Host "`n---[ STEP 5. CHECK ALICE'S BALANCE POST-PAYMENT ]---`n" -ForegroundColor Cyan
Invoke-RestMethod -Uri "$API_URL/wallets/$WALLET_ID" -Method Get -Headers @{ "Authorization" = "Bearer $JWT" } | Select-Object -ExpandProperty balances | Format-List

Write-Host "`n✅ Demo Complete!" -ForegroundColor Green
