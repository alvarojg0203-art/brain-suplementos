-- Migración: código de barras / SKU por producto, para poder cargar
-- ventas en Caja escaneándolo con una lectora de código de barras.
-- Corré esto una sola vez en MySQL Workbench sobre la base caro_boutique.

ALTER TABLE products ADD COLUMN barcode VARCHAR(64) NULL AFTER cost_price;
ALTER TABLE products ADD UNIQUE KEY uq_products_barcode (barcode);
