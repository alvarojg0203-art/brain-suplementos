-- Migración: galería de fotos por producto (ej: frente y espalda de una
-- prenda), independiente de los colores. Sirve para cualquier producto,
-- tenga o no colores cargados.
-- Corré esto una sola vez en MySQL Workbench, sobre la base caro_boutique.

USE caro_boutique;

CREATE TABLE IF NOT EXISTS product_images (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  image_url VARCHAR(500) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;
