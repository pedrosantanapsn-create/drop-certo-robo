-- Ajudante do PC: pedidos de link (ex.: meli.la) que só o navegador logado da dona consegue gerar.
-- Rode UMA vez no Supabase: SQL Editor → cole tudo → Run.
create table if not exists public.ajudante_pedidos (
  id uuid primary key default gen_random_uuid(),
  loja text not null default 'ml',
  chave text not null unique,
  url text not null default '',
  dados jsonb not null default '{}'::jsonb,
  link text,
  status text not null default 'pendente',
  erro text,
  criado_em timestamptz not null default now(),
  feito_em timestamptz
);
create index if not exists ajudante_pedidos_status_idx on public.ajudante_pedidos (status, criado_em);

-- A senha do ajudante fica num esquema que a API pública não enxerga.
create schema if not exists privado;
revoke all on schema privado from anon, authenticated, public;
create table if not exists privado.ajudante_segredo (
  id int primary key default 1 check (id = 1),
  chave text not null default replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '')
);
insert into privado.ajudante_segredo (id) values (1) on conflict (id) do nothing;
revoke all on privado.ajudante_segredo from anon, authenticated, public;

create or replace function public.ajudante_ok() returns boolean
language sql stable security definer set search_path = ''
as $$
  select coalesce(
    (nullif(current_setting('request.headers', true), '')::json ->> 'x-ajudante-chave')
      = (select s.chave from privado.ajudante_segredo s where s.id = 1),
    false);
$$;
revoke all on function public.ajudante_ok() from public;
grant execute on function public.ajudante_ok() to anon, authenticated;

-- Só quem manda a senha do ajudante lê e atualiza os pedidos (o site público não vê nada).
alter table public.ajudante_pedidos enable row level security;
drop policy if exists ajudante_le on public.ajudante_pedidos;
drop policy if exists ajudante_atualiza on public.ajudante_pedidos;
drop policy if exists ajudante_insere on public.ajudante_pedidos;
create policy ajudante_le on public.ajudante_pedidos for select to anon using (public.ajudante_ok());
create policy ajudante_atualiza on public.ajudante_pedidos for update to anon
  using (public.ajudante_ok()) with check (public.ajudante_ok());
create policy ajudante_insere on public.ajudante_pedidos for insert to anon
  with check (public.ajudante_ok() and loja = '_sistema');
grant select, insert, update on public.ajudante_pedidos to anon;

-- Mostra a senha do ajudante (copie e cole no arquivo senha.txt da pasta do ajudante):
select chave as senha_do_ajudante from privado.ajudante_segredo;
