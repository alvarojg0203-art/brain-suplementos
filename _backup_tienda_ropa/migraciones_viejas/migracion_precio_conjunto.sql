-- Migración: precio especial opcional para conjuntos/looks.
-- Corré esto una sola vez en MySQL Workbench sobre la base caro_boutique.

ALTER TABLE product_sets ADD COLUMN discount_price DECIMAL(10,2);
