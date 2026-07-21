-- Trade outcome tracking: let the user record what actually happened to an
-- analyzed trade (did it get proposed / accepted / rejected / completed) plus a
-- free-text retrospective note. Columns are nullable — existing rows stay
-- "untracked" until the user sets an outcome. trade_history remains backend-only
-- (RLS on, no client policies); updates go through /trade/history/outcome.

alter table trade_history
  add column if not exists status             text,         -- null | proposed | accepted | rejected | completed
  add column if not exists outcome_note       text,         -- optional retrospective note
  add column if not exists outcome_updated_at timestamptz;  -- when the outcome was last set
