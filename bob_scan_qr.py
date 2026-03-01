import os
import sys

# Mac specific fix for pyzbar not finding the brew installed zbar dylib
if sys.platform == "darwin":
    os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib:" + os.environ.get("DYLD_LIBRARY_PATH", "")

import cv2
import json
import urllib.request
import urllib.error
from pyzbar.pyzbar import decode

API_URL = "http://localhost:8000"
BOB_API_KEY = "sk_test_1234567890abcdef1234567890abcdef"
CRED_FILE = "demo_creds.env"

def load_bob_wallet_id():
    if not os.path.exists(CRED_FILE):
        return None
    with open(CRED_FILE, "r") as f:
        for line in f:
            if "BOB_WALLET_ID=" in line:
                return line.strip().split("=", 1)[1]
    return None

BOB_WALLET_ID = load_bob_wallet_id()

def scan_qr():
    print("Starting webcam... Please hold Alice's QR code up to the camera.")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return None

    qr_data = None
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # Optional: flip horizontally for a mirror effect so it's easier to aim
        frame = cv2.flip(frame, 1)

        # Draw a box indicating where to aim
        height, width, _ = frame.shape
        cv2.rectangle(frame, (width//2 - 150, height//2 - 150), 
                      (width//2 + 150, height//2 + 150), (255, 0, 0), 2)
        cv2.putText(frame, "Hold QR Code Here", (width//2 - 100, height//2 - 170), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        
        # Decode any QR codes in the current frame
        decoded_objects = decode(frame)
        for obj in decoded_objects:
            qr_data = obj.data.decode("utf-8")
            
            # Draw a green polygon around the detected QR code
            points = obj.polygon
            if len(points) == 4:
                pts = [(p.x, p.y) for p in points]
                cv2.polylines(frame, [__import__('numpy').array(pts)], True, (0, 255, 0), 3)
            
            cv2.putText(frame, "Scanned!", (obj.rect.left, obj.rect.top - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 3)
                        
            break  # Break out of inner loop once we find a code

        cv2.imshow("Bob's POS Offline QR Scanner", frame)
        
        # Wait for 'q' to quit, or exit automatically if standard code is found
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or qr_data:
            break

    cap.release()
    cv2.destroyAllWindows()
    return qr_data

def settle_payment(amount_cents, otp_code):
    print(f"\nContacting Backend to settle ${amount_cents/100:.2f}...")
    
    payload = {
        "merchant_id": "merchant_bob",
        "amount_cents": amount_cents,
        "otp_code": otp_code,
        "payee_wallet_id": BOB_WALLET_ID,
    }
    
    req = urllib.request.Request(
        f"{API_URL}/settlements/emergency",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": BOB_API_KEY
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            dollars = data["net_cents"] / 100
            print("\n✅ Payment Settled Successfully!")
            print(f"   Net amount deposited: ${dollars:.2f}")
            print("   The cryptographic Secure Element signature was verified offline.")
            if data.get("payee_wallet") and data["payee_wallet"].get("new_online_balance_cents") is not None:
                bob_bal = data["payee_wallet"]["new_online_balance_cents"] / 100
                print(f"   💰 Bob's new wallet balance: ${bob_bal:.2f}")
    except urllib.error.HTTPError as e:
        err_out = e.read().decode('utf-8')
        try:
            err_json = json.loads(err_out)
            msg = err_json.get("detail", {}).get("error", {}).get("message", err_out)
        except:
            msg = err_out
        print("\n❌ Transaction Failed")
        print(f"   Reason: {msg}")
    except Exception as e:
        print(f"\n❌ Connection Error: {e}")

def main():
    print("="*40)
    print(" ☕ Bob's Coffee Local POS ☕ ")
    print("="*40)
    
    try:
        amount_str = input("Enter exactly how much to charge Alice (e.g. 5.00): $").strip()
        amount_cents = int(float(amount_str) * 100)
    except ValueError:
        print("Invalid amount entered. Exiting.")
        sys.exit(1)
        
    otp_code = scan_qr()
    
    if not otp_code:
        print("No QR code detected or user cancelled.")
        sys.exit(0)
        
    print(f"\nSuccessfully scanned 16-Digit Code: {otp_code}")
    settle_payment(amount_cents, otp_code)

if __name__ == "__main__":
    main()
