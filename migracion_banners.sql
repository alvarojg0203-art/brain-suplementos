-- Migración para los banners motivacionales ("Ganar masa muscular",
-- "Mejorar rendimiento", etc.) que llevan directo a los productos de
-- cada categoría. Es seguro correrlo: solo crea la tabla nueva, no toca
-- nada de lo que ya tenés cargado.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS goal_banners (
  id INT AUTO_INCREMENT PRIMARY KEY,
  image_url VARCHAR(500) NOT NULL,
  title VARCHAR(150) NOT NULL,
  button_link VARCHAR(255),
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
