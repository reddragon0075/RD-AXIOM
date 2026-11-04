-- Migration: 20261027010000_concurrency_control.sql
-- Description: Optimistic Concurrency Control (OCC) versioning for duties to eliminate split-brain replay collisions

alter table public.duties add column if not exists version_id integer not null default 1;

create or replace function public.duty_increment_version()
returns trigger as $$
begin
  new.version_id := coalesce(old.version_id, 1) + 1;
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_duty_version on public.duties;
create trigger trg_duty_version
before update on public.duties
for each row
execute function public.duty_increment_version();

comment on column public.duties.version_id is 'Optimistic concurrency control version counter incremented on every duty mutation';
