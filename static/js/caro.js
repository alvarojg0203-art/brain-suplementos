/* =========================================================
   CONFIGURACIÓN RÁPIDA — Editá esto para personalizar
   ========================================================= */
const WHATSAPP_NUMBER = "5493865830702"; // tu número para pruebas: 54 (Argentina) + 9 (celular) + 3865830702
const INSTAGRAM_URL = "https://instagram.com/brain__suplementos";
const API_BASE = ""; // vacío = mismo servidor Flask (recomendado). Poner URL si el backend vive en otro dominio.
const LOW_STOCK_THRESHOLD = 3; // a partir de cuántas unidades o menos se muestra "¡Últimas unidades!"
/* ========================================================= */

function dismissAnnounce(){
  const bar = document.getElementById("announceBar");
  if(bar) bar.classList.add("hidden");
  sessionStorage.setItem("caro_announce_dismissed", "1");
}
if(sessionStorage.getItem("caro_announce_dismissed")){
  document.addEventListener("DOMContentLoaded", () => {
    const bar = document.getElementById("announceBar");
    if(bar) bar.classList.add("hidden");
  });
}

let PRODUCTS = [];
let CATEGORIES = []; // se cargan desde /api/categories: proteínas, creatina, barritas, etc. — las administra el equipo desde /admin/categorias
let cart = JSON.parse(localStorage.getItem("caro_cart") || "[]");
let currentFilter = "todos";
let currentSubcategory = ""; // sin efecto si currentFilter === "todos", o si esa categoría no tiene subcategorías cargadas
let favorites = new Set(JSON.parse(localStorage.getItem("caro_favorites") || "[]"));
let showFavoritesOnly = false;
let showOffersOnly = false;
let searchQuery = "";
let priceMin = null;
let priceMax = null;

function toggleFavorite(id, event){
  if(event) event.stopPropagation();
  if(favorites.has(id)) favorites.delete(id); else favorites.add(id);
  localStorage.setItem("caro_favorites", JSON.stringify([...favorites]));
  renderProducts();
}

function clearOffersFilter(){
  showOffersOnly = false;
  document.getElementById("offersBanner").style.display = "none";
  renderProducts();
}

function toggleFavFilter(){
  showFavoritesOnly = !showFavoritesOnly;
  document.getElementById("favFilterBtn").classList.toggle("active", showFavoritesOnly);
  renderProducts();
}

function onSearchInput(){
  searchQuery = document.getElementById("searchInput").value.trim().toLowerCase();
  renderProducts();
}

function applyPriceFilter(){
  const minVal = document.getElementById("priceMin").value;
  const maxVal = document.getElementById("priceMax").value;
  priceMin = minVal ? Number(minVal) : null;
  priceMax = maxVal ? Number(maxVal) : null;
  renderProducts();
}

/* Chips de subcategoría (Whey, Isolate, Creatina, etc.): se cargan
   desde /api/subcategories según la categoría elegida — cada categoría
   (proteínas/creatinas/vitaminas) tiene las suyas, administradas desde
   /admin/subcategorias. Si esa categoría no tiene ninguna cargada, o es
   "todos", los chips quedan ocultos. */
async function loadSubfilters(cat){
  const subfilters = document.getElementById("subfilters");
  if(!subfilters) return;
  if(cat === "todos"){
    subfilters.style.display = "none";
    subfilters.innerHTML = "";
    return;
  }
  try{
    const res = await fetch(`${API_BASE}/api/subcategories?category=${encodeURIComponent(cat)}`);
    const data = await res.json();
    if(!data.length){
      subfilters.style.display = "none";
      subfilters.innerHTML = "";
      return;
    }
    subfilters.innerHTML = `<button class="subfilter-btn active" data-subcat="" onclick="filterSubcategory('')">Todas</button>` +
      data.map(s => `<button class="subfilter-btn" data-subcat="${s.slug}" onclick="filterSubcategory('${s.slug}')">${s.name}</button>`).join("");
    subfilters.style.display = "flex";
  }catch(err){
    console.error(err);
    subfilters.style.display = "none";
  }
}

function getFilteredProducts(){
  return PRODUCTS.filter(p => {
    if(showFavoritesOnly && !favorites.has(p.id)) return false;
    if(showOffersOnly && !p.originalPrice) return false;
    if(searchQuery && !p.name.toLowerCase().includes(searchQuery)) return false;
    if(priceMin !== null && p.price < priceMin) return false;
    if(priceMax !== null && p.price > priceMax) return false;
    return true;
  });
}

/* Categorías (proteínas, creatina, barritas, aminoácidos, etc.): se cargan
   desde /api/categories, así el equipo las administra desde
   /admin/categorias sin tocar código. Con esto llenamos tanto las tarjetas
   de "Comprá por categoría" como los botones de filtro del catálogo. */
async function loadCategories(){
  try{
    const res = await fetch(`${API_BASE}/api/categories`);
    CATEGORIES = await res.json();
  }catch(err){
    console.error("No se pudieron cargar las categorías", err);
    CATEGORIES = [];
  }
  renderCategoryCards();
  renderCategoryFilters();
}

function renderCategoryCards(){
  const grid = document.getElementById("catGrid");
  if(!grid) return;
  // Estas tarjetas viven en la home ("Comprá por categoría"); el catálogo
  // completo ahora es la página /catalogo, así que en vez de filtrar en la
  // misma página, navegan ahí ya con la categoría elegida.
  grid.innerHTML = CATEGORIES.map(c => `
    <div class="cat-card" onclick="window.location.href='/catalogo?tag=${encodeURIComponent(c.slug)}'">
      <div class="cat-card-box">
        <div class="cat-card-img">${c.image_url ? `<img src="${c.image_url}" alt="${c.name}" loading="lazy">` : (c.icon || "")}</div>
        <h3>${c.name}</h3>
      </div>
    </div>
  `).join("");
}

function renderCategoryFilters(){
  const container = document.getElementById("categoryFilters");
  if(!container) return;
  const todosBtn = `<button class="filter-btn ${currentFilter === "todos" ? "active" : ""}" data-cat="todos" onclick="filterCategory('todos')">Todos</button>`;
  container.innerHTML = todosBtn + CATEGORIES.map(c => `
    <button class="filter-btn ${currentFilter === c.slug ? "active" : ""}" data-cat="${c.slug}" onclick="filterCategory('${c.slug}')">${c.name}</button>
  `).join("");
}

/* El catálogo completo vive en /catalogo (página aparte, ya no una
   sección más de la home). Esta función arma el filtro inicial de esa
   página según la URL: ?tag=<categoría o "ofertas">, ?sub=<subcategoría>
   y/o ?q=<búsqueda> — así los links de banners, categorías y el buscador
   del header pueden mandar directo al resultado filtrado. Se llama
   después de loadCategories(), así "tag" se valida contra las categorías
   reales (ya no hay una lista fija de categorías en el código). En la
   home (data-page="home") no hace nada: ahí el catálogo ni se muestra. */
async function initCatalogFromUrl(){
  if(document.documentElement.dataset.page !== "catalogo") return;

  const params = new URLSearchParams(window.location.search);
  const tag = params.get("tag");
  const sub = params.get("sub");
  const q = params.get("q");
  const validCats = CATEGORIES.map(c => c.slug);
  const cat = validCats.includes(tag) ? tag : "todos";

  if(tag === "ofertas"){
    showOffersOnly = true;
    document.getElementById("offersBanner").style.display = "block";
  }
  if(cat !== "todos"){
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.toggle("active", b.dataset.cat === cat));
    currentFilter = cat;
  }
  if(q){
    searchQuery = q.toLowerCase();
    const searchInput = document.getElementById("searchInput");
    if(searchInput) searchInput.value = q;
  }

  await loadSubfilters(cat);
  if(sub){
    currentSubcategory = sub;
    document.querySelectorAll("#subfilters .subfilter-btn").forEach(b => b.classList.toggle("active", b.dataset.subcat === sub));
  }

  await loadProducts(cat, sub || "");
}

/* Buscador del header (arriba de todo, al lado del logo): busca sobre
   todo el catálogo. Como el catálogo ahora es la página /catalogo, si
   estamos en la home mandamos directo para allá con la búsqueda en la
   URL; si ya estamos en /catalogo, filtra ahí mismo sin recargar. */
function runHeaderSearch(){
  const val = document.getElementById("headerSearchInput").value.trim();
  if(document.documentElement.dataset.page !== "catalogo"){
    window.location.href = "/catalogo" + (val ? ("?q=" + encodeURIComponent(val)) : "");
    return;
  }
  const catalogInput = document.getElementById("searchInput");
  if(catalogInput) catalogInput.value = val;
  searchQuery = val.toLowerCase();
  filterCategory("todos");
}

/* Mega-menú de "Productos" en el header: arma columnas con las
   categorías reales (y sus subcategorías) desde /api/menu-categories,
   así el equipo las sigue administrando desde /admin/categorias y
   /admin/subcategorias sin tocar código acá. */
async function loadMegaMenu(){
  const container = document.getElementById("megaMenu");
  if(!container) return;
  try{
    const res = await fetch(`${API_BASE}/api/menu-categories`);
    const cats = await res.json();
    renderMegaMenu(cats);
  }catch(err){
    console.error("No se pudo cargar el menú de productos", err);
  }
}

function renderMegaMenu(categories){
  const container = document.getElementById("megaMenu");
  if(!container) return;
  if(!categories.length){
    container.innerHTML = `<span class="mega-menu-empty">Todavía no hay categorías cargadas.</span>`;
    return;
  }
  // Cada categoría lleva a esa categoría puntual del catálogo (/catalogo?tag=...)
  container.innerHTML = categories.map(c => `
    <div class="mega-col">
      <a class="mega-cat" href="/catalogo?tag=${encodeURIComponent(c.slug)}" onclick="closeMobileMenu()">${c.name}</a>
      ${c.subcategories && c.subcategories.length ? `
        <div class="mega-menu-sub">
          ${c.subcategories.map(s => `<a href="/catalogo?tag=${encodeURIComponent(c.slug)}&sub=${encodeURIComponent(s.slug)}" onclick="closeMobileMenu()">${s.name}</a>`).join("")}
        </div>
      ` : ""}
    </div>
  `).join("");
}
 

/* Despliega/oculta las categorías dentro de "Productos" (menú de 3
   líneas). Es un acordeón en vez del mega-menú al pasar el mouse de
   antes, porque ahora este menú es el mismo en compu y en celular (donde
   no existe el hover). */
function toggleMobileMegaMenu(){
  const menu = document.getElementById("megaMenu");
  const chevron = document.getElementById("megaMenuChevron");
  if(!menu) return;
  const isOpen = menu.style.display === "block";
  menu.style.display = isOpen ? "none" : "block";
  if(chevron) chevron.classList.toggle("open", !isOpen);
}

let isLoggedIn = false;
let accountData = null;

async function checkAuth(){
  try{
    const res = await fetch(`${API_BASE}/api/me`);
    const data = await res.json();
    isLoggedIn = !!data.logged_in;
    accountData = isLoggedIn ? data : null;
    const label = document.getElementById("accountLabel");
    const link = document.getElementById("accountLink");
    if(isLoggedIn){
      label.textContent = data.name ? data.name.split(" ")[0] : "Mi cuenta";
      link.href = "/cuenta";
      link.title = "Mi cuenta";
    } else {
      label.textContent = "Ingresar";
      link.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
      link.removeAttribute("title");
    }
  }catch(err){ console.error(err); }
}

function prefillCheckoutForm(){
  if(!accountData) return;
  const firstEl = document.getElementById("custFirstName");
  const lastEl = document.getElementById("custLastName");
  const phoneEl = document.getElementById("custPhone");
  if(firstEl && lastEl && !firstEl.value && !lastEl.value && accountData.name){
    const parts = accountData.name.trim().split(" ");
    firstEl.value = parts[0] || "";
    lastEl.value = parts.slice(1).join(" ");
  }
  if(phoneEl && !phoneEl.value) phoneEl.value = accountData.phone || "";
  // La dirección guardada antes era un solo campo de texto libre, así que
  // no la partimos en Calle/Número/Depto/Barrio/Ciudad automáticamente:
  // la persona la vuelve a completar la primera vez con los campos nuevos.
}

/* Junta Nombre + Apellido en un solo string (así lo esperan las tablas
   customers/orders, que guardan el nombre completo en una sola columna). */
function getFullName(){
  const first = (document.getElementById("custFirstName").value || "").trim();
  const last = (document.getElementById("custLastName").value || "").trim();
  return `${first} ${last}`.trim();
}

/* Junta Calle/Número/Depto/Barrio/Ciudad en un solo string de dirección
   (mismo motivo: delivery_address es una sola columna de texto). */
function getFullAddress(){
  const street = (document.getElementById("custStreet").value || "").trim();
  const number = (document.getElementById("custStreetNumber").value || "").trim();
  const apartment = (document.getElementById("custApartment").value || "").trim();
  const neighborhood = (document.getElementById("custNeighborhood").value || "").trim();
  const city = (document.getElementById("custCity").value || "").trim();

  let address = [street, number].filter(Boolean).join(" ");
  if(apartment) address += `, Depto ${apartment}`;
  if(neighborhood) address += `${address ? ", " : ""}${neighborhood}`;
  if(city) address += `${address ? ", " : ""}${city}`;
  return address;
}

