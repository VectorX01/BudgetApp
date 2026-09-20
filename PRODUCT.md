# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A single user — the owner — tracking their own money. A graduate student in the
New York / Jersey City area who moved into salaried work mid-2026 (NYU TA income
through Feb, RBC salary from late May). No second audience; nothing is shared or
published. Sessions are short and frequent: log a transaction, or check a number.

## Product Purpose

A personal ledger and dashboard over a single Google Sheet. It answers three
questions:

1. What do I owe and what do I hold, right now?
2. Month over month, how much am I earning and how much am I keeping?
3. What is my investment portfolio actually worth versus what I put into it?

Success is that the owner trusts the numbers enough to stop opening the raw
spreadsheet.

## Positioning

Unlike an aggregator, nothing is linked to a bank. Every row is entered by hand,
which makes the ledger slow to fill but fully owned, auditable, and correct —
account balances currently reconcile to the cent against the real institutions.
That reconciliation is the product's core claim and must never regress.

## Operating Context

- Data lives in one Google Sheet, `Expense_Tracker`
  (`1MzP2q9xU4EMsqgBkpS4MphnFJCWbaePSp_ChjMzrcC4`), worksheet `Sheet1`.
- A second worksheet, `Copy of Sheet1`, is a stale Feb–Mar 2026 backup in an
  older format (positive expense amounts, blank `Transaction_Type`). It is not
  read by the app and must not become an input.
- Deployed on Streamlit Community Cloud behind account auth; the owner is the
  only viewer. Source: `github.com/VectorX01/BudgetApp`.
- Rows are entered both through the app sidebar and directly in the Sheet.
- Credit-card statement cycles do not align with calendar months, so the owner
  assigns each row a `Statement_Month` separately from its transaction date.

## Capabilities and Constraints

**Schema (`Sheet1`, 7 columns):** `Date`, `Description`, `Amount`, `Card`,
`Category`, `Statement_Month`, `Transaction_Type`.

**Sign convention:** `Amount` is stored signed. Expense negative, Income
positive, `Card Payment (Bank side)` negative, `Card Payment (Card side)`
positive. Every transfer is two rows that sum to zero, so summing the entire
sheet yields true net worth. As of 2026-09-20: 1,001 rows, 2025-12-03 →
2026-09-19, net worth $13,267.22.

**Accounts in use:** Checking, Savings, Marcus HYSA, Fidelity Cash Management,
Schwab Brokerage, Chase, Amex, Target, Samsung Card.
**Closed/archived:** Apple Card (245 rows of history, $0.00 balance), Discover,
Splitwise. History must remain queryable; they must not occupy balance tiles.

**Known data facts that constrain design:**

- `Statement_Month` is a bare month name with no year. The year is derivable
  from the transaction date (the statement falls 0–2 months after it); this
  resolves 998 of 1,001 rows cleanly.
- Transfer pairs do not reliably share a statement month — 8 pairs have their
  legs in different periods. Any money arithmetic must key on transaction date.
  `Statement_Month` remains valid only for "what is on this bill".
- Four Discover payoffs totalling $153.06 have no counter-leg (Discover was
  never tracked in `Sheet1`). Correct for net worth, invisible to expense views.
- The June Amex payment legs differ by $0.02 (3,227.15 in / 3,227.17 out).
- `Schwab Brokerage` currently reads $1,918.36, which is contributed cash plus
  $0.36 of dividends — cost basis, not market value. No market value exists
  anywhere in the data today.

**Confirmed product decisions (2026-09-20):**

- Income is sub-typed: Salary, Gift, Tax refund, Cashback, Interest, Dividend,
  Award/side, Opening balance.
- Merchant refunds and returns (34 rows, $1,506.37) offset the category they
  came from rather than counting as income. Cashback, interest, dividends and
  tax refunds stay income. 31 of those 34 rows are tagged `Other` and need a
  real category before the offset is meaningful.
- Portfolio valuation is recorded weekly as a market value **per account**, by
  hand. No holdings, tickers, share counts or price feeds — explicitly rejected
  as overkill.

## Evidence on Hand

Real, verified figures as of 2026-09-20 (no fabrication — all recomputed from
`Sheet1`):

- Balances: Checking $7.06, Savings $642.29, Marcus HYSA $10,727.51, Fidelity
  Brokerage $0.00, Fidelity Cash Management $575.03, Schwab Brokerage $1,918.36.
- Card dues: Chase $13.25, Amex $409.63, Target $40.14, Samsung $140.01.
- Net worth trajectory: −$673 (Dec 25) → $457 trough (end May 26) → $13,267 (Sep 26).
- Savings rate since salary began: Jun 64%, Jul 61%, Aug 73%, Sep 25% (partial).
- Income to date $43,003.68, of which $25,770.74 is salary.
- No market-value history exists. The portfolio tab has genuinely empty data
  until the owner logs the first weekly valuation; that empty state is real and
  must be designed, not faked.

## Product Principles

1. **Reconciliation is the product.** Any feature that could make a displayed
   balance disagree with the real institution is wrong, however useful it looks.
2. **Date is the unit of money; statement month is the unit of billing.** Never
   let the two swap roles.
3. **Entry effort is the binding constraint.** Every row is typed by hand, so
   reducing keystrokes and preventing entry mistakes beats adding analysis.
4. **Show cost basis and market value as separate facts.** Never let a
   contributed-cash figure masquerade as a portfolio value.
5. **Closed accounts keep their history and lose their real estate.**

## Accessibility & Inclusion

Single known user on desktop and phone. No established external requirement;
the practical need is that dense metric rows stay legible at phone width rather
than collapsing to unreadable columns.
