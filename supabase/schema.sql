-- Przetargi24 — schemat bazy dla kont i alertów e-mail.
--
-- Wklej całość do Supabase → SQL Editor → New query → Run.
-- Skrypt jest idempotentny: można go uruchomić ponownie po zmianach.
--
-- Zasada bezpieczeństwa: klucz `anon`, który trafia do statycznej strony,
-- jest z założenia publiczny. Dostęp do danych ogranicza wyłącznie Row Level
-- Security poniżej — każdy użytkownik widzi i zmienia tylko swoje wiersze.

-- === profile ==============================================================
-- Rozszerza wbudowaną tabelę auth.users o stan subskrypcji.

create table if not exists public.profile (
  id                      uuid primary key references auth.users (id) on delete cascade,
  email                   text        not null,
  -- Stan opłacania konta. Ustawiany wyłącznie przez webhook Stripe,
  -- działający kluczem serwisowym — użytkownik nie może go sobie zmienić.
  plan                    text        not null default 'free'
                          check (plan in ('free', 'premium')),
  premium_do              timestamptz,
  stripe_customer_id      text unique,
  utworzono               timestamptz not null default now()
);

comment on table public.profile is
  'Profil użytkownika i stan subskrypcji; pole plan zmienia tylko webhook Stripe.';

alter table public.profile enable row level security;

drop policy if exists "profil: własny odczyt" on public.profile;
create policy "profil: własny odczyt" on public.profile
  for select using (auth.uid() = id);

-- Celowo brak polityk insert/update/delete dla zalogowanych: profil zakłada
-- wyzwalacz, a plan zmienia wyłącznie klucz serwisowy (omija RLS).

-- Założenie profilu zaraz po rejestracji.
create or replace function public.utworz_profil()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profile (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists na_nowego_uzytkownika on auth.users;
create trigger na_nowego_uzytkownika
  after insert on auth.users
  for each row execute function public.utworz_profil();

-- === subskrypcje alertów ==================================================
-- Jeden wiersz to jeden zapisany filtr, na który użytkownik chce alertów.

create table if not exists public.alert (
  id            uuid primary key default gen_random_uuid(),
  uzytkownik    uuid        not null references public.profile (id) on delete cascade,
  nazwa         text        not null default 'Mój alert',
  -- Puste listy znaczą „bez ograniczenia w tym wymiarze”.
  kategorie     text[]      not null default '{}',
  frazy         text[]      not null default '{}',
  cpv           text[]      not null default '{}',
  wojewodztwa   text[]      not null default '{}',
  wartosc_min   numeric,
  aktywny       boolean     not null default true,
  utworzono     timestamptz not null default now(),
  ostatnia_wysylka timestamptz
);

comment on table public.alert is
  'Zapisany filtr użytkownika; automat wysyła e-mail o nowych pasujących ogłoszeniach.';

create index if not exists alert_uzytkownik_idx on public.alert (uzytkownik);
create index if not exists alert_aktywny_idx on public.alert (aktywny) where aktywny;

alter table public.alert enable row level security;

drop policy if exists "alert: własny odczyt" on public.alert;
create policy "alert: własny odczyt" on public.alert
  for select using (auth.uid() = uzytkownik);

drop policy if exists "alert: własny zapis" on public.alert;
create policy "alert: własny zapis" on public.alert
  for insert with check (auth.uid() = uzytkownik);

drop policy if exists "alert: własna zmiana" on public.alert;
create policy "alert: własna zmiana" on public.alert
  for update using (auth.uid() = uzytkownik) with check (auth.uid() = uzytkownik);

drop policy if exists "alert: własne usunięcie" on public.alert;
create policy "alert: własne usunięcie" on public.alert
  for delete using (auth.uid() = uzytkownik);

-- Limit dla kont darmowych pilnowany w bazie, nie w przeglądarce — inaczej
-- wystarczyłoby ominąć interfejs, żeby założyć dowolnie wiele alertów.
create or replace function public.pilnuj_limitu_alertow()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  ile   integer;
  plan_uzytkownika text;
begin
  select plan into plan_uzytkownika from public.profile where id = new.uzytkownik;
  if plan_uzytkownika = 'premium' then
    return new;
  end if;
  select count(*) into ile from public.alert where uzytkownik = new.uzytkownik;
  if ile >= 1 then
    raise exception 'Konto darmowe obsługuje jeden alert. Przejdź na premium, aby dodać kolejne.'
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists limit_alertow on public.alert;
create trigger limit_alertow
  before insert on public.alert
  for each row execute function public.pilnuj_limitu_alertow();

-- === dziennik wysyłek =====================================================
-- Chroni przed wysłaniem tego samego ogłoszenia dwa razy, gdy automat
-- uruchomi się kilka razy w ciągu dnia.

create table if not exists public.wyslane (
  alert       uuid        not null references public.alert (id) on delete cascade,
  ogloszenie  text        not null,
  wyslano     timestamptz not null default now(),
  primary key (alert, ogloszenie)
);

comment on table public.wyslane is
  'Które ogłoszenie poszło już w którym alercie — zabezpiecza przed duplikatem.';

alter table public.wyslane enable row level security;
-- Brak polityk: tabela obsługiwana wyłącznie kluczem serwisowym automatu.