function formatPrice(n){
  return "$" + Number(n).toLocaleString("es-AR");
}

/* Precio "simulado" en 3 cuotas con Mercado Pago: el mismo precio de
   efectivo/transferencia + el % que se cargue en /admin/pagos, dividido
   en 3. El % es uno solo para toda la tienda (no por producto). Se pinta
   chiquito y en gris debajo del precio grande de efectivo/transferencia,
   que es el que ya se mostraba antes. */
let pricingSettings = { mercado_pago: true, recargo_cuotas_pct: 0 };

async function loadPricingSettings(){
  try{
    const res = await fetch(`${API_BASE}/api/payment-methods`);
    if(res.ok) pricingSettings = await res.json();
  }catch(err){
    console.error("No se pudo cargar el recargo de 3 cuotas", err);
  }
}

function installmentPrice(price){
  const pct = Number(pricingSettings.recargo_cuotas_pct) || 0;
  return Math.round((price * (1 + pct / 100)) / 3);
}

function installmentsHtml(price){
  if(!pricingSettings.mercado_pago) return "";
  return `<span class="installments-hint">3 cuotas de ${formatPrice(installmentPrice(price))} con Mercado Pago</span>`;
}

/* Estrellitas llenas/vacías para mostrar el promedio de reseñas (ej: 4.3
   se pinta como 4 llenas + 1 vacía, redondeando al entero más cercano). */
function starsHtml(rating){
  const rounded = Math.round(rating || 0);
  let out = "";
  for(let i = 1; i <= 5; i++) out += `<span class="star ${i <= rounded ? "filled" : ""}">★</span>`;
  return out;
}

/* =========================================================
   CARRUSEL DE PORTADA (hero_slides) — si no hay ninguno
   cargado desde el panel, se deja el texto fijo de siempre.
   ========================================================= */
let heroSlides = [];
let heroIndex = 0;
let heroTimer = null;

async function loadHeroSlides(){
  try{
    const res = await fetch(`${API_BASE}/api/hero-slides`);
    if(!res.ok) return;
    const data = await res.json();
    if(!data.length) return;
    heroSlides = data;
    renderHeroSlides();
    startHeroAutoplay();
  }catch(err){ console.error(err); }
}

function renderHeroSlides(){
  const slider = document.getElementById("heroSlider");
  // En celular (pantalla angosta), si el slide tiene cargada una imagen
  // recortada especial para mobile, usamos esa en vez de la de compu —
  // si no cargaron ninguna, sigue mostrando la misma de siempre.
  const isMobile = window.innerWidth <= 640;
  slider.innerHTML = heroSlides.map((s, i) => {
    // Si el slide no tiene título ni bajada (una foto/imagen de marca
    // "limpia", sin texto encima), no le ponemos el velo oscuro: ese
    // oscurecido es solo para que el texto blanco se lea sobre la foto.
    const hasText = !!(s.title || s.subtitle);
    const bgImage = (isMobile && s.mobile_image_url) ? s.mobile_image_url : s.image_url;
    return `
    <div class="hero-slide ${i === 0 ? "active" : ""} ${hasText ? "has-text" : ""}" style="background-image:url('${bgImage}')">
      <div class="hero-content">
        ${s.title ? `<h1>${s.title}</h1>` : ""}
        ${s.subtitle ? `<p>${s.subtitle}</p>` : ""}
        ${s.button_text && s.button_link ? `<a href="${s.button_link}" class="btn btn-primary">${s.button_text}</a>` : ""}
      </div>
    </div>
  `;
  }).join("");
  heroIndex = 0;

  const multiple = heroSlides.length > 1;
  document.getElementById("heroDots").style.display = multiple ? "flex" : "none";
  document.querySelectorAll(".hero-arrow").forEach(a => a.style.display = multiple ? "flex" : "none");
  document.getElementById("heroDots").innerHTML = heroSlides.map((_, i) =>
    `<button class="hero-dot ${i === 0 ? "active" : ""}" onclick="goToHeroSlide(${i})" aria-label="Ir a la imagen ${i + 1}"></button>`
  ).join("");

  if(multiple){
    const heroSection = document.getElementById("inicio");
    let touchStartX = null;
    heroSection.ontouchstart = e => { touchStartX = e.touches[0].clientX; };
    heroSection.ontouchend = e => {
      if(touchStartX === null) return;
      const delta = e.changedTouches[0].clientX - touchStartX;
      if(Math.abs(delta) > 50){ delta > 0 ? heroPrev() : heroNext(); }
      touchStartX = null;
    };
  }
}

function showHeroSlide(i){
  document.querySelectorAll(".hero-slide").forEach((s, idx) => s.classList.toggle("active", idx === i));
  document.querySelectorAll(".hero-dot").forEach((d, idx) => d.classList.toggle("active", idx === i));
  heroIndex = i;
}

function heroNext(){ showHeroSlide((heroIndex + 1) % heroSlides.length); resetHeroAutoplay(); }
function heroPrev(){ showHeroSlide((heroIndex - 1 + heroSlides.length) % heroSlides.length); resetHeroAutoplay(); }
function goToHeroSlide(i){ showHeroSlide(i); resetHeroAutoplay(); }

function startHeroAutoplay(){
  if(heroSlides.length <= 1) return;
  heroTimer = setInterval(() => showHeroSlide((heroIndex + 1) % heroSlides.length), 6000);
}
function resetHeroAutoplay(){
  clearInterval(heroTimer);
  startHeroAutoplay();
}

/* Misma conversión de la respuesta de /api/products al formato que usa
   el front (precio con descuento ya aplicado, imagen de "hover", etc),
   compartida entre el catálogo principal (loadProducts) y el buscador
   de "Armá tu combo" (loadComboBuilderProducts) para no tener la misma
   lógica de precios pegada en dos lugares distintos. */
function mapProductApiToClient(p){
  const hasDiscount = p.discount_percent !== null && p.discount_percent !== undefined;
  const finalPrice = hasDiscount ? Math.round(p.price * (1 - p.discount_percent / 100)) : p.price;
  // Para el hover "ver de atrás" en la vidriera: primero probamos con
  // las fotos extra generales del producto (si las tiene); si no,
  // usamos la segunda foto del primer color (la primera ya se usa
  // como foto principal de la tarjeta) — así alcanza con cargar las
  // fotos por color, sin tener que subirlas también aparte.
  const firstFlavorImages = (p.colors && p.colors[0] && p.colors[0].images) || [];
  const hoverImg = (p.images && p.images.length) ? p.images[0] : (firstFlavorImages.length > 1 ? firstFlavorImages[1] : null);
  return {
    id: p.id, name: p.name, cat: p.category, catName: p.category_name || p.category,
    price: finalPrice,
    originalPrice: hasDiscount ? p.price : null,
    discountPercent: hasDiscount ? p.discount_percent : null,
    img: p.image_url || "https://placehold.co/400x500/eee/634b3d?text=Sin+foto",
    stock: p.stock,
    colors: p.colors || [],
    hoverImg,
    showLowStockBadge: !!p.show_low_stock_badge,
    ratingAvg: p.rating_avg, ratingCount: p.rating_count || 0
  };
}

async function loadProducts(category, subcategory){
  const grid = document.getElementById("productGrid");
  grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:var(--color-muted);">Cargando productos...</p>`;
  try{
    const params = new URLSearchParams();
    if(category && category !== "todos") params.set("category", category);
    if(category !== "todos" && subcategory) params.set("subcategoria", subcategory);
    const qs = params.toString();
    const url = qs ? `${API_BASE}/api/products?${qs}` : `${API_BASE}/api/products`;
    const res = await fetch(url);
    if(!res.ok) throw new Error("respuesta no OK");
    const data = await res.json();
    PRODUCTS = data.map(mapProductApiToClient);
    renderProducts();
  }catch(err){
    console.error(err);
    grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:#b34747;">
      No se pudo conectar con el servidor. Revisá que app.py esté corriendo (ver README.md).</p>`;
  }
}

/* Tarjeta de producto: la usa tanto la vidriera principal como el
   carrusel de "Los más llevados", para que se vean y funcionen
   exactamente igual (mismo botón de agregar, mismo corazón de favorito,
   mismo hover de foto) sin mantener el HTML pegado en dos lugares. */
function productCardHtml(p){
  const hasFlavors = p.colors && p.colors.length > 0;
  const lowStock = p.showLowStockBadge && p.stock > 0 && p.stock <= LOW_STOCK_THRESHOLD;
  const isFav = favorites.has(p.id);
  const addBtn = hasFlavors
    ? `<button class="add-btn" onclick="openProductDetail(${p.id})">Ver opciones</button>`
    : (p.stock > 0
        ? `<button class="add-btn" onclick="addToCart(${p.id})">Agregar al carrito</button>`
        : `<button class="add-btn" disabled style="opacity:.5;cursor:not-allowed;">Sin stock</button>`);
  return `
    <div class="product-card">
      <div class="product-img-wrap" onclick="openProductDetail(${p.id})" style="cursor:pointer;">
        ${p.originalPrice ? `<span class="discount-badge">-${Math.round(p.discountPercent)}%</span>` : ""}
        <button class="fav-btn ${isFav ? "active" : ""}" onclick="toggleFavorite(${p.id}, event)" aria-label="Favorito">
          <svg viewBox="0 0 24 24" fill="${isFav ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.8"><path d="M12 21s-7.2-4.6-10-9.3C.3 8.4 1.8 4.8 5.2 4c2-.5 4 .3 5.3 2 1.3-1.7 3.3-2.5 5.3-2 3.4.8 4.9 4.4 3.2 7.7C19.2 16.4 12 21 12 21Z"/></svg>
        </button>
        <img src="${p.img}" alt="${p.name}" loading="lazy">
        ${p.hoverImg ? `<img src="${p.hoverImg}" alt="${p.name}" class="img-back" loading="lazy">` : ""}
      </div>
      <div class="product-info">
        <span class="cat-tag">${p.catName}</span>
        <h4 style="cursor:pointer;" onclick="openProductDetail(${p.id})">${p.name}</h4>
        ${p.ratingCount > 0 ? `<div class="rating-badge">${starsHtml(p.ratingAvg)} <span>(${p.ratingCount})</span></div>` : ""}
        ${p.originalPrice
          ? `<span class="price-row"><span class="price-old">${formatPrice(p.originalPrice)}</span><span class="price">${formatPrice(p.price)}</span></span>`
          : `<span class="price">${formatPrice(p.price)}</span>`}
        ${installmentsHtml(p.price)}
        ${hasFlavors ? `<div class="color-dots">${p.colors.map(c => `<span class="color-dot" style="background:${c.hex}" title="${c.name}"></span>`).join("")}</div>` : ""}
        ${lowStock ? `<span class="low-stock">¡Últimas unidades!</span>` : ""}
        ${addBtn}
      </div>
    </div>
  `;
}

function renderProducts(){
  const grid = document.getElementById("productGrid");
  const list = getFilteredProducts();

  if(PRODUCTS.length === 0){
    grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:var(--color-muted);">No hay productos en esta categoría todavía.</p>`;
    return;
  }
  if(list.length === 0){
    const msg = showFavoritesOnly ? "Todavía no marcaste favoritos por acá." : "No encontramos productos con esos filtros.";
    grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:var(--color-muted);">${msg}</p>`;
    return;
  }
  grid.innerHTML = list.map(productCardHtml).join("");
}

/* NOVEDADES: carrusel horizontal con los productos cargados más
   recientemente (sin importar ventas). Va primero, arriba de "Más
   vendidos". Mismo patrón de carrusel que el resto de la home. */
async function loadNewestProducts(){
  const section = document.getElementById("novedades");
  const track = document.getElementById("novedadesTrack");
  if(!section || !track) return;
  try{
    const res = await fetch(`${API_BASE}/api/newest-products?limit=12`);
    if(!res.ok) throw new Error("respuesta no OK");
    const data = await res.json();
    if(!data.length){ section.style.display = "none"; return; }
    track.innerHTML = data.map(mapProductApiToClient).map(productCardHtml).join("");
    section.style.display = "block";
  }catch(err){
    console.error(err);
    section.style.display = "none";
  }
}

function scrollNewest(direction){
  scrollCarouselTrack("novedadesTrack", ".product-card", direction, 3);
}

/* MÁS VENDIDOS (antes "Los más llevados"): carrusel horizontal con
   flechas, ranking automático por ventas reales (ver reference video).
   Independiente del catálogo/filtros de la vidriera principal. */
async function loadMostPurchased(){
  const section = document.getElementById("masLlevados");
  const track = document.getElementById("mostPurchasedTrack");
  try{
    const res = await fetch(`${API_BASE}/api/most-purchased?limit=12`);
    if(!res.ok) throw new Error("respuesta no OK");
    const data = await res.json();
    if(!data.length){ section.style.display = "none"; return; }
    track.innerHTML = data.map(mapProductApiToClient).map(productCardHtml).join("");
    section.style.display = "block";
  }catch(err){
    console.error(err);
    section.style.display = "none";
  }
}

