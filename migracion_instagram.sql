-- Tira "Seguinos en Instagram" con capturas reales de posteos/reels.
-- Pegá esto en tu base de datos y ya te aparece /admin/instagram para
-- cargar las capturas.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS instagram_posts (
  id INT AUTO_INCREMENT PRIMARY KEY,
  image_url VARCHAR(500) NOT NULL,
  link VARCHAR(255),
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
