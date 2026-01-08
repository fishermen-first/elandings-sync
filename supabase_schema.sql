-- eLandings Sync - Supabase Schema
-- Run this SQL in your Supabase SQL Editor to create the required tables.

-- Table 1: Main landing reports
CREATE TABLE landing_reports (
  id BIGINT PRIMARY KEY,                           -- landing_report_id from eLandings
  report_type TEXT,                                 -- G, S, I, etc.
  report_type_name TEXT,                            -- "Groundfish", "Shellfish", etc.
  status TEXT,                                      -- status code (8 = Final)
  status_desc TEXT,                                 -- "Final Report Submitted"
  vessel_adfg_number TEXT,                          -- ADF&G vessel number
  vessel_name TEXT,                                 -- vessel name
  port_code TEXT,                                   -- port code (e.g., "COR")
  port_name TEXT,                                   -- port name (e.g., "Cordova")
  gear_code TEXT,                                   -- gear code
  gear_name TEXT,                                   -- gear name (e.g., "Longline")
  date_of_landing DATE,                             -- landing date
  date_fishing_began DATE,                          -- fishing start date
  crew_size INT,                                    -- number of crew
  processor_code TEXT,                              -- processor code
  processor_name TEXT,                              -- processor name
  fish_ticket_number TEXT,                          -- primary fish ticket number
  data_entry_user TEXT,                             -- user who entered data
  data_entry_date TIMESTAMPTZ,                      -- when data was entered
  last_change_user TEXT,                            -- user who last modified
  last_change_date TIMESTAMPTZ,                     -- last modification timestamp
  raw_json JSONB,                                   -- full original report for reference
  created_at TIMESTAMPTZ DEFAULT NOW(),             -- when synced to Supabase
  updated_at TIMESTAMPTZ DEFAULT NOW()              -- when last updated in Supabase
);

-- Table 2: Line items (catch details)
CREATE TABLE landing_report_items (
  id SERIAL PRIMARY KEY,
  landing_report_id BIGINT REFERENCES landing_reports(id) ON DELETE CASCADE,
  item_number INT,                                  -- line item number within report
  species_code TEXT,                                -- species code (e.g., "200" for Halibut)
  species_name TEXT,                                -- species name (e.g., "Halibut")
  weight DECIMAL(12,4),                             -- weight in pounds
  condition_code TEXT,                              -- condition code (e.g., "4" for Gutted)
  condition_name TEXT,                              -- condition name
  disposition_code TEXT,                            -- disposition code (e.g., "60" for Sold)
  disposition_name TEXT,                            -- disposition name
  fish_ticket_number TEXT,                          -- fish ticket for this item
  UNIQUE(landing_report_id, item_number)
);

-- Table 3: Statistical areas
CREATE TABLE landing_report_stat_areas (
  id SERIAL PRIMARY KEY,
  landing_report_id BIGINT REFERENCES landing_reports(id) ON DELETE CASCADE,
  item_number INT,                                  -- stat area item number
  stat_area TEXT,                                   -- ADF&G stat area (e.g., "365801")
  fed_area TEXT,                                    -- Federal area (e.g., "650")
  iphc_area TEXT,                                   -- IPHC regulatory area (e.g., "2C", "3A")
  percent INT,                                      -- percentage of catch from this area
  UNIQUE(landing_report_id, item_number)
);

-- Table 4: Sync state (singleton)
CREATE TABLE sync_state (
  id INT PRIMARY KEY DEFAULT 1,                     -- always 1 (singleton)
  last_sync TIMESTAMPTZ,                            -- when last sync completed
  CHECK (id = 1)                                    -- ensure only one row
);

-- Initialize sync_state with empty row
INSERT INTO sync_state (id, last_sync) VALUES (1, NULL);

-- Indexes for common queries
CREATE INDEX idx_landing_reports_vessel ON landing_reports(vessel_adfg_number);
CREATE INDEX idx_landing_reports_date ON landing_reports(date_of_landing);
CREATE INDEX idx_landing_reports_port ON landing_reports(port_code);
CREATE INDEX idx_landing_reports_status ON landing_reports(status);
CREATE INDEX idx_landing_reports_type ON landing_reports(report_type);

CREATE INDEX idx_items_report_id ON landing_report_items(landing_report_id);
CREATE INDEX idx_items_species ON landing_report_items(species_code);
CREATE INDEX idx_items_fish_ticket ON landing_report_items(fish_ticket_number);

CREATE INDEX idx_stat_areas_report_id ON landing_report_stat_areas(landing_report_id);
CREATE INDEX idx_stat_areas_iphc ON landing_report_stat_areas(iphc_area);

-- Enable Row Level Security (optional, recommended for production)
-- ALTER TABLE landing_reports ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE landing_report_items ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE landing_report_stat_areas ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE sync_state ENABLE ROW LEVEL SECURITY;

-- Create policies as needed for your authentication setup
-- Example: Allow authenticated users to read all data
-- CREATE POLICY "Allow authenticated read" ON landing_reports FOR SELECT TO authenticated USING (true);