/* Helper genérico para los carruseles horizontales con flechas ("Los
   más llevados" y "Combos Más llevados"): avanza/retrocede un puñado de
   tarjetas por click, calculando el ancho real de la primera tarjeta
   (que puede cambiar según el tamaño de pantalla). */
function scrollCarouselTrack(trackId, cardSelector, direction, cardsPerClick){
  const track = document.getElementById(trackId);
  if(!track) return;
  const card = track.querySelector(cardSelector);
  const step = card ? (card.getBoundingClientRect().width + 24) * cardsPerClick : 600;
  track.scrollBy({left: direction * step, behavior: "smooth"});
}

function scrollMostPurchased(direction){
  scrollCarouselTrack("mostPurchasedTrack", ".product-card", direction, 3);
}

function scrollSets(direction){
  scrollCarouselTrack("setsGrid", ".set-card", direction, 2);
}

/* BANNERS MOTIVACIONALES ("Ganar masa muscular", etc.) — se cargan y
   ordenan desde /admin/banners. Cada uno lleva a los productos de la
   categoría que le hayan asignado (o a todo el catálogo si no eligieron
   ninguna). El catálogo ahora es la página /catalogo, así que si en el
   panel cargaron un link viejo tipo /?tag=slug#catalogo, el script del
   <head> de index.html lo redirige solo a /catalogo?tag=slug. */
async function loadGoalBanners(){
  const section = document.getElementById("goalBanners");
  const track = document.getElementById("goalBannersTrack");
  try{
    const res = await fetch(`${API_BASE}/api/goal-banners`);
    if(!res.ok) throw new Error("respuesta no OK");
    const banners = await res.json();
    if(!banners.length){ section.style.display = "none"; return; }
    track.innerHTML = banners.map(b => `
      <a class="goal-banner" href="${b.button_link || "/catalogo"}">
        <img src="${b.image_url}" alt="${b.title}" loading="lazy">
        <span class="goal-banner-title">${b.title}</span>
      </a>
    `).join("");
    section.style.display = "block";
  }catch(err){
    console.error(err);
    section.style.display = "none";
  }
}

function scrollGoalBanners(direction){
  scrollCarouselTrack("goalBannersTrack", ".goal-banner", direction, 2);
}

/* SEGUINOS EN INSTAGRAM: capturas reales de posteos/reels, cargadas y
   ordenadas desde /admin/instagram. Cada captura lleva al posteo
   puntual si le cargaron un link, y si no a INSTAGRAM_URL (el perfil). */
async function loadInstagramPosts(){
  const section = document.getElementById("instagramFeed");
  const track = document.getElementById("instagramFeedTrack");
  if(!section || !track) return;
  try{
    const res = await fetch(`${API_BASE}/api/instagram-posts`);
    if(!res.ok) throw new Error("respuesta no OK");
    const posts = await res.json();
    if(!posts.length){ section.style.display = "none"; return; }
    track.innerHTML = posts.map(p => `
      <a class="instagram-post" href="${p.link || INSTAGRAM_URL}" target="_blank" rel="noopener">
        <img src="${p.image_url}" alt="Posteo de Instagram" loading="lazy">
      </a>
    `).join("");
    section.style.display = "flex";
  }catch(err){
    console.error(err);
    section.style.display = "none";
  }
}

function filterCategory(cat){
  currentFilter = cat;
  currentSubcategory = "";
  // Si venías con el filtro de "solo ofertas" prendido (por ejemplo por un
  // botón del carrusel), al elegir una categoría a mano lo sacamos: si no,
  // quedaba trabado mostrando solo lo que está en oferta para siempre.
  showOffersOnly = false;
  const offersBanner = document.getElementById("offersBanner");
  if(offersBanner) offersBanner.style.display = "none";
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.toggle("active", b.dataset.cat === cat));

  // Las subcategorías (remeras, botas, etc.) dependen de lo que haya
  // cargado esa categoría en /admin/subcategorias — se piden de nuevo
  // cada vez que se cambia de categoría.
  loadSubfilters(cat);

  loadProducts(cat, "");
  document.getElementById("catalogo").scrollIntoView({behavior:"smooth"});
}

function filterSubcategory(subcat){
  currentSubcategory = subcat;
  document.querySelectorAll("#subfilters .subfilter-btn").forEach(b => b.classList.toggle("active", b.dataset.subcat === subcat));
  loadProducts(currentFilter, subcat);
}

function saveCart(){
  localStorage.setItem("caro_cart", JSON.stringify(cart));
  renderCart();
}

function addToCart(id){
  const product = PRODUCTS.find(p => p.id === id);
  if(!product) return;
  const existing = cart.find(i => i.id === id && !i.flavorId);
  if(existing){ existing.qty += 1; } else {
    cart.push({ id: product.id, name: product.name, price: product.price, img: product.img, flavorId: null, flavorName: null, weightId: null, weightName: null, qty: 1 });
  }
  saveCart();
  showToast(`${product.name} agregado al carrito`);
}

function cartLineIndex(id, flavorId, weightId){
  return cart.findIndex(i => i.id === id && (i.flavorId || null) === (flavorId || null) && (i.weightId || null) === (weightId || null));
}

function changeQty(id, flavorId, weightId, delta){
  const idx = cartLineIndex(id, flavorId, weightId);
  if(idx === -1) return;
  cart[idx].qty += delta;
  if(cart[idx].qty <= 0){ cart.splice(idx, 1); }
  saveCart();
}

function removeItem(id, flavorId, weightId){
  const idx = cartLineIndex(id, flavorId, weightId);
  if(idx === -1) return;
  cart.splice(idx, 1);
  saveCart();
}

function cartTotal(){
  return cart.reduce((sum, i) => sum + i.price * i.qty, 0);
}

/* Cupón de descuento aplicado en el checkout (además del % de descuento
   que ya puede tener cada producto). Se valida contra el servidor antes
   de mostrarlo, y se vuelve a validar al confirmar el pedido. */
let appliedCoupon = null; // {code, percent_off}

function cartDiscount(){
  if(!appliedCoupon) return 0;
  return Math.round((cartTotal() * appliedCoupon.percent_off / 100) * 100) / 100;
}
function cartFinalTotal(){
  return cartTotal() - cartDiscount();
}

/* Zonas de envío con costo real, cargadas desde /admin/envios. Si la
   dueña todavía no cargó ninguna zona, no se muestra nada acá y el envío
   se sigue coordinando por WhatsApp como antes. */
let shippingZones = [];
let selectedShippingZoneId = null;

async function loadShippingZones(){
  try{
    const res = await fetch(`${API_BASE}/api/shipping-zones`);
    shippingZones = await res.json();
  }catch(err){
    console.error(err);
    shippingZones = [];
  }
}

function renderShippingZones(){
  const container = document.getElementById("shippingZonesList");
  if(!container) return;
  if(!shippingZones.length){
    container.innerHTML = `<p class="shipping-empty-note">Por ahora coordinamos el costo de envío por WhatsApp después de confirmar el pedido.</p>`;
    return;
  }
  if(!shippingZones.some(z => z.id === selectedShippingZoneId)){
    selectedShippingZoneId = shippingZones[0].id;
  }
  container.innerHTML = shippingZones.map(z => {
    const isFree = z.free_from !== null && z.free_from !== undefined && cartTotal() >= z.free_from;
    const freeNote = (z.free_from !== null && z.free_from !== undefined && !isFree)
      ? ` <span style="color:var(--color-muted);font-weight:400;">(envío gratis desde ${formatPrice(z.free_from)})</span>`
      : "";
    return `
      <label class="shipping-option">
        <input type="radio" name="shippingZone" value="${z.id}" ${z.id === selectedShippingZoneId ? "checked" : ""} onchange="selectShippingZone(${z.id})">
        <span class="so-name">${z.name}${freeNote}</span>
        <span class="so-price ${isFree ? "free" : ""}">${isFree ? "Gratis" : formatPrice(z.price)}</span>
      </label>
    `;
  }).join("");
}

function selectShippingZone(id){
  selectedShippingZoneId = id;
  renderCheckoutSummary();
  refreshCardBrickAmount();
}

function cartShippingCost(){
  const deliveryEl = document.getElementById("deliveryMethod");
  if(!deliveryEl || deliveryEl.value !== "Envío a domicilio") return 0;
  const zone = shippingZones.find(z => z.id === selectedShippingZoneId);
  if(!zone) return 0;
  if(zone.free_from !== null && zone.free_from !== undefined && cartTotal() >= zone.free_from) return 0;
  return zone.price;
}

function cartGrandTotal(){
  return cartFinalTotal() + cartShippingCost();
}

async function applyCoupon(){
  const input = document.getElementById("couponInput");
  const code = (input.value || "").trim();
  const msgEl = document.getElementById("couponMsg");
  if(!code){ msgEl.textContent = "Ingresá un código"; return; }
  try{
    const res = await fetch(`${API_BASE}/api/coupons/validate`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ code, subtotal: cartTotal() }),
    });
    const data = await res.json();
    if(!data.valid){
      appliedCoupon = null;
      msgEl.textContent = data.error || "Ese cupón no es válido";
      msgEl.style.color = "#b34747";
      renderCheckoutSummary();
      return;
    }
    appliedCoupon = { code: data.code, percent_off: data.percent_off };
    msgEl.textContent = `¡Cupón aplicado! -${data.percent_off}%`;
    msgEl.style.color = "#357a41";
    renderCheckoutSummary();
    refreshCardBrickAmount();
  }catch(err){
    console.error(err);
    msgEl.textContent = "No se pudo validar el cupón";
    msgEl.style.color = "#b34747";
  }
}

function removeCoupon(){
  appliedCoupon = null;
  const input = document.getElementById("couponInput");
  if(input) input.value = "";
  const msgEl = document.getElementById("couponMsg");
  if(msgEl) msgEl.textContent = "";
  renderCheckoutSummary();
  refreshCardBrickAmount();
}

function refreshCardBrickAmount(){
  // El monto del Payment Brick se fija al montarlo; si el cupón cambia
  // después (form de tarjeta ya visible), hay que remontarlo para que
  // cobre el total con descuento en vez del que tenía guardado.
  const checked = document.querySelector('input[name="payMethod"]:checked');
  if(checked && checked.dataset.mode === "embedded" && cardBrickController){
    ensureCardBrick();
  }
}

function renderCart(){
  const count = cart.reduce((s,i) => s + i.qty, 0);
  document.getElementById("cartCount").textContent = count;
  const itemsEl = document.getElementById("cartItems");
  if(cart.length === 0){
    itemsEl.innerHTML = `<div class="cart-empty">Tu carrito está vacío</div>`;
  } else {
    itemsEl.innerHTML = cart.map(i => {
      const variant = [i.flavorName, i.weightName ? `Peso ${i.weightName}` : null].filter(Boolean).join(" · ");
      return `
      <div class="cart-item">
        <img src="${i.img}" alt="${i.name}">
        <div class="cart-item-info">
          <h5>${i.name}${variant ? ` <span style="font-weight:400;color:var(--color-muted);">· ${variant}</span>` : ""}</h5>
          <span class="price">${formatPrice(i.price)} c/u</span>
          <div class="qty-controls">
            <button onclick="changeQty(${i.id},${i.flavorId || "null"},${i.weightId || "null"},-1)">−</button>
            <span>${i.qty}</span>
            <button onclick="changeQty(${i.id},${i.flavorId || "null"},${i.weightId || "null"},1)">+</button>
          </div>
          <span class="remove-item" onclick="removeItem(${i.id},${i.flavorId || "null"},${i.weightId || "null"})">Quitar</span>
        </div>
      </div>
    `;
    }).join("");
  }
  document.getElementById("cartSubtotal").textContent = formatPrice(cartTotal());
  document.getElementById("checkoutBtn").disabled = cart.length === 0;
}

function openCart(){
  document.getElementById("cartDrawer").classList.add("open");
  document.getElementById("overlay").classList.add("show");
}
function closeCart(){
  document.getElementById("cartDrawer").classList.remove("open");
  document.getElementById("overlay").classList.remove("show");
}
function closeAll(){ closeCart(); closeCheckout(); closeProductDetail(); closeComboBuilder(); }

let currentDetail = null;
let selectedFlavorId = null;
let selectedWeightId = null;
// Si la ficha de producto se abrió desde "Armá tu combo" (para elegir
// sabor/peso de un producto que lo necesita), el botón de "Agregar"
// tiene que sumarlo al combo que se está armando y no directo al
// carrito real — este flag es lo que distingue un caso del otro.
let productDetailForCombo = false;

