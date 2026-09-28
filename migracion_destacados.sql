-- Migración: agrega la tabla featured_products, que permite elegir a
-- mano qué productos aparecen fijos en "Novedades" o en "Más vendidos"
-- desde el nuevo panel /admin/destacados. Los que no se fijan a mano
-- se siguen completando solos como antes (por fecha o por ventas).
--
-- Cómo correrla: importar este archivo en la base de datos de
-- BrainSuplementos (igual que las migraciones anteriores).

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS featured_products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  section ENUM('novedades','vendidos') NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  UNIQUE KEY uq_featured_product_section (product_id, section)
) ENGINE=InnoDB;
