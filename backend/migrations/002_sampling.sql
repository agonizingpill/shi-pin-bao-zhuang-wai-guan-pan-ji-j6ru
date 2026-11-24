CREATE TABLE IF NOT EXISTS sample_plan (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id bigint NOT NULL UNIQUE REFERENCES pack_lot(id),
    threshold double precision NOT NULL DEFAULT 0.02 CHECK (threshold > 0 AND threshold < 1),
    confidence double precision NOT NULL DEFAULT 0.95 CHECK (confidence > 0 AND confidence < 1),
    state text NOT NULL DEFAULT 'sampling' CHECK (state IN
        ('sampling', 'ready', 'full_inspection', 'signed', 'rejected')),
    created_by text NOT NULL REFERENCES staff(username),
    created_at timestamptz NOT NULL DEFAULT now(),
    signed_by text REFERENCES staff(username),
    signed_at timestamptz,
    basis jsonb
);
CREATE TABLE IF NOT EXISTS sample_pallet (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id bigint NOT NULL REFERENCES sample_plan(id),
    label text NOT NULL,
    units integer NOT NULL CHECK (units > 0),
    state text NOT NULL DEFAULT 'sampling' CHECK (state IN ('sampling', 'full_inspection')),
    conclusion text CHECK (conclusion IN ('pass', 'fail')),
    UNIQUE (plan_id, label)
);
CREATE TABLE IF NOT EXISTS sample_round (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pallet_id bigint NOT NULL REFERENCES sample_pallet(id),
    round_no integer NOT NULL CHECK (round_no > 0),
    draw_size integer NOT NULL CHECK (draw_size > 0),
    seed text NOT NULL,
    kind text NOT NULL DEFAULT 'sample' CHECK (kind IN ('sample', 'full')),
    created_by text NOT NULL REFERENCES staff(username),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (pallet_id, round_no)
);
CREATE TABLE IF NOT EXISTS sample_item (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    round_id bigint NOT NULL REFERENCES sample_round(id),
    pallet_id bigint NOT NULL REFERENCES sample_pallet(id),
    item_no integer NOT NULL CHECK (item_no > 0),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'judged')),
    grade char(1) CHECK (grade IN ('A', 'B', 'C')),
    channels jsonb,
    input_sha256 text,
    judged_by text REFERENCES staff(username),
    judged_at timestamptz,
    UNIQUE (pallet_id, item_no)
);
CREATE INDEX IF NOT EXISTS pending_items ON sample_item(pallet_id) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS round_items ON sample_item(round_id);
