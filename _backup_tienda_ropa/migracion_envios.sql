-- Migración: costo de envío real (zonas configurables)
-- Corré esto una sola vez en MySQL Workbench (o con el cliente de MySQL
-- que uses) contra la base de datos de Vua Showroom.

-- Si ya corriste migracion_funciones_nuevas.sql, la tabla shipping_zones
-- ya existe y esta línea no hace nada (es segura de repetir).
CREATE TABLE IF NOT EXISTS shipping_zones (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL DEFAULT 0,
  free_from DECIMAL(10,2),
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

ALTER TABLE orders ADD COLUMN shipping_zone VARCHAR(100);
ALTER TABLE orders ADD COLUMN shipping_cost DECIMAL(10,2);
