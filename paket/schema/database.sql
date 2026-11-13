-- Skema referensi (PostgreSQL). Tim boleh menyesuaikan.
CREATE TABLE entity (
  id SERIAL PRIMARY KEY, code VARCHAR(5) UNIQUE NOT NULL,      -- QDI / QKI
  legal_name TEXT NOT NULL, former_name TEXT, npwp16 CHAR(16) NOT NULL, nitku CHAR(22) NOT NULL,
  report_title TEXT NOT NULL, maker_name TEXT, maker_title TEXT, reviewer_name TEXT, reviewer_title TEXT
);
CREATE TABLE tax_object_code (
  code VARCHAR(12) PRIMARY KEY, name TEXT NOT NULL, tax_type VARCHAR(20) NOT NULL, -- PS23 / PS4_2 / PS21
  is_final BOOLEAN NOT NULL, rate NUMERIC(6,4) NOT NULL, verified_on DATE
);
CREATE TABLE vendor (
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, npwp_display TEXT, npwp16 CHAR(16) NOT NULL, nitku CHAR(22) NOT NULL,
  default_service TEXT, default_kop VARCHAR(12) REFERENCES tax_object_code(code), default_section VARCHAR(30),
  is_qris BOOLEAN DEFAULT FALSE, invoice_pattern TEXT, active BOOLEAN DEFAULT TRUE,
  withhold_pph23 BOOLEAN DEFAULT TRUE, is_recurring BOOLEAN DEFAULT FALSE, aliases TEXT[],  -- untuk autocomplete (mis. 'rintis','rts')
  auto_rules JSONB  -- aturan khusus: section/notes berdasarkan kata kunci item faktur
);
CREATE TABLE period (
  id SERIAL PRIMARY KEY, entity_id INT REFERENCES entity(id), month SMALLINT NOT NULL, year SMALLINT NOT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'DRAFT',   -- DRAFT / REVIEWED / LOCKED
  pph21_total NUMERIC(18,2) DEFAULT 0, signature_city TEXT DEFAULT 'Jakarta',
  signature_date DATE,  -- NULL = 'Hari ini' (tanggal WIB saat PDF dibuat); terisi = tanggal pilihan user, dipakai ulang saat regenerate reviewed_by TEXT, reviewed_at TIMESTAMPTZ,
  UNIQUE (entity_id, month, year)
);
CREATE TABLE tax_invoice (               -- faktur pajak masukan
  id SERIAL PRIMARY KEY, serial_no CHAR(17) UNIQUE NOT NULL, seller_npwp16 CHAR(16), buyer_npwp16 CHAR(16),
  seller_name TEXT, invoice_date DATE, sale_amount NUMERIC(18,2), vat_base NUMERIC(18,2), vat NUMERIC(18,2),
  reference TEXT, items JSONB, file_path TEXT, uploaded_by TEXT, uploaded_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE transaction (
  id SERIAL PRIMARY KEY, period_id INT REFERENCES period(id), section VARCHAR(30) NOT NULL, -- PPH23 / PPH23_QRIS / FINAL_4_2 / PPH21_FREELANCE
  sort_order INT, invoice_date DATE NOT NULL, invoice_no TEXT NOT NULL, vendor_id INT REFERENCES vendor(id),
  npwp_display TEXT, description TEXT, service_type TEXT, kop VARCHAR(12) REFERENCES tax_object_code(code),
  dpp NUMERIC(18,2) NOT NULL, rate NUMERIC(6,4) NOT NULL, tax_amount NUMERIC(18,4) GENERATED ALWAYS AS (dpp*rate) STORED,
  withholding_date DATE NOT NULL, tax_invoice_id INT REFERENCES tax_invoice(id), match_status VARCHAR(20), draft_status VARCHAR(20) DEFAULT 'CONFIRMED', -- PERLU_KONFIRMASI / CONFIRMED
  source VARCHAR(12), -- MANUAL / FAKTUR / RUTIN / BULK
  bupot_no TEXT, bupot_status VARCHAR(20), bupot_tte_status VARCHAR(20), reported_in_spt BOOLEAN, bupot_imported_at TIMESTAMPTZ, paid_date DATE, bukpot_sent TEXT, bukpot_email_date DATE, notes TEXT,
  created_by TEXT, created_at TIMESTAMPTZ DEFAULT now(), updated_by TEXT, updated_at TIMESTAMPTZ,
  UNIQUE (vendor_id, invoice_no)
);
CREATE TABLE signer (                     -- daftar penanda tangan (PRD 7.2.1)
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL, email TEXT, entity_id INT REFERENCES entity(id),
  signature_image_path TEXT, active BOOLEAN DEFAULT TRUE
);
CREATE TABLE entity_stamp (id SERIAL PRIMARY KEY, entity_id INT REFERENCES entity(id), image_path TEXT);
CREATE TABLE signature_preset (            -- susunan blok ttd per entitas
  id SERIAL PRIMARY KEY, entity_id INT REFERENCES entity(id), name TEXT, is_default BOOLEAN DEFAULT FALSE,
  city TEXT DEFAULT 'Jakarta',
  blocks JSONB NOT NULL  -- [{"order":1,"label":"Dibuat oleh","signer_id":1,"mode":"BLANK|IMAGE|IMAGE_STAMP","requires_approval":false}, ...] maks 4
);
CREATE TABLE output_log (
  id SERIAL PRIMARY KEY, period_id INT REFERENCES period(id), kind VARCHAR(10), -- XML / PDF / XLSX / EMAIL
  version INT, file_path TEXT, sha256 CHAR(64), signature_snapshot JSONB, recipients TEXT, status TEXT, created_by TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE bupot_import (              -- upload export data pemotongan Coretax (PRD 7.4)
  id SERIAL PRIMARY KEY, entity_id INT REFERENCES entity(id), file_path TEXT, rows_total INT, rows_matched INT,
  result JSONB, imported_by TEXT, imported_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY, table_name TEXT, row_id INT, action TEXT, old_value JSONB, new_value JSONB,
  actor TEXT, at TIMESTAMPTZ DEFAULT now()
);