async function openProductDetail(id, forCombo = false){
  productDetailForCombo = forCombo;
  const modal = document.getElementById("productModal");
  const body = document.getElementById("productDetailBody");
  body.innerHTML = `<p style="text-align:center;color:var(--color-muted);padding:40px 0;">Cargando...</p>`;
  modal.classList.add("show");

  try{
    const res = await fetch(`${API_BASE}/api/products/${id}`);
    if(!res.ok) throw new Error("no se pudo cargar");
    const data = await res.json();
    const hasDiscount = data.discount_percent !== null && data.discount_percent !== undefined;
    const finalPrice = hasDiscount ? Math.round(data.price * (1 - data.discount_percent / 100)) : data.price;
    currentDetail = {
      id: data.id, name: data.name, cat: data.category, catName: data.category_name || data.category, description: data.description,
      price: finalPrice, originalPrice: hasDiscount ? data.price : null,
      image: data.image_url || "https://placehold.co/400x500/eee/634b3d?text=Sin+foto",
      images: data.images || [], // fotos extra del producto (envase/tabla/detalle), sin sabor
      stock: data.stock,
      colors: data.colors || [],
      sizes: data.sizes || [],
      reviews: data.reviews || [], ratingAvg: data.rating_avg, ratingCount: data.rating_count || 0
    };
    selectedFlavorId = currentDetail.colors.length ? currentDetail.colors[0].id : null;
    const initialWeights = currentWeightOptions();
    selectedWeightId = initialWeights.length ? initialWeights[0].id : null;
    renderProductDetail();
  }catch(err){
    console.error(err);
    body.innerHTML = `<p style="text-align:center;color:#b34747;padding:40px 0;">No se pudo cargar el producto.</p>`;
  }
}

function closeProductDetail(){
  document.getElementById("productModal").classList.remove("show");
}

function currentGalleryImages(){
  // Fotos "principales": las propias del color elegido si tiene, si no la
  // foto de tapa del producto.
  let mainImages = [currentDetail.image];
  if(currentDetail.colors.length){
    const color = currentDetail.colors.find(c => c.id === selectedFlavorId) || currentDetail.colors[0];
    if(color.images && color.images.length) mainImages = color.images;
  }
  // A esas siempre les sumamos la galería general del producto (envase/
  // tabla/detalle) si existe — son fotos que valen para cualquier sabor,
  // así que no se pueden perder solo porque el sabor tenga foto propia.
  const extra = (currentDetail.images || []).filter(img => !mainImages.includes(img));
  return extra.length ? [...mainImages, ...extra] : mainImages;
}

/* Si el sabor elegido tiene sus propios pesos cargados (stock por
   combinación sabor+peso, ej: 2 de Chocolate en 1kg y 1 de Vainilla en 1kg,
   cada uno separado), esos son los que hay que mostrar/usar — si no,
   caemos a los pesos generales del producto (como antes). */
function currentWeightOptions(){
  const color = currentDetail.colors.find(c => c.id === selectedFlavorId);
  if(color && color.sizes && color.sizes.length) return color.sizes;
  return currentDetail.sizes;
}

function currentStock(){
  const color = currentDetail.colors.find(c => c.id === selectedFlavorId);
  if(color && color.sizes && color.sizes.length){
    const size = color.sizes.find(s => s.id === selectedWeightId);
    return size ? size.stock : 0;
  }
  let stock = color ? color.stock : currentDetail.stock;
  if(currentDetail.sizes.length){
    const size = currentDetail.sizes.find(s => s.id === selectedWeightId);
    const weightStock = size ? size.stock : 0;
    stock = color ? Math.min(stock, weightStock) : weightStock;
  }
  return stock;
}

function selectFlavor(flavorId){
  selectedFlavorId = flavorId;
  const weightOptions = currentWeightOptions();
  selectedWeightId = weightOptions.length ? weightOptions[0].id : null;
  renderProductDetail();
}

function selectWeight(weightId){
  selectedWeightId = weightId;
  renderProductDetail();
}

function relatedProducts(){
  return PRODUCTS.filter(p => p.cat === currentDetail.cat && p.id !== currentDetail.id).slice(0, 4);
}

/* Stock total de un sabor para pintarlo "sin stock": si tiene pesos
   propios, es la suma de esos pesos (el .stock plano del sabor ya no
   se actualiza en ese modo); si no, es el .stock de siempre. */
function flavorTotalStock(color){
  if(color.sizes && color.sizes.length) return color.sizes.reduce((s, sz) => s + sz.stock, 0);
  return color.stock;
}

function renderProductDetail(){
  const body = document.getElementById("productDetailBody");
  const images = currentGalleryImages();
  const stock = currentStock();
  const selectedFlavor = currentDetail.colors.find(c => c.id === selectedFlavorId);
  const weightOptions = currentWeightOptions();
  const selectedWeight = weightOptions.find(s => s.id === selectedWeightId);
  const related = relatedProducts();

  body.innerHTML = `
    <div class="product-detail">
      <div class="product-gallery">
        <div class="gallery-main"><img id="galleryMainImg" src="${images[0]}" alt="${currentDetail.name}" onclick="openImageLightbox(this.src, '${currentDetail.name.replace(/'/g, "\\'")}')"></div>
        ${images.length > 1 ? `<div class="gallery-thumbs">${images.map((img, i) => `
          <img src="${img}" class="${i === 0 ? "active" : ""}" onclick="setGalleryImage(this, '${img}')">
        `).join("")}</div>` : ""}
      </div>
      <div class="product-detail-info">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
          <span class="cat-tag">${currentDetail.catName}</span>
          <button type="button" class="share-btn" onclick="shareProduct()" title="Compartir" aria-label="Compartir producto">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 10.5 15.4 6.5M8.6 13.5l6.8 4"/></svg>
          </button>
        </div>
        <h2>${currentDetail.name}</h2>
        ${currentDetail.originalPrice
          ? `<span class="price-row"><span class="price-old">${formatPrice(currentDetail.originalPrice)}</span><span class="price">${formatPrice(currentDetail.price)}</span></span>`
          : `<span class="price">${formatPrice(currentDetail.price)}</span>`}
        ${installmentsHtml(currentDetail.price)}
        ${currentDetail.description ? `<p class="desc">${currentDetail.description}</p>` : ""}
        ${currentDetail.show_low_stock_badge && stock > 0 && stock <= LOW_STOCK_THRESHOLD ? `<span class="low-stock" style="margin-bottom:14px;">¡Últimas unidades!</span>` : ""}
        ${currentDetail.colors.length ? `
          <div class="color-picker">
            <h5>Sabor${selectedFlavor ? `: ${selectedFlavor.name}` : ""}</h5>
            <div class="color-options">
              ${currentDetail.colors.map(c => `
                <span class="color-swatch ${c.id === selectedFlavorId ? "selected" : ""} ${flavorTotalStock(c) <= 0 ? "out-of-stock" : ""}"
                      style="background:${c.hex};" title="${c.name}${flavorTotalStock(c) <= 0 ? " (sin stock)" : ""}"
                      onclick="selectFlavor(${c.id})"></span>
              `).join("")}
            </div>
          </div>
        ` : ""}
        ${weightOptions.length ? `
          <div class="size-picker">
            <h5>Peso${selectedWeight ? `: ${selectedWeight.name}` : ""}</h5>
            <div class="size-options">
              ${weightOptions.map(s => `
                <span class="size-pill ${s.id === selectedWeightId ? "selected" : ""} ${s.stock <= 0 ? "out-of-stock" : ""}"
                      title="${s.stock <= 0 ? "Sin stock" : ""}"
                      onclick="selectWeight(${s.id})">${s.name}</span>
              `).join("")}
            </div>
          </div>
        ` : ""}
        ${stock > 0
          ? `<button class="btn btn-primary" onclick="addToCartFromDetail()">${productDetailForCombo ? "Agregar al combo" : "Agregar al carrito"}</button>`
          : renderStockNotifyHtml()}
      </div>
      ${related.length ? `
      <div class="related-products">
        <h5>También te puede interesar</h5>
        <div class="related-grid">
          ${related.map(r => `
            <div class="related-card" onclick="openProductDetail(${r.id})">
              <img src="${r.img}" alt="${r.name}">
              <span>${r.name}</span>
              <span class="price">${formatPrice(r.price)}</span>
            </div>
          `).join("")}
        </div>
      </div>` : ""}
    </div>
    ${renderReviewsSectionHtml()}
  `;
  syncReviewStarInputUI();
}

/* "Avisame cuando haya stock": si la combinación elegida (sabor/peso, o
   el producto entero si no tiene variantes) está agotada, mostramos un
   mini-form para dejar el email en vez del botón de comprar. */
function renderStockNotifyHtml(){
  const email = accountData && accountData.email ? accountData.email : "";
  return `
    <button class="btn btn-primary" disabled style="opacity:.5;cursor:not-allowed;">Sin stock</button>
    <div class="stock-notify-box">
      <p class="stock-notify-label">¿Te avisamos por mail cuando vuelva a haber stock?</p>
      <div class="stock-notify-form">
        <input type="email" id="stockNotifyEmail" placeholder="Tu email" value="${email}">
        <button type="button" class="btn btn-outline btn-sm" onclick="submitStockNotify()">Avisame</button>
      </div>
      <p id="stockNotifyMsg" class="stock-notify-msg"></p>
    </div>
  `;
}

async function submitStockNotify(){
  const input = document.getElementById("stockNotifyEmail");
  const msgEl = document.getElementById("stockNotifyMsg");
  const email = (input.value || "").trim();
  if(!email || !email.includes("@")){
    msgEl.textContent = "Ingresá un email válido";
    msgEl.style.color = "#b34747";
    return;
  }
  const selectedFlavor = currentDetail.colors.find(c => c.id === selectedFlavorId);
  const selectedWeight = currentWeightOptions().find(s => s.id === selectedWeightId);
  try{
    const res = await fetch(`${API_BASE}/api/stock-notify`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        email, product_id: currentDetail.id,
        flavor_id: selectedFlavor ? selectedFlavor.id : null,
        weight_id: selectedWeight ? selectedWeight.id : null,
      }),
    });
    const data = await res.json();
    if(!res.ok){
      msgEl.textContent = data.error || "No se pudo guardar el aviso";
      msgEl.style.color = "#b34747";
      return;
    }
    input.disabled = true;
    document.querySelector(".stock-notify-form button").disabled = true;
    msgEl.textContent = "¡Listo! Te escribimos apenas haya stock.";
    msgEl.style.color = "#357a41";
  }catch(err){
    console.error(err);
    msgEl.textContent = "No se pudo guardar el aviso";
    msgEl.style.color = "#b34747";
  }
}

let reviewFormRating = 0;

function renderReviewsSectionHtml(){
  const reviews = currentDetail.reviews || [];
  const myId = accountData && accountData.id;
  const myReview = reviews.find(r => r.customer_id === myId);

  const summary = currentDetail.ratingCount
    ? `<div class="reviews-summary">${starsHtml(currentDetail.ratingAvg)} <strong>${currentDetail.ratingAvg}</strong> · ${currentDetail.ratingCount} reseña${currentDetail.ratingCount === 1 ? "" : "s"}</div>`
    : `<p style="color:var(--color-muted);font-size:0.88rem;margin-bottom:14px;">Todavía no tiene reseñas. ¡Sé la primera en opinar!</p>`;

  const list = reviews.map(r => `
    <div class="review-item">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
        <div>
          <span class="review-name">${r.customer_name}</span>
          ${r.verified ? `<span class="verified-badge">Compra verificada</span>` : ""}
        </div>
        ${r.customer_id === myId ? `<span class="remove-item" onclick="deleteMyReview(${r.id})">Borrar</span>` : ""}
      </div>
      <div>${starsHtml(r.rating)}</div>
      ${r.comment ? `<p class="review-comment">${r.comment}</p>` : ""}
      <p class="review-date">${new Date(r.created_at).toLocaleDateString("es-AR")}</p>
    </div>
  `).join("");

  const form = isLoggedIn ? `
    <div class="review-form">
      <h5 style="margin-bottom:10px;">${myReview ? "Editá tu reseña" : "Dejá tu reseña"}</h5>
      <div class="star-input" id="reviewStarInput">
        ${[1,2,3,4,5].map(n => `<span class="star" onclick="selectReviewStar(${n})">★</span>`).join("")}
      </div>
      <textarea id="reviewComment" placeholder="Contanos qué te pareció (opcional)">${myReview ? myReview.comment || "" : ""}</textarea>
      <button class="btn btn-outline btn-sm" style="margin-top:10px;" onclick="submitReview()">Publicar reseña</button>
    </div>
  ` : `
    <p style="font-size:0.85rem;color:var(--color-muted);margin-top:14px;">
      <a href="/login" style="color:var(--color-primary-dark);font-weight:600;">Iniciá sesión</a> para dejar tu reseña.
    </p>
  `;

  reviewFormRating = myReview ? myReview.rating : 0;

  return `
    <div class="reviews-section">
      <h5 style="margin-bottom:12px;">Reseñas de clientes</h5>
      ${summary}
      ${list}
      ${form}
    </div>
  `;
}

function selectReviewStar(n){
  reviewFormRating = n;
  document.querySelectorAll("#reviewStarInput .star").forEach((el, i) => {
    el.classList.toggle("filled", i < n);
  });
}

