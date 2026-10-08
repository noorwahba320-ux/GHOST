-- Ghost Panel commercial virtual-number and inbound messaging schema.
-- Apply through Supabase migrations; RLS is enabled on all public tables.
create table public.ghost_clients (
 id bigint generated always as identity primary key, name text not null, email text, company text,
 external_ref text unique, status text not null default 'active' check(status in ('active','suspended','closed')),
 balance numeric(18,6) not null default 0 check(balance >= 0), currency char(3) not null default 'USD',
 created_at timestamptz not null default now()
);
create table public.ghost_providers (
 id bigint generated always as identity primary key, name text not null, slug text not null unique,
 protocol text not null default 'webhook', endpoint_url text, webhook_secret_hash text,
 status text not null default 'active' check(status in ('active','inactive','suspended')),
 notes text, created_at timestamptz not null default now()
);
create table public.ghost_number_ranges (
 id bigint generated always as identity primary key,
 provider_id bigint references public.ghost_providers(id) on delete set null,
 name text not null, country text not null, prefix text not null, operator text,
 currency char(3) not null default 'USD', monthly_price numeric(18,6) not null default 0 check(monthly_price >= 0),
 status text not null default 'active', created_at timestamptz not null default now()
);
create table public.ghost_phone_numbers (
 id bigint generated always as identity primary key,
 range_id bigint references public.ghost_number_ranges(id) on delete set null,
 provider_id bigint references public.ghost_providers(id) on delete set null,
 client_id bigint references public.ghost_clients(id) on delete set null,
 number text not null unique, country text not null, operator text,
 status text not null default 'available' check(status in ('available','assigned','suspended','retired')),
 currency char(3) not null default 'USD', monthly_price numeric(18,6) not null default 0 check(monthly_price >= 0),
 assigned_at timestamptz, activated_at timestamptz, created_at timestamptz not null default now()
);
create table public.ghost_messages (
 id bigint generated always as identity primary key,
 provider_id bigint references public.ghost_providers(id) on delete set null,
 phone_number_id bigint references public.ghost_phone_numbers(id) on delete set null,
 client_id bigint references public.ghost_clients(id) on delete set null,
 external_id text unique, sender text, destination text not null, body text not null,
 status text not null default 'received', received_at timestamptz not null default now()
);
create table public.ghost_cdr (
 id bigint generated always as identity primary key,
 message_id bigint references public.ghost_messages(id) on delete set null,
 client_id bigint references public.ghost_clients(id) on delete set null,
 phone_number_id bigint references public.ghost_phone_numbers(id) on delete set null,
 event_type text not null, units numeric(18,6) not null default 1,
 unit_price numeric(18,6) not null default 0, amount numeric(18,6) not null default 0,
 currency char(3) not null default 'USD', metadata_json jsonb not null default '{}'::jsonb,
 occurred_at timestamptz not null default now()
);
create table public.ghost_ledger (
 id bigint generated always as identity primary key,
 client_id bigint not null references public.ghost_clients(id) on delete cascade,
 entry_type text not null check(entry_type in ('credit','charge','refund','adjustment')),
 amount numeric(18,6) not null, currency char(3) not null default 'USD',
 reference text, description text, created_at timestamptz not null default now()
);
create table public.ghost_payment_requests (
 id bigint generated always as identity primary key,
 client_id bigint not null references public.ghost_clients(id) on delete cascade,
 amount numeric(18,6) not null check(amount > 0), currency char(3) not null default 'USD',
 method text not null, reference text,
 status text not null default 'pending' check(status in ('pending','approved','rejected','cancelled')),
 notes text, created_at timestamptz not null default now(), processed_at timestamptz
);
create table public.ghost_api_keys (
 id bigint generated always as identity primary key,
 client_id bigint not null references public.ghost_clients(id) on delete cascade,
 label text not null, token_hash text not null unique, token_prefix text not null,
 last_used_at timestamptz, revoked_at timestamptz, created_at timestamptz not null default now()
);
create table public.ghost_audit_events (
 id bigint generated always as identity primary key, actor text not null, action text not null,
 entity_type text, entity_id text, ip_address inet, detail text, created_at timestamptz not null default now()
);
create table public.ghost_settings (
 key text primary key, value text, updated_at timestamptz not null default now()
);
create index ghost_phone_numbers_status_idx on public.ghost_phone_numbers(status);
create index ghost_phone_numbers_country_idx on public.ghost_phone_numbers(country);
create index ghost_messages_received_idx on public.ghost_messages(received_at desc);
create index ghost_messages_client_idx on public.ghost_messages(client_id);
create index ghost_cdr_occurred_idx on public.ghost_cdr(occurred_at desc);
create index ghost_ledger_client_created_idx on public.ghost_ledger(client_id,created_at desc);
create index ghost_audit_created_idx on public.ghost_audit_events(created_at desc);
alter table public.ghost_clients enable row level security;
alter table public.ghost_providers enable row level security;
alter table public.ghost_number_ranges enable row level security;
alter table public.ghost_phone_numbers enable row level security;
alter table public.ghost_messages enable row level security;
alter table public.ghost_cdr enable row level security;
alter table public.ghost_ledger enable row level security;
alter table public.ghost_payment_requests enable row level security;
alter table public.ghost_api_keys enable row level security;
alter table public.ghost_audit_events enable row level security;
alter table public.ghost_settings enable row level security;
