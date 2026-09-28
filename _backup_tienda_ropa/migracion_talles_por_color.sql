-- Migración: talles con stock propio por cada color (ej: 2 unidades de
-- Rosa viejo talle L, 1 de Beige talle L, cada uno cargado por separado).
-- Corré esto una sola vez en MySQL Workbench, sobre la base caro_boutique.

USE caro_boutique;

ALTER TABLE product_sizes
  ADD COLUMN product_color_id INT NULL AFTER product_id,
  ADD CONSTRAINT fk_product_sizes_color
    FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE CASCADE;
