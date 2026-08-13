-- 0006: the known 2026-season driver pool per team (race-seat + reserve/
-- development drivers), used to default and validate the pre-race lineup
-- confirmation step (see utils/team_driver_pool.py) - the user reviews/edits
-- this before a live stream starts, since OpenF1's free-tier REST access
-- can't be relied on for a genuinely in-progress session's roster (it only
-- serves data outside F1's own 30-minutes-before/after "live" window).
--
-- driver_number/tla are left NULL for reserve drivers who have never held a
-- permanent F1 number - filled in by the user at confirmation time if that
-- driver actually substitutes in for a race.

CREATE TABLE IF NOT EXISTS team_driver_pool (
    id SERIAL PRIMARY KEY,
    season_year INTEGER NOT NULL,
    team_name VARCHAR(100) NOT NULL,
    driver_number INTEGER,
    tla VARCHAR(10),
    full_name VARCHAR(100) NOT NULL,
    is_reserve BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_team_driver_pool_entry UNIQUE (season_year, team_name, full_name)
);

CREATE INDEX IF NOT EXISTS idx_team_driver_pool_season_team ON team_driver_pool(season_year, team_name);

-- Race-seat lineup, 2026 season (22 drivers, 11 teams) - source: formula1.com
-- official driver-numbers announcement.
INSERT INTO team_driver_pool (season_year, team_name, driver_number, tla, full_name, is_reserve) VALUES
    (2026, 'McLaren', 1, 'NOR', 'Lando Norris', FALSE),
    (2026, 'McLaren', 81, 'PIA', 'Oscar Piastri', FALSE),
    (2026, 'Cadillac', 11, 'PER', 'Sergio Perez', FALSE),
    (2026, 'Cadillac', 77, 'BOT', 'Valtteri Bottas', FALSE),
    (2026, 'Red Bull Racing', 3, 'VER', 'Max Verstappen', FALSE),
    (2026, 'Red Bull Racing', 6, 'HAD', 'Isack Hadjar', FALSE),
    (2026, 'Ferrari', 16, 'LEC', 'Charles Leclerc', FALSE),
    (2026, 'Ferrari', 44, 'HAM', 'Lewis Hamilton', FALSE),
    (2026, 'Mercedes', 12, 'ANT', 'Kimi Antonelli', FALSE),
    (2026, 'Mercedes', 63, 'RUS', 'George Russell', FALSE),
    (2026, 'Aston Martin', 14, 'ALO', 'Fernando Alonso', FALSE),
    (2026, 'Aston Martin', 18, 'STR', 'Lance Stroll', FALSE),
    (2026, 'Audi', 5, 'BOR', 'Gabriel Bortoleto', FALSE),
    (2026, 'Audi', 27, 'HUL', 'Nico Hulkenberg', FALSE),
    (2026, 'Williams', 23, 'ALB', 'Alexander Albon', FALSE),
    (2026, 'Williams', 55, 'SAI', 'Carlos Sainz', FALSE),
    (2026, 'Racing Bulls', 30, 'LAW', 'Liam Lawson', FALSE),
    (2026, 'Racing Bulls', 41, 'LIN', 'Arvid Lindblad', FALSE),
    (2026, 'Alpine', 10, 'GAS', 'Pierre Gasly', FALSE),
    (2026, 'Alpine', 43, 'COL', 'Franco Colapinto', FALSE),
    (2026, 'Haas', 31, 'OCO', 'Esteban Ocon', FALSE),
    (2026, 'Haas', 87, 'BEA', 'Oliver Bearman', FALSE)
ON CONFLICT (season_year, team_name, full_name) DO NOTHING;

-- Reserve/development drivers, 2026 season - source: publicly reported team
-- announcements (see the driver_roster feature discussion for citations).
-- driver_number/tla are only populated where the driver has a well-established
-- permanent F1 number from a prior race stint; NULL otherwise (filled in by
-- the user at confirmation time if that driver actually substitutes in).
INSERT INTO team_driver_pool (season_year, team_name, driver_number, tla, full_name, is_reserve) VALUES
    (2026, 'Red Bull Racing', 22, 'TSU', 'Yuki Tsunoda', TRUE),
    (2026, 'Mercedes', NULL, NULL, 'Frederik Vesti', TRUE),
    (2026, 'McLaren', NULL, NULL, 'Leonardo Fornaroli', TRUE),
    (2026, 'McLaren', NULL, NULL, 'Pato O''Ward', TRUE),
    (2026, 'Ferrari', 99, 'GIO', 'Antonio Giovinazzi', TRUE),
    (2026, 'Williams', NULL, NULL, 'Luke Browning', TRUE),
    (2026, 'Alpine', NULL, NULL, 'Paul Aron', TRUE),
    (2026, 'Aston Martin', NULL, NULL, 'Jak Crawford', TRUE),
    (2026, 'Racing Bulls', NULL, NULL, 'Ayumu Iwasa', TRUE),
    (2026, 'Cadillac', 24, 'ZHO', 'Zhou Guanyu', TRUE),
    (2026, 'Haas', 7, 'DOO', 'Jack Doohan', TRUE),
    (2026, 'Haas', NULL, NULL, 'Ryo Hirakawa', TRUE)
ON CONFLICT (season_year, team_name, full_name) DO NOTHING;