async function submitReview(){
  if(!reviewFormRating){
    showToast("Elegí una calificación de 1 a 5 estrellas");
    return;
  }
  const comment = document.getElementById("reviewComment").value.trim();
  try{
    const res = await fetch(`${API_BASE}/api/products/${currentDetail.id}/reviews`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ rating: reviewFormRating, comment }),
    });
    const data = await res.json();
    if(!res.ok){
      showToast(data.error || "No se pudo guardar la reseña");
      return;
    }
    showToast("¡Gracias por tu reseña!");
    await openProductDetail(currentDetail.id);
  }catch(err){
    console.error(err);
    showToast("No se pudo guardar la reseña");
  }
}

async function deleteMyReview(reviewId){
  if(!confirm("¿Borrar tu reseña?")) return;
  try{
    const res = await fetch(`${API_BASE}/api/reviews/${reviewId}`, { method: "DELETE" });
    const data = await res.json();
    if(!res.ok){
      showToast(data.error || "No se pudo borrar la reseña");
      return;
    }
    showToast("Reseña borrada");
    await openProductDetail(currentDetail.id);
  }catch(err){
    console.error(err);
    showToast("No se pudo borrar la reseña");
  }
}

/* Después de setear reviewFormRating (ej: al abrir la ficha con una
   reseña propia ya cargada), pintamos las estrellas del formulario. */
function syncReviewStarInputUI(){
  const container = document.getElementById("reviewStarInput");
  if(!container) return;
  container.querySelectorAll(".star").forEach((el, i) => {
    el.classList.toggle("filled", i < reviewFormRating);
  });
}

function shareProduct(){
  if(!currentDetail) return;
  const text = `¡Mirá "${currentDetail.name}" en BrainSuplementos! ${formatPrice(currentDetail.price)}`;
  const url = window.location.origin + window.location.pathname;

  if(navigator.share){
    navigator.share({ title: currentDetail.name, text, url }).catch(() => {});
  } else {
    const waUrl = `https://wa.me/?text=${encodeURIComponent(text + " " + url)}`;
    window.open(waUrl, "_blank");
  }
}

function setGalleryImage(thumbEl, url){
  document.getElementById("galleryMainImg").src = url;
  thumbEl.parentElement.querySelectorAll("img").forEach(el => el.classList.remove("active"));
  thumbEl.classList.add("active");
}

/* Visor de imagen a pantalla completa con zoom: se usa tanto para las
   fotos del detalle de producto como para la foto de tapa de un combo. */
function openImageLightbox(url, alt){
  const overlay = document.getElementById("imageLightbox");
  const frame = overlay.querySelector(".lightbox-frame");
  const img = document.getElementById("lightboxImg");
  img.src = url;
  img.alt = alt || "";
  frame.classList.remove("zoomed");
  frame.scrollTop = 0;
  frame.scrollLeft = 0;
  overlay.classList.add("show");
}

function closeImageLightbox(){
  document.getElementById("imageLightbox").classList.remove("show");
}

function toggleImageZoom(e){
  const frame = document.querySelector("#imageLightbox .lightbox-frame");
  const wasZoomed = frame.classList.contains("zoomed");
  frame.classList.toggle("zoomed");
  if(!wasZoomed){
    // Centramos el zoom más o menos en el punto donde tocó el usuario.
    const img = document.getElementById("lightboxImg");
    requestAnimationFrame(() => {
      const rect = frame.getBoundingClientRect();
      const px = e && e.clientX ? (e.clientX - rect.left) / rect.width : 0.5;
      const py = e && e.clientY ? (e.clientY - rect.top) / rect.height : 0.5;
      frame.scrollLeft = img.scrollWidth * px - rect.width / 2;
      frame.scrollTop = img.scrollHeight * py - rect.height / 2;
    });
  }
}

function addToCartFromDetail(){
  if(!currentDetail) return;
  const stock = currentStock();
  if(stock <= 0) return;
  const selectedFlavor = currentDetail.colors.find(c => c.id === selectedFlavorId);
  const selectedWeight = currentWeightOptions().find(s => s.id === selectedWeightId);
  const cartId = currentDetail.id;
  const flavorId = selectedFlavor ? selectedFlavor.id : null;
  const flavorName = selectedFlavor ? selectedFlavor.name : null;
  const weightId = selectedWeight ? selectedWeight.id : null;
  const weightName = selectedWeight ? selectedWeight.name : null;
  const img = currentGalleryImages()[0];
  const variant = [flavorName, weightName ? `Peso ${weightName}` : null].filter(Boolean).join(" · ");

  // "Armá tu combo": esto NO va al carrito real, va a la selección que
  // está armando el cliente en esa sección — se confirma toda junta
  // recién cuando toca "Agregar combo al carrito".
  if(productDetailForCombo){
    addComboBuilderItem({
      id: cartId, name: currentDetail.name, price: currentDetail.price, img,
      flavorId, flavorName, weightId, weightName,
    });
    showToast(`${currentDetail.name}${variant ? " · " + variant : ""} agregado al combo`);
    closeProductDetail();
    return;
  }

  const existing = cart.find(i => i.id === cartId && (i.flavorId || null) === flavorId && (i.weightId || null) === weightId);
  if(existing){ existing.qty += 1; } else {
    cart.push({
      id: cartId, name: currentDetail.name, price: currentDetail.price, img,
      flavorId, flavorName, weightId, weightName, qty: 1
    });
  }
  saveCart();
  showToast(`${currentDetail.name}${variant ? " · " + variant : ""} agregado al carrito`);
  closeProductDetail();
  // Si este producto se abrió porque faltaba elegir sabor/peso dentro de
  // un combo armado desde el panel admin, seguimos con el próximo
  // producto pendiente de ese combo.
  continuePendingSetVariantQueue();
}

function openCheckout(){
  if(cart.length === 0) return;
  if(!isLoggedIn){
    showToast("Necesitás una cuenta para comprar, te llevamos a iniciar sesión");
    setTimeout(() => {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }, 900);
    return;
  }
  prefillCheckoutForm();
  renderShippingZones();
  renderCheckoutSummary();
  goToEntregaStep();
  document.getElementById("checkoutModal").classList.add("show");
}

/* Checkout en 2 pasos (Entrega → Pago), con "Carrito" ya marcado como
   hecho porque para llegar acá la persona ya revisó el carrito. */
function goToPagoStep(){
  const first = document.getElementById("custFirstName");
  const last = document.getElementById("custLastName");
  const phone = document.getElementById("custPhone");
  if(!first.reportValidity() || !last.reportValidity() || !phone.reportValidity()) return;

  document.getElementById("stepEntrega").style.display = "none";
  document.getElementById("stepPago").style.display = "block";

  document.getElementById("stepIndicatorEntrega").classList.remove("active");
  document.getElementById("stepIndicatorEntrega").classList.add("done");
  document.getElementById("stepIndicatorPago").classList.add("active");

  renderCheckoutRecap();
  loadPaymentMethods();
}

function goToEntregaStep(){
  document.getElementById("stepPago").style.display = "none";
  document.getElementById("stepEntrega").style.display = "block";

  document.getElementById("stepIndicatorEntrega").classList.remove("done");
  document.getElementById("stepIndicatorEntrega").classList.add("active");
  document.getElementById("stepIndicatorPago").classList.remove("active");

  unmountCardBrick();
}

function renderCheckoutRecap(){
  const delivery = document.getElementById("deliveryMethod").value;
  const address = getFullAddress();
  const recap = document.getElementById("checkoutRecap");
  recap.innerHTML = `
    <div>
      <strong>${getFullName()}</strong> · ${document.getElementById("custPhone").value}<br>
      ${delivery}${delivery === "Envío a domicilio" && address ? ` — ${address}` : ""}
    </div>
    <button type="button" class="recap-change" onclick="goToEntregaStep()">Cambiar</button>
  `;
}

function renderCheckoutSummary(){
  const box = document.getElementById("checkoutSummary");
  box.innerHTML = cart.map(i => {
    const variant = [i.flavorName, i.weightName ? `Peso ${i.weightName}` : null].filter(Boolean).join(" · ");
    return `
      <div class="checkout-summary-item">
        <img src="${i.img || 'https://placehold.co/100x120/eee/999?text=%20'}" alt="${i.name}">
        <div class="csi-info">
          <div class="csi-name">${i.name}</div>
          ${variant ? `<div class="csi-variant">${variant}</div>` : ""}
          <div class="csi-qty">Cantidad: ${i.qty}</div>
        </div>
        <div class="csi-price">${formatPrice(i.price * i.qty)}</div>
      </div>
    `;
  }).join("") + `
    <div class="coupon-box">
      ${appliedCoupon ? `
        <div class="coupon-applied">
          <span>Cupón <strong>${appliedCoupon.code}</strong> (-${appliedCoupon.percent_off}%)</span>
          <span class="remove-item" onclick="removeCoupon()">Quitar</span>
        </div>
      ` : `
        <div class="coupon-form">
          <input type="text" id="couponInput" placeholder="Código de descuento" style="text-transform:uppercase;">
          <button type="button" class="btn btn-outline btn-sm" onclick="applyCoupon()">Aplicar</button>
        </div>
      `}
      <p id="couponMsg" class="coupon-msg"></p>
    </div>
    ${appliedCoupon ? `
    <div class="checkout-summary-subtotal">
      <span>Subtotal</span>
      <span>${formatPrice(cartTotal())}</span>
    </div>
    <div class="checkout-summary-subtotal discount-line">
      <span>Descuento (${appliedCoupon.code})</span>
      <span>-${formatPrice(cartDiscount())}</span>
    </div>
    ` : ""}
    ${document.getElementById("deliveryMethod").value === "Envío a domicilio" && shippingZones.length ? `
    <div class="checkout-summary-subtotal">
      <span>Envío</span>
      <span>${cartShippingCost() > 0 ? formatPrice(cartShippingCost()) : "Gratis"}</span>
    </div>
    ` : ""}
    <div class="checkout-summary-total">
      <span>Total</span>
      <span>${formatPrice(cartGrandTotal())}</span>
    </div>
  `;
}
function closeCheckout(){
  document.getElementById("checkoutModal").classList.remove("show");
  unmountCardBrick();
}

/* Los medios de pago que se ven acá los prende/apaga tu equipo desde
   /admin/pagos. "Efectivo" y "Transferencia bancaria" avisan por WhatsApp
   como siempre ("Efectivo" sirve tanto para pagar al recibir el envío
   como al retirar en el local: eso lo define la "Forma de entrega", que
   es un campo aparte). "Mercado Pago" redirige al checkout alojado por
   Mercado Pago. "Tarjeta de crédito/débito" se combinan en una sola
   opción: si hay MP_PUBLIC_KEY configurada, el formulario de tarjeta
   aparece embebido acá mismo (el número nunca llega a nuestro servidor,
   lo tokeniza el SDK de Mercado Pago en el navegador); si todavía no está
   esa clave, cae al mismo checkout redirigido que Mercado Pago. */
let mpInstance = null;
let cardBrickController = null;

async function loadPaymentMethods(){
  const container = document.getElementById("payOptions");
  const acceptedEl = document.getElementById("acceptedCards");
  let settings = { efectivo: true, transferencia: true, tarjeta_credito: true, tarjeta_debito: true, mercado_pago: true, tarjetas_aceptadas: "" };
  let mpConfig = { public_key: null };

  try{
    const [settingsRes, mpConfigRes] = await Promise.all([
      fetch(`${API_BASE}/api/payment-methods`),
      fetch(`${API_BASE}/api/mp-config`),
    ]);
    if(settingsRes.ok) settings = await settingsRes.json();
    if(mpConfigRes.ok) mpConfig = await mpConfigRes.json();
  }catch(err){
    console.error("No se pudieron cargar los medios de pago, se muestran todos por defecto", err);
  }

  const cardFormAvailable = !!mpConfig.public_key;

  const options = [];
  if(settings.mercado_pago){
    options.push({ value: "Mercado Pago", label: "Mercado Pago (dinero en cuenta)", mode: "redirect" });
  }
  if(settings.tarjeta_credito || settings.tarjeta_debito){
    options.push(cardFormAvailable
      ? { value: "Tarjeta", label: "Tarjeta de crédito o débito", mode: "embedded" }
      : { value: "Tarjeta de crédito", label: "Tarjeta de crédito o débito", mode: "redirect" });
  }
  if(settings.transferencia){
    options.push({ value: "Transferencia bancaria", label: "Transferencia bancaria", mode: "whatsapp" });
  }
  if(settings.efectivo){
    options.push({ value: "Efectivo", label: "Efectivo (en el local)", mode: "whatsapp" });
  }

  if(options.length === 0){
    container.innerHTML = `<p style="font-size:0.82rem;color:var(--color-muted);">Todavía no hay medios de pago configurados. Escribinos por WhatsApp para coordinar tu compra.</p>`;
    return;
  }

  container.innerHTML = options.map((m, i) => `
    <label class="pay-option"><input type="radio" name="payMethod" value="${m.value}" data-mode="${m.mode}" ${i === 0 ? "checked" : ""}> ${m.label}</label>
  `).join("");

  container.querySelectorAll('input[name="payMethod"]').forEach(input => {
    input.addEventListener("change", updateCheckoutPaymentUi);
  });
  updateCheckoutPaymentUi();

  if(settings.tarjetas_aceptadas){
    acceptedEl.innerHTML = `<span class="accepted-cards-label">Tarjetas aceptadas:</span> ${renderCardBrandBadges(settings.tarjetas_aceptadas)}`;
    acceptedEl.style.display = "flex";
  } else {
    acceptedEl.style.display = "none";
  }
}

