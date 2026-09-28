-- Migración: aviso "¡Últimas unidades!" opcional por producto.
-- Antes se mostraba automáticamente en cualquier producto con poco stock;
-- ahora es apagado por default y se prende solo en los productos puntuales
-- donde quieras generar esa sensación de urgencia (tildando la casilla en
-- Editar/Nuevo producto).
-- Corré esto una sola vez en MySQL Workbench sobre la base caro_boutique.

ALTER TABLE products ADD COLUMN show_low_stock_badge TINYINT(1) NOT NULL DEFAULT 0 AFTER active;
