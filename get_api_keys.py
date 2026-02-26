"""
get_api_keys.py - Generate Polymarket CLOB API credentials from your private key

Run ONCE to get your API key/secret/passphrase:
    python get_api_keys.py

Then paste the output into your .env file.
"""
from dotenv import load_dotenv
import os
load_dotenv()

PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY", "")

if not PRIVATE_KEY:
    print("❌ Add POLY_PRIVATE_KEY to your .env first!")
    exit(1)

try:
    from py_clob_client.client import ClobClient
except ImportError:
    print("❌ Run: pip install py-clob-client")
    exit(1)

print("🔑 Generating Polymarket API credentials...")
print("   (This signs a message with your wallet — no funds moved)")
print()

try:
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=PRIVATE_KEY,
        chain_id=137,
    )
    creds = client.create_or_derive_api_key()
    print("✅ SUCCESS! Add these to your .env:")
    print()
    print(f"POLY_API_KEY={creds.api_key}")
    print(f"POLY_API_SECRET={creds.api_secret}")
    print(f"POLY_API_PASSPHRASE={creds.api_passphrase}")
    print()
    print("Done! Now run: python main.py")
except Exception as e:
    print(f"❌ Error: {e}")
    print("   Check that POLY_PRIVATE_KEY is correct (should start with 0x)")
