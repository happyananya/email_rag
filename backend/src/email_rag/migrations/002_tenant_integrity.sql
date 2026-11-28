-- Enforce the tenant/account relationships that the application already applies in every query.
-- These composite keys make a future application bug fail closed instead of accepting a row that
-- combines one user's user_id with another user's account_id.

ALTER TABLE email_accounts
    ADD CONSTRAINT email_accounts_id_user_unique UNIQUE (id, user_id);

ALTER TABLE emails
    ADD CONSTRAINT emails_account_user_fk
    FOREIGN KEY (account_id, user_id) REFERENCES email_accounts (id, user_id) ON DELETE CASCADE;

ALTER TABLE emails
    ADD CONSTRAINT emails_id_user_account_unique UNIQUE (id, user_id, account_id);

ALTER TABLE email_chunks
    ADD CONSTRAINT email_chunks_account_user_fk
    FOREIGN KEY (account_id, user_id) REFERENCES email_accounts (id, user_id) ON DELETE CASCADE;

ALTER TABLE email_chunks
    ADD CONSTRAINT email_chunks_email_tenant_fk
    FOREIGN KEY (email_id, user_id, account_id)
    REFERENCES emails (id, user_id, account_id) ON DELETE CASCADE;

ALTER TABLE summaries
    ADD CONSTRAINT summaries_account_user_fk
    FOREIGN KEY (account_id, user_id) REFERENCES email_accounts (id, user_id) ON DELETE CASCADE;

ALTER TABLE drafts
    ADD CONSTRAINT drafts_account_user_fk
    FOREIGN KEY (account_id, user_id) REFERENCES email_accounts (id, user_id) ON DELETE CASCADE;

ALTER TABLE action_items
    ADD CONSTRAINT action_items_account_user_fk
    FOREIGN KEY (account_id, user_id) REFERENCES email_accounts (id, user_id) ON DELETE CASCADE;

ALTER TABLE action_items
    ADD CONSTRAINT action_items_status_check CHECK (status IN ('open', 'done'));

-- Collapse any duplicates produced before this migration, preferring the oldest checklist item.
DELETE FROM action_items duplicate
USING action_items original
WHERE duplicate.user_id = original.user_id
  AND duplicate.account_id = original.account_id
  AND duplicate.thread_id = original.thread_id
  AND lower(duplicate.description) = lower(original.description)
  AND duplicate.owner IS NOT DISTINCT FROM original.owner
  AND duplicate.due_date IS NOT DISTINCT FROM original.due_date
  AND (duplicate.created_at, duplicate.id) > (original.created_at, original.id);

CREATE UNIQUE INDEX action_items_thread_content_unique
    ON action_items (user_id, account_id, thread_id, lower(description), owner, due_date)
    NULLS NOT DISTINCT;