/* Mapea nombres de tarjetas (lo que tu equipo escribe en /admin/pagos) a un
   logo con el color/estilo de cada marca. Lo que no reconoce lo muestra
   igual, como una etiqueta genérica con el texto tal cual lo escribió. */
const CARD_BRAND_BADGES = {
  "visa": { label: "VISA", cls: "cb-visa" },
  "mastercard": { label: "mastercard", cls: "cb-mastercard" },
  "master card": { label: "mastercard", cls: "cb-mastercard" },
  "amex": { label: "AMEX", cls: "cb-amex" },
  "american express": { label: "AMEX", cls: "cb-amex" },
  "naranja": { label: "naranja", cls: "cb-naranja" },
  "cabal": { label: "cabal", cls: "cb-cabal" },
  "cencosud": { label: "Cencosud", cls: "cb-cencosud" },
  "tarjeta shopping": { label: "T. Shopping", cls: "cb-generic" },
  "nativa": { label: "Nativa", cls: "cb-generic" },
};

function renderCardBrandBadges(text){
  return text.split(",").map(s => s.trim()).filter(Boolean).map(name => {
    const brand = CARD_BRAND_BADGES[name.toLowerCase()];
    return brand
      ? `<span class="card-brand-badge ${brand.cls}">${brand.label}</span>`
      : `<span class="card-brand-badge cb-generic">${name}</span>`;
  }).join("");
}

function updateCheckoutPaymentUi(){
  const checked = document.querySelector('input[name="payMethod"]:checked');
  const cardContainer = document.getElementById("cardPaymentBrick");
  const submitBtn = document.getElementById("checkoutSubmitBtn");
  if(!checked) return;

  // La transferencia bancaria pide el DNI del titular de la cuenta de
  // origen, así se puede validar que coincida con el que efectivamente
  // hizo la transferencia (igual que en los checkouts de referencia).
  const transferGroup = document.getElementById("transferDniGroup");
  const dniInput = document.getElementById("custTransferDni");
  if(checked.value === "Transferencia bancaria"){
    transferGroup.style.display = "block";
    dniInput.required = true;
  } else {
    transferGroup.style.display = "none";
    dniInput.required = false;
  }

  if(checked.dataset.mode === "embedded"){
    cardContainer.style.display = "block";
    submitBtn.style.display = "none";
    ensureCardBrick();
  } else {
    cardContainer.style.display = "none";
    unmountCardBrick();
    submitBtn.style.display = "block";
    submitBtn.textContent = checked.dataset.mode === "whatsapp" ? "Enviar pedido por WhatsApp" : "Ir a pagar";
  }
}

function unmountCardBrick(){
  if(cardBrickController){
    cardBrickController.unmount().catch(() => {});
    cardBrickController = null;
  }
}

async function ensureCardBrick(){
  const container = document.getElementById("cardPaymentBrick");
  if(typeof MercadoPago === "undefined"){
    container.innerHTML = `<p style="font-size:0.82rem;color:var(--color-muted);">No se pudo cargar el formulario de tarjeta.</p>`;
    return;
  }
  try{
    const res = await fetch(`${API_BASE}/api/mp-config`);
    const config = await res.json();
    if(!config.public_key) return;

    if(!mpInstance){
      mpInstance = new MercadoPago(config.public_key, { locale: "es-AR" });
    }
    unmountCardBrick();
    container.innerHTML = "";

    const bricksBuilder = mpInstance.bricks();
    cardBrickController = await bricksBuilder.create("cardPayment", "cardPaymentBrick", {
      initialization: { amount: cartGrandTotal() },
      callbacks: {
        onReady: () => {},
        onError: (error) => {
          console.error(error);
          showToast("No se pudo procesar la tarjeta, revisá los datos e intentá de nuevo");
        },
        onSubmit: (cardFormData) => submitCardPayment(cardFormData),
      },
    });
  }catch(err){
    console.error(err);
    container.innerHTML = `<p style="font-size:0.82rem;color:var(--color-muted);">No se pudo cargar el formulario de tarjeta.</p>`;
  }
}

function submitCardPayment(cardFormData){
  return new Promise((resolve, reject) => {
    const name = getFullName();
    const phone = document.getElementById("custPhone").value;
    const delivery = document.getElementById("deliveryMethod").value;
    const address = getFullAddress();

    if(!name || !phone){
      showToast("Completá tu nombre y teléfono antes de pagar");
      reject();
      return;
    }

    fetch(`${API_BASE}/api/orders/card-payment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name, phone,
        delivery_method: delivery,
        delivery_address: delivery === "Envío a domicilio" ? address : null,
        coupon_code: appliedCoupon ? appliedCoupon.code : null,
        shipping_zone_id: delivery === "Envío a domicilio" ? selectedShippingZoneId : null,
        items: cart.map(i => ({
          product_id: i.id, name: i.name, price: i.price, qty: i.qty,
          flavor_id: i.flavorId || null, flavor_name: i.flavorName || null,
          weight_id: i.weightId || null, weight_label: i.weightName || null,
        })),
        token: cardFormData.token,
        payment_method_id: cardFormData.payment_method_id,
        issuer_id: cardFormData.issuer_id,
        installments: cardFormData.installments,
        payer: cardFormData.payer,
      }),
    })
      .then(async res => {
        if(res.status === 401){
          showToast("Tu sesión venció, iniciá sesión de nuevo");
          setTimeout(() => {
            window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
          }, 900);
          reject();
          return;
        }
        const data = await res.json().catch(() => ({}));
        if(res.status === 409){
          showToast(data.error || "Uno de los productos ya no tiene stock suficiente");
          reject();
          return;
        }
        if(!res.ok && res.status !== 502){
          showToast("No se pudo procesar el pago, intentá de nuevo");
          reject();
          return;
        }

        cart = [];
        appliedCoupon = null;
        selectedShippingZoneId = null;
        saveCart();
        resolve();

        const dest = data.status === "pagado" ? "exito" : data.status === "cancelado" ? "error" : "pendiente";
        window.location.href = `/pago/${dest}?order_id=${data.order_id}`;
      })
      .catch(err => {
        console.error(err);
        showToast("No se pudo procesar el pago, intentá de nuevo");
        reject();
      });
  });
}

document.getElementById("deliveryMethod").addEventListener("change", function(){
  // La zona de envío vive adentro de #addressGroup, así que se
  // muestra/oculta junto con la dirección sin necesitar otro toggle.
  document.getElementById("addressGroup").style.display = this.value === "Envío a domicilio" ? "block" : "none";
  renderShippingZones();
  renderCheckoutSummary();
  refreshCardBrickAmount();
});

document.getElementById("checkoutForm").addEventListener("submit", submitOrder);

async function submitOrder(e){
  e.preventDefault();
  const name = getFullName();
  const phone = document.getElementById("custPhone").value;
  const delivery = document.getElementById("deliveryMethod").value;
  const address = getFullAddress();
  let payMethod = document.querySelector('input[name="payMethod"]:checked').value;
  if(payMethod === "Transferencia bancaria"){
    const dni = (document.getElementById("custTransferDni").value || "").trim();
    if(dni) payMethod = `Transferencia bancaria (DNI titular: ${dni})`;
  }
  const submitBtn = e.target.querySelector('button[type="submit"]');

  submitBtn.disabled = true;
  submitBtn.textContent = "Guardando pedido...";

  try{
    const res = await fetch(`${API_BASE}/api/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name, phone,
        delivery_method: delivery,
        delivery_address: delivery === "Envío a domicilio" ? address : null,
        payment_method: payMethod,
        coupon_code: appliedCoupon ? appliedCoupon.code : null,
        shipping_zone_id: delivery === "Envío a domicilio" ? selectedShippingZoneId : null,
        items: cart.map(i => ({
          product_id: i.id, name: i.name, price: i.price, qty: i.qty,
          flavor_id: i.flavorId || null, flavor_name: i.flavorName || null,
          weight_id: i.weightId || null, weight_label: i.weightName || null
        }))
      })
    });
    if(res.status === 401){
      showToast("Tu sesión venció, iniciá sesión de nuevo");
      submitBtn.disabled = false;
      updateCheckoutPaymentUi();
      setTimeout(() => {
        window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
      }, 900);
      return;
    }
    if(res.status === 409){
      const data = await res.json().catch(() => ({}));
      showToast(data.error || "Uno de los productos ya no tiene stock suficiente");
      submitBtn.disabled = false;
      updateCheckoutPaymentUi();
      return;
    }
    if(!res.ok) throw new Error("El servidor devolvió un error");

    const data = await res.json();
    if(data.checkout_url){
      // Se creó el pedido y Mercado Pago está configurado: mandamos a la
      // persona directo al checkout alojado por MP en vez de a WhatsApp.
      cart = [];
      appliedCoupon = null;
      selectedShippingZoneId = null;
      saveCart();
      showToast("Redirigiendo a Mercado Pago...");
      window.location.href = data.checkout_url;
      return;
    }
  }catch(err){
    console.error(err);
    showToast("No se pudo guardar el pedido, pero te derivamos a WhatsApp igual");
  }

  let msg = `¡Hola BrainSuplementos! Quiero hacer un pedido:%0A%0A`;
  cart.forEach(i => {
    const variant = [i.flavorName, i.weightName ? `Peso ${i.weightName}` : null].filter(Boolean).join(", ");
    msg += `• ${i.name}${variant ? ` (${variant})` : ""} x${i.qty} — ${formatPrice(i.price * i.qty)}%0A`;
  });
  msg += `%0A*Total: ${formatPrice(cartGrandTotal())}*%0A%0A`;
  msg += `Nombre: ${name}%0ATeléfono: ${phone}%0AEntrega: ${delivery}`;
  if(delivery === "Envío a domicilio") msg += `%0ADirección: ${address}`;
  msg += `%0AMétodo de pago: ${payMethod}`;

  const url = `https://wa.me/${WHATSAPP_NUMBER}?text=${msg}`;
  window.open(url, "_blank");

  cart = [];
  appliedCoupon = null;
  selectedShippingZoneId = null;
  saveCart();
  closeCheckout();
  closeCart();
  submitBtn.disabled = false;
  submitBtn.textContent = "Enviar pedido por WhatsApp";
  showToast("¡Pedido enviado! Te esperamos en WhatsApp");
}

function showToast(text){
  const toast = document.getElementById("toast");
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2500);
}

function toggleMobileMenu(){
  const m = document.getElementById("mobileMenu");
  if(m.style.display === "flex"){
    closeMobileMenu();
  } else {
    m.style.display = "flex";
    fitMobileMenuToScreen();
  }
}

/* El header es "sticky" (queda pegado arriba al scrollear). Si el menú
   desplegado (con "Productos" abierto y muchas categorías/subcategorías)
   termina siendo más alto que la pantalla, al estar pegado arriba no hay
   forma de bajar la página para ver el resto — queda cortado. Por eso el
   menú tiene su propio scroll interno, con una altura máxima calculada
   según el espacio real que queda debajo del header en la pantalla. */
function fitMobileMenuToScreen(){
  const m = document.getElementById("mobileMenu");
  if(!m) return;
  const top = m.getBoundingClientRect().top;
  const maxHeight = Math.max(200, window.innerHeight - top - 12);
  m.style.maxHeight = maxHeight + "px";
  m.style.overflowY = "auto";
}
window.addEventListener("resize", () => {
  const m = document.getElementById("mobileMenu");
  if(m && m.style.display === "flex") fitMobileMenuToScreen();
});

function closeMobileMenu(){
  const m = document.getElementById("mobileMenu");
  if(m) m.style.display = "none";
  // Al cerrar el menú, el acordeón de "Productos" vuelve a arrancar
  // cerrado la próxima vez que lo abran.
  const mega = document.getElementById("megaMenu");
  const chevron = document.getElementById("megaMenuChevron");
  if(mega) mega.style.display = "none";
  if(chevron) chevron.classList.remove("open");
}

/* CONJUNTOS: looks armados por tu equipo desde /admin/combos con
   productos que ya existen en el catálogo. Cada producto mantiene su
   propio precio y stock — el combo es solo una forma de mostrarlos
   juntos y agregarlos todos al carrito de una sola vez. */
let SETS_BY_ID = {};

async function loadSets(){
  try{
    const res = await fetch(`${API_BASE}/api/sets`);
    if(!res.ok) return;
    const sets = await res.json();
    renderSets(sets);
  }catch(err){
    console.error("No se pudieron cargar los combos", err);
  }
}

/* Precio "de catálogo" de cada producto del combo, ya con su propio
   % de descuento (si tiene) aplicado — es la base sobre la que se
   prorratea el precio especial del combo, si la dueña cargó uno. */
function setItemBasePrice(it){
  // El precio de cada producto dentro de un combo es el que se carga
  // puntualmente para ESE combo en /admin/combos — se ignora por
  // completo el precio (y el descuento) que tenga ese producto en el
  // catálogo normal.
  return it.price;
}

