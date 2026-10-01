-- Per-user timezone preference for localized greetings and date/time rendering.
-- The browser and local SQLite fallback use the same IANA timezone contract.

alter table public.profiles
  add column if not exists timezone text not null default 'UTC';

update public.profiles
set timezone = 'UTC'
where trim(timezone) = '';

alter table public.profiles
  drop constraint if exists profiles_timezone_format;

alter table public.profiles
  add constraint profiles_timezone_format
  check (length(trim(timezone)) between 1 and 80);

-- Carry the signup selection through email-confirmation flows, where the
-- browser does not yet have an authenticated token with which to PATCH.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles(id, email, full_name, phone, account_type, timezone)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', ''),
    coalesce(new.raw_user_meta_data ->> 'phone', ''),
    nullif(new.raw_user_meta_data ->> 'account_type', '')::public.account_type,
    coalesce(nullif(new.raw_user_meta_data ->> 'timezone', ''), 'UTC')
  )
  on conflict (id) do update set
    email = excluded.email,
    full_name = case when excluded.full_name <> '' then excluded.full_name else public.profiles.full_name end,
    phone = case when excluded.phone <> '' then excluded.phone else public.profiles.phone end,
    account_type = coalesce(excluded.account_type, public.profiles.account_type),
    timezone = case when excluded.timezone <> 'UTC' then excluded.timezone else public.profiles.timezone end,
    updated_at = now();
  return new;
end;
$$;
