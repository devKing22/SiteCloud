-- ===========================
-- Config Heaven migration
-- ===========================

-- configs extras
alter table if exists configs
  add column if not exists client text,
  add column if not exists server text,
  add column if not exists views bigint default 0;

-- profile username fields (na tabela de usuários da app)
create table if not exists profiles (
  user_id text primary key,
  username text unique,
  username_changed_at timestamptz default now()
);

-- reviews por config (1..5)
create table if not exists config_reviews (
  id bigserial primary key,
  config_id bigint not null,
  user_id text not null,
  stars int not null check (stars >= 1 and stars <= 5),
  created_at timestamptz default now(),
  unique(config_id, user_id)
);

-- comments por config
create table if not exists config_comments (
  id bigserial primary key,
  config_id bigint not null,
  user_id text not null,
  author text not null,
  comment text not null,
  created_at timestamptz default now()
);

create index if not exists idx_config_reviews_config_id on config_reviews(config_id);
create index if not exists idx_config_comments_config_id on config_comments(config_id);