/* Si el combo tiene un precio especial (menor a la suma normal de sus
   productos), esto da el precio "prorrateado" que le toca a cada
   producto individual para que la suma dé exactamente ese precio
   especial (en vez de cobrar de más o de menos al agregarlos al carrito
   uno por uno). Si no hay precio especial, devuelve el precio normal. */
function setItemEffectivePrice(set, it){
  const basePrice = setItemBasePrice(it);
  const catalogTotal = set.items.reduce((sum, x) => sum + setItemBasePrice(x), 0);
  const hasSetDiscount = set.discount_price !== null && set.discount_price !== undefined
    && catalogTotal > 0 && set.discount_price < catalogTotal;
  if(!hasSetDiscount) return basePrice;
  return Math.round(basePrice * (set.discount_price / catalogTotal));
}

function renderSets(sets){
  const section = document.getElementById("combos");
  const grid = document.getElementById("setsGrid");
  if(!sets || !sets.length){
    section.style.display = "none";
    return;
  }
  SETS_BY_ID = {};
  sets.forEach(s => { SETS_BY_ID[s.id] = s; });

  section.style.display = "block";
  grid.innerHTML = sets.map(s => {
    let catalogTotal = 0;
    const itemsHtml = s.items.map(it => {
      const finalPrice = setItemBasePrice(it);
      catalogTotal += finalPrice;
      return `
        <div class="set-item" onclick="openProductDetail(${it.id})" title="Ver ${it.name}">
          <img src="${it.image_url || 'https://placehold.co/100x120/eee/999?text=%20'}" alt="${it.name}">
          <span class="set-item-name">${it.name}</span>
          <span class="set-item-price">${formatPrice(finalPrice)}</span>
        </div>
      `;
    }).join("");
    const coverImage = s.image_url || (s.items[0] && s.items[0].image_url) || "https://placehold.co/400x300/eee/999?text=%20";
    const hasSetDiscount = s.discount_price !== null && s.discount_price !== undefined && s.discount_price < catalogTotal;
    const totalHtml = hasSetDiscount
      ? `<div class="set-total">Total: <span class="price-old">${formatPrice(catalogTotal)}</span> <strong>${formatPrice(s.discount_price)}</strong></div>`
      : `<div class="set-total">Total: <strong>${formatPrice(catalogTotal)}</strong></div>`;
    return `
      <div class="set-card">
        <div class="set-cover-wrap">
          <img class="set-cover" src="${coverImage}" alt="${s.name}" onclick="openImageLightbox('${coverImage}', '${s.name.replace(/'/g, "\\'")}')">
        </div>
        <div class="set-info">
          <h3>${s.name}</h3>
          ${s.description ? `<p class="set-desc">${s.description}</p>` : ""}
          <div class="set-items">${itemsHtml}</div>
          ${totalHtml}
          <button class="btn btn-primary" onclick="addSetToCart(${s.id})">Agregar combo al carrito</button>
        </div>
      </div>
    `;
  }).join("");
}

async function loadBrands(){
  try{
    const res = await fetch(`${API_BASE}/api/brands`);
    if(!res.ok) return;
    const brands = await res.json();
    renderBrands(brands);
  }catch(err){
    console.error("No se pudieron cargar las marcas", err);
  }
}

function renderBrands(brands){
  const section = document.getElementById("brandsMarquee");
  const track = document.getElementById("brandsTrack");
  if(!section || !track) return;
  if(!brands || !brands.length){
    section.style.display = "none";
    return;
  }
  section.style.display = "block";
  const logosHtml = brands.map(b => {
    const img = `<img src="${b.image_url}" alt="${b.name}" loading="lazy">`;
    return b.link
      ? `<a href="${b.link}" target="_blank" rel="noopener" title="${b.name}">${img}</a>`
      : `<span title="${b.name}">${img}</span>`;
  }).join("");
  // Si hay pocas marcas cargadas, una sola tanda de logos no llega a
  // ocupar el ancho de la pantalla y la cinta queda con los logos
  // amontonados a la izquierda y un hueco en blanco enorme al lado.
  // Para evitarlo, se repite la tanda las veces que hagan falta hasta
  // llenar bien el ancho, y recién ahí se duplica todo x2 para que el
  // loop de la animación no se note el corte al volver al principio.
  const repeats = Math.max(1, Math.ceil(8 / brands.length));
  const oneSet = logosHtml.repeat(repeats);
  track.innerHTML = oneSet + oneSet;
  initBrandsLensEffect();
}

/* Efecto "lente": mientras la cinta de marcas se desliza, el logo que
   pasa por el centro del cartel se agranda, se enfoca (sin blur) y queda
   bien opaco; a medida que se aleja del centro se achica, se desenfoca
   un poco y se transparenta, como si hubiera una lupa fija en el medio.
   Se recalcula en cada frame con la posición real de cada logo (no con
   CSS puro) porque la cinta se mueve con una animación infinita y hay
   que medir contra el centro del cartel, no contra el viewport. Se
   arranca/para solo con IntersectionObserver para no gastar CPU de
   más cuando la sección no está a la vista. */
let brandsLensRAF = null;
let brandsLensObserver = null;
function initBrandsLensEffect(){
  const section = document.getElementById("brandsMarquee");
  const viewport = section ? section.querySelector(".marquee-viewport") : null;
  const track = document.getElementById("brandsTrack");
  if(!section || !viewport || !track) return;
  // El efecto "lente" (agrandar/enfocar el logo del centro y difuminar el
  // resto) se pensó para el cartel ancho de compu, donde entran varios
  // logos completos a la vez. En el celular el cartel es angosto y con
  // pocos logos visibles: el radio de foco terminaba agarrando un solo
  // logo por vez, y el resto quedaba mitad borroso/achicado todo el
  // tiempo — se veía como si algo estuviera roto en vez de un efecto
  // sutil. Por eso en pantallas chicas se deja la cinta sin ese zoom:
  // todos los logos parejos, nítidos y del mismo tamaño, solo con el
  // desplazamiento automático.
  const isMobileMarquee = () => window.matchMedia("(max-width: 640px)").matches;

  function resetLogos(){
    track.querySelectorAll("img").forEach(img => {
      img.style.transform = "";
      img.style.opacity = "";
      img.style.filter = "";
    });
  }

  function tick(){
    if(isMobileMarquee()){
      resetLogos();
      brandsLensRAF = null;
      return;
    }
    const vpRect = viewport.getBoundingClientRect();
    const centerX = vpRect.left + vpRect.width / 2;
    // El radio de foco se banca del ancho real del cartel: en pantallas
    // angostas un radio fijo grande dejaba TODOS los logos a medio
    // desenfocar sin que ninguno llegue a verse nítido. Con esto siempre
    // hay una zona central proporcional a la pantalla bien enfocada.
    const FOCUS_RADIUS = Math.max(130, vpRect.width * 0.32);
    track.querySelectorAll("img").forEach(img => {
      const r = img.getBoundingClientRect();
      const imgCenter = r.left + r.width / 2;
      const dist = Math.min(Math.abs(imgCenter - centerX), FOCUS_RADIUS);
      const t = 1 - dist / FOCUS_RADIUS; // 1 en el centro, 0 en el borde del radio de foco
      img.style.transform = `scale(${(1 + t * 0.26).toFixed(3)})`;
      img.style.opacity = (0.55 + t * 0.45).toFixed(3);
      img.style.filter = `blur(${((1 - t) * 1.2).toFixed(2)}px)`;
    });
    brandsLensRAF = requestAnimationFrame(tick);
  }
  if(brandsLensObserver) brandsLensObserver.disconnect();
  brandsLensObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if(entry.isIntersecting){
        if(!brandsLensRAF) tick();
      }else if(brandsLensRAF){
        cancelAnimationFrame(brandsLensRAF);
        brandsLensRAF = null;
      }
    });
  }, {threshold:0});
  brandsLensObserver.observe(section);

  // Si gira el celular o cambia el tamaño de ventana cruzando el punto de
  // corte de 640px, retomamos (o dejamos de aplicar) el efecto según
  // corresponda, sin esperar a que la sección salga y vuelva a entrar en
  // pantalla.
  window.addEventListener("resize", () => {
    if(isMobileMarquee()) resetLogos();
    else if(!brandsLensRAF && brandsLensObserver) tick();
  });
}

/* Arma directamente el item de carrito con los datos que ya trae
   /api/sets (no depende de que el producto esté en el PRODUCTS del
   catálogo actual, que puede estar filtrado por categoría). `price` ya
   viene calculado (normal o prorrateado si el combo tiene precio
   especial) — no se recalcula acá para no aplicar el descuento 2 veces. */
function addSetItemToCart(item, price){
  const existing = cart.find(i => i.id === item.id && !i.flavorId && !i.weightId);
  if(existing){
    existing.qty += 1;
  } else {
    cart.push({
      id: item.id, name: item.name, price, img: item.image_url,
      flavorId: null, flavorName: null, weightId: null, weightName: null, qty: 1,
    });
  }
}

function addSetToCart(setId){
  const set = SETS_BY_ID[setId];
  if(!set) return;

  let added = 0;
  const needsVariant = [];
  set.items.forEach(it => {
    const price = setItemEffectivePrice(set, it);
    if(it.has_variants){
      needsVariant.push({ item: it, price });
    } else {
      addSetItemToCart(it, price);
      added++;
    }
  });
  saveCart();

  if(needsVariant.length > 0){
    // En vez de solo avisar que hace falta elegir sabor/peso, abrimos
    // directo la ficha del primer producto que lo necesita — igual que
    // si el cliente hubiera tocado ese producto desde el catálogo.
    if(added > 0){
      showToast(`Se agregaron ${added} producto${added === 1 ? "" : "s"} del combo. Elegí sabor/peso para el resto.`);
    }
    if(needsVariant.length > 1){
      pendingSetVariantQueue = needsVariant.slice(1);
    }
    openSetVariantItem(needsVariant[0]);
  } else {
    showToast("¡Combo agregado al carrito!");
  }
}

/* Si un combo tiene más de un producto con sabor/peso, después de
   elegir el primero seguimos ofreciendo el siguiente automáticamente en
   vez de dejar que el cliente tenga que ir a buscarlo a mano. Cada
   entrada de la cola es {item, price} — el precio ya viene prorrateado
   si el combo tiene un precio especial cargado. */
let pendingSetVariantQueue = [];

async function openSetVariantItem(entry){
  await openProductDetail(entry.item.id);
  // Si el combo tiene precio especial, el precio de este producto en
  // el carrito tiene que ser el prorrateado (entry.price) y no el precio
  // de catálogo que acaba de cargar la ficha — lo pisamos acá y volvemos
  // a pintar para que se vea tachado el precio normal.
  if(entry.price !== currentDetail.price){
    currentDetail.originalPrice = currentDetail.originalPrice || currentDetail.price;
    currentDetail.price = entry.price;
    renderProductDetail();
  }
}

function continuePendingSetVariantQueue(){
  if(!pendingSetVariantQueue.length) return;
  const next = pendingSetVariantQueue.shift();
  showToast(`Ahora elegí sabor/peso para "${next.item.name}"`);
  openSetVariantItem(next);
}

/* ================= ARMÁ TU COMBO (cliente arma el suyo) =================
   A diferencia de los combos de "product_sets" (armados desde el panel
   admin, con precio fijo), acá el cliente elige productos sueltos del
   catálogo. Por ahora no tiene descuento propio (queda pendiente definir
   cómo se calcula, ver charla con el equipo) — solo suma los precios de
   catálogo, y exige un mínimo de productos antes de poder confirmarlo. */
const MIN_COMBO_ITEMS = 4;
let COMBO_PRODUCTS = [];
let comboSelection = [];
let comboProductsLoaded = false;

function openComboBuilder(){
  document.getElementById("comboBuilderModal").classList.add("show");
  // El catálogo para el combo se pide recién la primera vez que se abre
  // el modal (no al cargar la home) — así no se hace ese fetch de más si
  // el cliente nunca llega a usar "Armá tu combo".
  if(!comboProductsLoaded){
    comboProductsLoaded = true;
    loadComboBuilderProducts();
  }
}

function closeComboBuilder(){
  document.getElementById("comboBuilderModal").classList.remove("show");
}

async function loadComboBuilderProducts(){
  const grid = document.getElementById("comboProductGrid");
  try{
    const res = await fetch(`${API_BASE}/api/products`);
    if(!res.ok) throw new Error("respuesta no OK");
    const data = await res.json();
    COMBO_PRODUCTS = data.map(mapProductApiToClient);
    renderComboBuilder();
  }catch(err){
    console.error(err);
    if(grid) grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:#b34747;">No se pudo cargar el catálogo para armar el combo.</p>`;
  }
}

function onComboBuilderSearch(){ renderComboBuilder(); }

function comboBuilderFilteredProducts(){
  const q = (document.getElementById("comboSearchInput").value || "").trim().toLowerCase();
  if(!q) return COMBO_PRODUCTS;
  return COMBO_PRODUCTS.filter(p => p.name.toLowerCase().includes(q));
}

