"""Trace the GF(2^8) generator sequence to find cycle length."""
x = 1
seen = {}
for i in range(260):
    if x in seen and x != 0:
        print(f"Cycle! x={x} first seen at i={seen[x]}, now at i={i}")
        print(f"Cycle length: {i - seen[x]}")
        break
    seen[x] = i
    
    # xtime: multiply by 2 in GF(2^8) with poly 0x11B
    carry = x & 0x80
    x = (x << 1) & 0xFF
    if carry:
        x ^= 0x1B

print(f"\nTotal elements seen: {len(seen)}")
print(f"Is 3 in sequence? {3 in seen}")
if 3 in seen:
    print(f"  3 first appears at step {seen[3]}")
print(f"Is 1 in sequence? {1 in seen}")
if 1 in seen:
    print(f"  1 first appears at step {seen[1]}")

# Check: what is x after 255 steps from 1?
x = 1
for i in range(255):
    carry = x & 0x80
    x = (x << 1) & 0xFF
    if carry:
        x ^= 0x1B
print(f"\n2^255 = {x} (should be 1 if primitive)")
