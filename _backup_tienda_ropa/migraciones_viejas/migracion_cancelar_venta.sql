-- Migración: permite cancelar una venta presencial (Caja) y que el stock
-- vendido se devuelva automáticamente.
-- Corré esto una sola vez en MySQL Workbench sobre la base caro_boutique.

ALTER TABLE pos_sales ADD COLUMN status ENUM('completada','cancelada') NOT NULL DEFAULT 'completada' AFTER customer_name;