// Cantidad ya elegida de un producto SIN sabor/peso (los que tienen
// variantes se identifican por sabor+peso, no tiene sentido un contador
// único en la tarjeta — para esos, cada click abre la ficha de nuevo).
function comboQtyFor(id){
  const line = comboSelection.find(i => i.id === id && !i.flavorId && !i.weightId);
  return line ? line.qty : 0;
}

function renderComboBuilder(){
  const grid = document.getElementById("comboProductGrid");
  if(!grid) return;
  const list = comboBuilderFilteredProducts();
  if(!COMBO_PRODUCTS.length){
    grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:var(--color-muted);">Cargando productos...</p>`;
  } else if(!list.length){
    grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:var(--color-muted);">No encontramos productos con ese nombre.</p>`;
  } else {
    grid.innerHTML = list.map(p => {
      const hasFlavors = p.colors && p.colors.length > 0;
      const qty = comboQtyFor(p.id);
      let actionHtml;
      if(p.stock <= 0){
        actionHtml = `<button class="add-btn" disabled style="opacity:.5;cursor:not-allowed;">Sin stock</button>`;
      } else if(hasFlavors){
        actionHtml = `<button class="add-btn" onclick="openProductDetail(${p.id}, true)">Elegir sabor/peso</button>`;
      } else if(qty > 0){
        actionHtml = `
          <div class="combo-qty-controls">
            <button type="button" onclick="changeComboQty(${p.id}, null, null, -1)">−</button>
            <span>${qty}</span>
            <button type="button" onclick="changeComboQty(${p.id}, null, null, 1)">+</button>
          </div>`;
      } else {
        actionHtml = `<button class="add-btn" onclick="addToComboDirect(${p.id})">Agregar al combo</button>`;
      }
      return `
      <div class="product-card">
        <div class="product-img-wrap">
          <img src="${p.img}" alt="${p.name}" loading="lazy">
        </div>
        <div class="product-info">
          <span class="cat-tag">${p.catName}</span>
          <h4>${p.name}</h4>
          <span class="price">${formatPrice(p.price)}</span>
          ${hasFlavors ? `<div class="color-dots">${p.colors.map(c => `<span class="color-dot" style="background:${c.hex}" title="${c.name}"></span>`).join("")}</div>` : ""}
          ${actionHtml}
        </div>
      </div>`;
    }).join("");
  }
  renderComboSummary();
}

function addComboBuilderItem(item){
  const existing = comboSelection.find(i =>
    i.id === item.id && (i.flavorId || null) === (item.flavorId || null) && (i.weightId || null) === (item.weightId || null)
  );
  if(existing){ existing.qty += 1; } else {
    comboSelection.push({ ...item, qty: 1 });
  }
  renderComboBuilder();
}

function addToComboDirect(id){
  const product = COMBO_PRODUCTS.find(p => p.id === id);
  if(!product) return;
  addComboBuilderItem({ id: product.id, name: product.name, price: product.price, img: product.img, flavorId: null, flavorName: null, weightId: null, weightName: null });
}

function changeComboQty(id, flavorId, weightId, delta){
  const idx = comboSelection.findIndex(i => i.id === id && (i.flavorId || null) === (flavorId || null) && (i.weightId || null) === (weightId || null));
  if(idx === -1) return;
  comboSelection[idx].qty += delta;
  if(comboSelection[idx].qty <= 0) comboSelection.splice(idx, 1);
  renderComboBuilder();
}

function removeComboItem(id, flavorId, weightId){
  const idx = comboSelection.findIndex(i => i.id === id && (i.flavorId || null) === (flavorId || null) && (i.weightId || null) === (weightId || null));
  if(idx === -1) return;
  comboSelection.splice(idx, 1);
  renderComboBuilder();
}

function comboSelectionCount(){ return comboSelection.reduce((s, i) => s + i.qty, 0); }
function comboSelectionTotal(){ return comboSelection.reduce((s, i) => s + i.price * i.qty, 0); }

function renderComboSummary(){
  const itemsBox = document.getElementById("comboSummaryItems");
  const hint = document.getElementById("comboSummaryHint");
  const totalEl = document.getElementById("comboSummaryTotal");
  const confirmBtn = document.getElementById("comboConfirmBtn");
  if(!itemsBox) return;

  if(!comboSelection.length){
    itemsBox.innerHTML = `<p class="combo-summary-empty">Todavía no elegiste ningún producto.</p>`;
  } else {
    itemsBox.innerHTML = comboSelection.map(i => {
      const variant = [i.flavorName, i.weightName ? `Peso ${i.weightName}` : null].filter(Boolean).join(" · ");
      return `
      <div class="combo-line">
        <img src="${i.img}" alt="${i.name}">
        <div class="combo-line-info">
          <h6>${i.name}</h6>
          <span>${variant ? variant + " · " : ""}${i.qty} × ${formatPrice(i.price)}</span>
        </div>
        <span class="combo-line-remove" onclick="removeComboItem(${i.id}, ${i.flavorId || "null"}, ${i.weightId || "null"})">Quitar</span>
      </div>`;
    }).join("");
  }

  const count = comboSelectionCount();
  if(count >= MIN_COMBO_ITEMS){
    hint.textContent = `Listo, elegiste ${count} productos.`;
    hint.classList.add("ready");
  } else {
    hint.textContent = `Elegiste ${count} de ${MIN_COMBO_ITEMS} productos mínimo.`;
    hint.classList.remove("ready");
  }
  totalEl.textContent = formatPrice(comboSelectionTotal());
  confirmBtn.disabled = count < MIN_COMBO_ITEMS;
}

function confirmComboToCart(){
  if(comboSelectionCount() < MIN_COMBO_ITEMS) return;
  comboSelection.forEach(item => {
    const existing = cart.find(i => i.id === item.id && (i.flavorId || null) === (item.flavorId || null) && (i.weightId || null) === (item.weightId || null));
    if(existing){ existing.qty += item.qty; } else {
      cart.push({ ...item });
    }
  });
  saveCart();
  const count = comboSelectionCount();
  comboSelection = [];
  renderComboBuilder();
  showToast(`¡Combo agregado al carrito! (${count} producto${count === 1 ? "" : "s"})`);
  closeComboBuilder();
  openCart();
}

/* POPUP DE BIENVENIDA: se muestra una sola vez por navegador (se acuerda
   con localStorage) ofreciendo un cupón de descuento a cambio de
   nombre/mail/cumpleaños. No tiene nada que ver con "Armá tu combo", que
   sigue funcionando igual que siempre. */
const WELCOME_POPUP_KEY = "bs_welcome_seen";

function initWelcomePopup(){
  if(localStorage.getItem(WELCOME_POPUP_KEY)) return;
  setTimeout(() => {
    const modal = document.getElementById("welcomeModal");
    if(modal) modal.classList.add("show");
  }, 1800);
}

function closeWelcomePopup(){
  const modal = document.getElementById("welcomeModal");
  if(modal) modal.classList.remove("show");
  localStorage.setItem(WELCOME_POPUP_KEY, "1");
}

async function submitWelcomeSignup(event){
  event.preventDefault();
  const name = document.getElementById("welcomeName").value.trim();
  const email = document.getElementById("welcomeEmail").value.trim();
  const birthday = document.getElementById("welcomeBirthday").value || null;
  const errorEl = document.getElementById("welcomeError");
  const submitBtn = document.getElementById("welcomeSubmitBtn");
  errorEl.style.display = "none";

  if(!name || !email){
    errorEl.textContent = "Completá nombre y mail para continuar.";
    errorEl.style.display = "block";
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Enviando...";
  try{
    const res = await fetch(`${API_BASE}/api/welcome-signup`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name, email, birthday}),
    });
    const data = await res.json();
    if(!res.ok || !data.ok){
      errorEl.textContent = data.error || "No se pudo guardar. Probá de nuevo.";
      errorEl.style.display = "block";
      submitBtn.disabled = false;
      submitBtn.textContent = "Quiero mi cupón";
      return;
    }
    document.getElementById("welcomeSuccessName").textContent = name.split(" ")[0];
    document.getElementById("welcomeCouponCode").textContent = data.code;
    document.getElementById("welcomeCouponHint").textContent = data.emailed
      ? `Tocá el código para copiarlo. También te lo mandamos por mail. Tenés ${data.percent_off}% off en tu primera compra.`
      : `Tocá el código para copiarlo. Tenés ${data.percent_off}% off en tu primera compra.`;
    document.getElementById("welcomeFormStep").style.display = "none";
    document.getElementById("welcomeSuccessStep").style.display = "block";
    localStorage.setItem(WELCOME_POPUP_KEY, "1");
  }catch(err){
    console.error(err);
    errorEl.textContent = "No se pudo conectar. Probá de nuevo.";
    errorEl.style.display = "block";
    submitBtn.disabled = false;
    submitBtn.textContent = "Quiero mi cupón";
  }
}

function copyWelcomeCoupon(){
  const code = document.getElementById("welcomeCouponCode").textContent.trim();
  if(!code) return;
  navigator.clipboard?.writeText(code).then(() => showToast("¡Código copiado!")).catch(() => {});
}

/* Esperamos a tener el % de recargo de 3 cuotas ANTES de pintar cualquier
   producto (catálogo, novedades, más vendidos, etc.), así los precios
   salen bien la primera vez y no "saltan" después de cargar la página. */
(async function initStore(){
  await loadPricingSettings();
  loadCategories().then(initCatalogFromUrl);
  renderCart();
  checkAuth();
  loadHeroSlides();
  loadSets();
  loadBrands();
  loadMegaMenu();
  loadShippingZones();
  loadNewestProducts();
  loadMostPurchased();
  loadGoalBanners();
  loadInstagramPosts();
  initWelcomePopup();
})();
document.querySelectorAll(".js-instagram-link").forEach(el => { el.href = INSTAGRAM_URL; });
// El @ que se muestra es el mismo INSTAGRAM_URL de arriba, sin repetirlo
// a mano en el HTML (así alcanza con cambiarlo en un solo lugar).
document.querySelectorAll(".js-instagram-handle").forEach(el => {
  const handle = INSTAGRAM_URL.replace(/\/+$/, "").split("/").pop();
  el.textContent = "@" + handle;
});

// WhatsApp: todos los links de la página (footer, botón flotante) se arman
// desde WHATSAPP_NUMBER en vez de tener el número pegado en el HTML, así
// alcanza con cambiarlo en un solo lugar.
document.querySelectorAll(".js-whatsapp-link").forEach(el => {
  const text = el.dataset.waText;
  el.href = `https://wa.me/${WHATSAPP_NUMBER}` + (text ? `?text=${encodeURIComponent(text)}` : "");
});

// Mismo criterio para los datos de contacto que Google lee del JSON-LD.
const ldJsonEl = document.getElementById("ldJsonStore");
if(ldJsonEl){
  try{
    const data = JSON.parse(ldJsonEl.textContent.replace("+__WHATSAPP_NUMBER__", `+${WHATSAPP_NUMBER}`).replace("__WHATSAPP_NUMBER__", WHATSAPP_NUMBER).replace("__INSTAGRAM_URL__", INSTAGRAM_URL));
    ldJsonEl.textContent = JSON.stringify(data);
  }catch(err){ console.error("No se pudo actualizar el JSON-LD", err); }
}

// Visor de imagen: click sobre la foto grande alterna el zoom, y Escape cierra el visor.
document.getElementById("lightboxImg").addEventListener("click", (e) => toggleImageZoom(e));
document.addEventListener("keydown", (e) => {
  if(e.key === "Escape" && document.getElementById("imageLightbox").classList.contains("show")){
    closeImageLightbox();
  }
});

/* static/js/navbar.js
   Complementa el hover de CSS en escritorio. No toca el comportamiento del celular:
   ahí sigue funcionando toggleMobileMegaMenu() de caro.js. */
(function () {
  var item = document.getElementById('productosMenuTrigger');
  var menu = document.getElementById('megaMenu');
  if (!item || !menu) return;
  var trigger = item.querySelector('.mobile-nav-mega-toggle');

  var isDesktop = function () { return window.matchMedia('(min-width:901px)').matches; };
  var noHover   = function () { return window.matchMedia('(hover:none)').matches; };

  function close() {
    item.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
  }

  // Teclado (Enter/Espacio) o pantalla táctil grande: abre/cierra con clic.
  // Con mouse no hace nada, porque el panel ya se abre solo con el hover.
  trigger.addEventListener('click', function (e) {
    if (!isDesktop()) return;
    item.classList.remove('suppress');
    if (noHover() || e.detail === 0) {   // e.detail === 0 => activado con teclado
      var open = item.classList.toggle('open');
      trigger.setAttribute('aria-expanded', open);
    }
  });

  // Al elegir una categoría, el panel se esconde (aunque el mouse siga encima)
  // hasta que el mouse salga de "Productos".
  menu.addEventListener('click', function (e) {
    if (!isDesktop() || !e.target.closest('a, button')) return;
    close();
    if (!noHover()) item.classList.add('suppress');
  });
  item.addEventListener('mouseleave', function () { item.classList.remove('suppress'); });

  item.addEventListener('focusout', function (e) {
    if (isDesktop() && !item.contains(e.relatedTarget)) close();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  document.addEventListener('click', function (e) {
    if (isDesktop() && !item.contains(e.target)) close();
  });
})();