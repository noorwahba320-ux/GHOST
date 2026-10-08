# GHOST Panel

Commercial Virtual Numbers + Inbound SMS management panel built with Flask, PostgreSQL/Supabase, and Vercel-compatible Python runtime.

The rebuilt application is designed for lawful business messaging use. It does not provide OTP extraction, verification-bypass automation, or tooling intended to defeat third-party verification systems.

## Modules

- Dashboard
- Provider management
- Number Inventory
- Clients
- API Keys
- Inbound SMS webhooks
- CDR
- Billing / Ledger
- Audit log
- Vercel deployment
- Supabase/PostgreSQL

## Production architecture

Provider -> authenticated webhook -> GHOST -> Number Inventory -> Client -> CDR/Ledger
