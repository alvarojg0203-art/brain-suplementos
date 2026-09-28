-- Migración: conjuntos/looks (agrupar productos ya cargados para
-- mostrarlos juntos en la tienda). Corré esto una sola vez en MySQL
-- Workbench, sobre la base caro_boutique.

USE caro_boutique;

CREATE TABLE IF NOT EXISTS product_sets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  description VARCHAR(255),
  image_url VARCHAR(500),
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS product_set_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  set_id INT NOT NULL,
  product_id INT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  FOREIGN KEY (set_id) REFERENCES product_sets(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  UNIQUE KEY uq_set_product (set_id, product_id)
) ENGINE=InnoDB;
