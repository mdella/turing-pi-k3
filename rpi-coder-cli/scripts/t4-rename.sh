#!/usr/bin/env bash
# Test 4 — multi-file rename. ./t4-rename.sh <aider|goose>
# Fixture: calc_total defined in shop/pricing.py, used by cart.py and invoice.py, 2 test modules, README.
. "$(dirname "$0")/lib.sh"; H=$1; D=$ROOT/t4-$H
rm -rf "$D"; mkdir -p "$D/shop" "$D/tests"; cd "$D" || exit 1; git init -q
cat > shop/__init__.py <<'PY'
PY
cat > shop/pricing.py <<'PY'
def calc_total(items, tax_rate=0.0):
    """Sum price*qty for (price, qty) pairs and apply tax."""
    subtotal = sum(price * qty for price, qty in items)
    return round(subtotal * (1 + tax_rate), 2)
PY
cat > shop/cart.py <<'PY'
from shop.pricing import calc_total


class Cart:
    def __init__(self):
        self.items = []

    def add(self, price, qty=1):
        self.items.append((price, qty))

    def total(self, tax_rate=0.0):
        return calc_total(self.items, tax_rate)
PY
cat > shop/invoice.py <<'PY'
from shop import pricing


def render(items, tax_rate=0.0):
    total = pricing.calc_total(items, tax_rate)
    lines = [f"{qty} x {price:.2f}" for price, qty in items]
    return "\n".join(lines + [f"TOTAL {total:.2f}"])
PY
: > tests/__init__.py
cat > tests/test_pricing.py <<'PY'
import unittest
from shop.pricing import calc_total


class TestPricing(unittest.TestCase):
    def test_calc_total(self):
        self.assertEqual(calc_total([(2.0, 3), (1.5, 2)]), 9.0)

    def test_calc_total_tax(self):
        self.assertEqual(calc_total([(10.0, 1)], 0.1), 11.0)
PY
cat > tests/test_cart.py <<'PY'
import unittest
from shop.cart import Cart
from shop.invoice import render


class TestCart(unittest.TestCase):
    def test_total(self):
        c = Cart(); c.add(2.0, 2); c.add(1.0)
        self.assertEqual(c.total(), 5.0)

    def test_invoice(self):
        self.assertTrue(render([(1.0, 2)]).endswith("TOTAL 2.00"))
PY
cat > README.md <<'PY'
# shop
`calc_total(items, tax_rate)` in `shop/pricing.py` computes an order total.
`Cart.total()` and `invoice.render()` both use `calc_total`.
PY
git add -A; git -c user.email=t@t -c user.name=t commit -qm fixture
P="Rename the function calc_total to compute_order_total everywhere in this repository: its definition, every call and import, the tests and the README. Then run: $UNITTEST  and make sure all tests pass."
proxy_start "$D/proxy.jsonl"
s=$(date +%s); agent "$H" "$P" "t4-$H-$(date +%s)" > "$D/agent.log" 2>&1; rc=$?; w=$(( $(date +%s)-s ))
proxy_stop
left=$(grep -rn calc_total --include='*.py' --include='*.md' . | grep -v '^./\.aider' | wc -l)
new=$(grep -rln compute_order_total --include='*.py' --include='*.md' . | grep -v '^./\.aider' | wc -l)
echo "T4 $H rc=$rc wall=${w}s leftovers=$left files_with_new_name=$new tests=$(check_tests) $(proxy_summary "$D/proxy.jsonl")"
