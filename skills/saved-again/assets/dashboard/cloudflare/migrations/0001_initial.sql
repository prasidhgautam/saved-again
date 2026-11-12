CREATE TABLE IF NOT EXISTS categories(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  art TEXT NOT NULL,
  color TEXT NOT NULL,
  rank INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS posts(
  id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  category TEXT NOT NULL DEFAULT 'review',
  subcategory TEXT NOT NULL DEFAULT 'Unsorted',
  search_text TEXT NOT NULL DEFAULT '',
  favourite INTEGER NOT NULL DEFAULT 0,
  tried INTEGER NOT NULL DEFAULT 0,
  dismissed INTEGER NOT NULL DEFAULT 0,
  snoozed_until TEXT,
  notes TEXT NOT NULL DEFAULT '',
  manual_category INTEGER NOT NULL DEFAULT 0,
  revision INTEGER NOT NULL DEFAULT 0,
  updated TEXT NOT NULL,
  preview_key TEXT,
  preview_hash TEXT
);

CREATE INDEX IF NOT EXISTS posts_position ON posts(position);
CREATE INDEX IF NOT EXISTS posts_category ON posts(category,subcategory);
CREATE INDEX IF NOT EXISTS posts_state ON posts(favourite,tried,dismissed);

CREATE TABLE IF NOT EXISTS mutations(
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  patch TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_clients(
  id TEXT PRIMARY KEY,
  cursor INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_requests(
  id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO categories VALUES
('filmmaking','AI & Filmmaking','filmmaking.webp','#733325',0),
('marketing','Marketing','marketing.webp','#164b35',1),
('food','Food','food.webp','#984a23',2),
('technology','AI & Technology','technology.webp','#234b5d',3),
('places','Places & Experiences','places.webp','#42614b',4),
('learning','Learning & Ideas','learning.webp','#79562d',5),
('wellbeing','Fitness & Wellbeing','wellbeing.webp','#4f6640',6),
('style','Style & Everyday','style.webp','#76414c',7),
('entertainment','Cinema & Culture','entertainment.webp','#593b64',8),
('career','Career & Work','career.webp','#3d5068',9),
('review','Needs review','review.webp','#7f7562',10);
