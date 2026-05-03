import os
import sys

from iat.transfer import send_iat


ESCROW_WALLET = os.getenv("IAT_ESCROW_WALLET")
KEYPAIR_PATH = os.getenv("IAT_BUYER_KEYPAIR", "buyer-keypair.json")


if len(sys.argv) < 3:
    print("Usage:")
    print("PYTHONPATH=. python3 examples/stake_agent.py <agent_id> <amount_iat>")
    sys.exit(1)


agent_id = sys.argv[1]
amount = float(sys.argv[2])

if not ESCROW_WALLET:
    raise SystemExit("Missing IAT_ESCROW_WALLET env var")

memo = f"STAKE:{agent_id}"

tx = send_iat(
    KEYPAIR_PATH,
    ESCROW_WALLET,
    amount,
    memo_text=memo,
)

print("Stake sent")
print("agent_id:", agent_id)
print("amount:", amount)
print("memo:", memo)
print("tx_signature:", tx)
