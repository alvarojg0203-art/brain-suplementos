-- Migración: subcategorías administrables desde el panel, para las 3
-- categorías (antes solo existía una lista fija de subcategorías de
-- Indumentaria escrita en el código, sin poder editarla ni usarla en
-- Calzado/Accesorios).
-- Corré esto una sola vez en MySQL Workbench sobre la base caro_boutique.

CREATE TABLE IF NOT EXISTS subcategories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category ENUM('indumentaria','calzado','accesorios') NOT NULL,
  name VARCHAR(60) NOT NULL,
  slug VARCHAR(60) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_subcategories_category_slug (category, slug)
) ENGINE=InnoDB;

-- Carga las subcategorías de Indumentaria que ya venían fijas en el código,
-- así los productos que ya las tenían puestas siguen funcionando igual.
INSERT IGNORE INTO subcategories (category, name, slug, sort_order) VALUES
('indumentaria', 'Remeras', 'remeras', 1),
('indumentaria', 'Pantalones', 'pantalones', 2),
('indumentaria', 'Buzos y hoodies', 'buzos', 3),
('indumentaria', 'Camperas', 'camperas', 4),
('indumentaria', 'Vestidos', 'vestidos', 5),
('indumentaria', 'Polleras', 'polleras', 6),
('indumentaria', 'Shorts', 'shorts', 7),
('indumentaria', 'Otros', 'otros', 8);
