ALTER TABLE jobs ADD COLUMN input_uploaded INTEGER NOT NULL DEFAULT 1 CHECK (input_uploaded IN (0, 1));
