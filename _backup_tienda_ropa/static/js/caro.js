/* =========================================================
   CONFIGURACIÓN RÁPIDA — Editá esto para personalizar
   ========================================================= */
const WHATSAPP_NUMBER = "5493865830702"; // tu número para pruebas: 54 (Argentina) + 9 (celular) + 3865830702
const INSTAGRAM_URL = "https://instagram.com/vua.showroom"; // cambiá esto por el link real de tu Instagram
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

/* Chips de subcategoría (Remeras, Pantalones, Botas, etc.): se cargan
   desde /api/subcategories según la categoría elegida — cada categoría
   (indumentaria/calzado/accesorios) tiene las suyas, administradas desde
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

/* Si venimos de un botón del carrusel (ej: /?tag=ofertas#catalogo), aplica
   el filtro correspondiente y baja directo al catálogo. */
function initCatalogFromUrl(){
  const params = new URLSearchParams(window.location.search);
  const tag = params.get("tag");
  const validCats = ["indumentaria", "calzado", "accesorios"];
  const cat = validCats.includes(tag) ? tag : "todos";

  if(tag === "ofertas"){
    showOffersOnly = true;
    document.getElementById("offersBanner").style.display = "block";
  }
  if(cat !== "todos"){
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.toggle("active", b.dataset.cat === cat));
    currentFilter = cat;
  }
  loadSubfilters(cat);

  loadProducts(cat, "").then(() => {
    if(tag){
      setTimeout(() => document.getElementById("catalogo").scrollIntoView({behavior:"smooth"}), 200);
    }
  });
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
  slider.innerHTML = heroSlides.map((s, i) => {
    // Si el slide no tiene título ni bajada (una foto/imagen de marca
    // "limpia", sin texto encima), no le ponemos el velo oscuro: ese
    // oscurecido es solo para que el texto blanco se lea sobre la foto.
    const hasText = !!(s.title || s.subtitle);
    return `
    <div class="hero-slide ${i === 0 ? "active" : ""} ${hasText ? "has-text" : ""}" style="background-image:url('${s.image_url}')">
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
    PRODUCTS = data.map(p => {
      const hasDiscount = p.discount_percent !== null && p.discount_percent !== undefined;
      const finalPrice = hasDiscount ? Math.round(p.price * (1 - p.discount_percent / 100)) : p.price;
      // Para el hover "ver de atrás" en la vidriera: primero probamos con
      // las fotos extra generales del producto (si las tiene); si no,
      // usamos la segunda foto del primer color (la primera ya se usa
      // como foto principal de la tarjeta) — así alcanza con cargar las
      // fotos por color, sin tener que subirlas también aparte.
      const firstColorImages = (p.colors && p.colors[0] && p.colors[0].images) || [];
      const hoverImg = (p.images && p.images.length) ? p.images[0] : (firstColorImages.length > 1 ? firstColorImages[1] : null);
      return {
        id: p.id, name: p.name, cat: p.category,
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
    });
    renderProducts();
  }catch(err){
    console.error(err);
    grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:#b34747;">
      No se pudo conectar con el servidor. Revisá que app.py esté corriendo (ver README.md).</p>`;
  }
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
  grid.innerHTML = list.map(p => {
    const hasColors = p.colors && p.colors.length > 0;
    const lowStock = p.showLowStockBadge && p.stock > 0 && p.stock <= LOW_STOCK_THRESHOLD;
    const isFav = favorites.has(p.id);
    const addBtn = hasColors
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
        <span class="cat-tag">${p.cat}</span>
        <h4 style="cursor:pointer;" onclick="openProductDetail(${p.id})">${p.name}</h4>
        ${p.ratingCount > 0 ? `<div class="rating-badge">${starsHtml(p.ratingAvg)} <span>(${p.ratingCount})</span></div>` : ""}
        ${p.originalPrice
          ? `<span class="price-row"><span class="price-old">${formatPrice(p.originalPrice)}</span><span class="price">${formatPrice(p.price)}</span></span>`
          : `<span class="price">${formatPrice(p.price)}</span>`}
        ${hasColors ? `<div class="color-dots">${p.colors.map(c => `<span class="color-dot" style="background:${c.hex}" title="${c.name}"></span>`).join("")}</div>` : ""}
        ${lowStock ? `<span class="low-stock">¡Últimas unidades!</span>` : ""}
        ${addBtn}
      </div>
    </div>
  `;
  }).join("");
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
  const existing = cart.find(i => i.id === id && !i.colorId);
  if(existing){ existing.qty += 1; } else {
    cart.push({ id: product.id, name: product.name, price: product.price, img: product.img, colorId: null, colorName: null, sizeId: null, sizeName: null, qty: 1 });
  }
  saveCart();
  showToast(`${product.name} agregado al carrito`);
}

function cartLineIndex(id, colorId, sizeId){
  return cart.findIndex(i => i.id === id && (i.colorId || null) === (colorId || null) && (i.sizeId || null) === (sizeId || null));
}

function changeQty(id, colorId, sizeId, delta){
  const idx = cartLineIndex(id, colorId, sizeId);
  if(idx === -1) return;
  cart[idx].qty += delta;
  if(cart[idx].qty <= 0){ cart.splice(idx, 1); }
  saveCart();
}

function removeItem(id, colorId, sizeId){
  const idx = cartLineIndex(id, colorId, sizeId);
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
      const variant = [i.colorName, i.sizeName ? `Talle ${i.sizeName}` : null].filter(Boolean).join(" · ");
      return `
      <div class="cart-item">
        <img src="${i.img}" alt="${i.name}">
        <div class="cart-item-info">
          <h5>${i.name}${variant ? ` <span style="font-weight:400;color:var(--color-muted);">· ${variant}</span>` : ""}</h5>
          <span class="price">${formatPrice(i.price)} c/u</span>
          <div class="qty-controls">
            <button onclick="changeQty(${i.id},${i.colorId || "null"},${i.sizeId || "null"},-1)">−</button>
            <span>${i.qty}</span>
            <button onclick="changeQty(${i.id},${i.colorId || "null"},${i.sizeId || "null"},1)">+</button>
          </div>
          <span class="remove-item" onclick="removeItem(${i.id},${i.colorId || "null"},${i.sizeId || "null"})">Quitar</span>
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
function closeAll(){ closeCart(); closeCheckout(); closeProductDetail(); }

let currentDetail = null;
let selectedColorId = null;
let selectedSizeId = null;

async function openProductDetail(id){
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
      id: data.id, name: data.name, cat: data.category, description: data.description,
      price: finalPrice, originalPrice: hasDiscount ? data.price : null,
      image: data.image_url || "https://placehold.co/400x500/eee/634b3d?text=Sin+foto",
      images: data.images || [], // fotos extra del producto (frente/espalda/detalle), sin color
      stock: data.stock,
      colors: data.colors || [],
      sizes: data.sizes || [],
      reviews: data.reviews || [], ratingAvg: data.rating_avg, ratingCount: data.rating_count || 0
    };
    selectedColorId = currentDetail.colors.length ? currentDetail.colors[0].id : null;
    const initialSizes = currentSizeOptions();
    selectedSizeId = initialSizes.length ? initialSizes[0].id : null;
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
    const color = currentDetail.colors.find(c => c.id === selectedColorId) || currentDetail.colors[0];
    if(color.images && color.images.length) mainImages = color.images;
  }
  // A esas siempre les sumamos la galería general del producto (frente/
  // espalda/detalle) si existe — son fotos que valen para cualquier color,
  // así que no se pueden perder solo porque el color tenga foto propia.
  const extra = (currentDetail.images || []).filter(img => !mainImages.includes(img));
  return extra.length ? [...mainImages, ...extra] : mainImages;
}

/* Si el color elegido tiene sus propios talles cargados (stock por
   combinación color+talle, ej: 2 de Rosa viejo en L y 1 de Beige en L,
   cada uno separado), esos son los que hay que mostrar/usar — si no,
   caemos a los talles generales del producto (como antes). */
function currentSizeOptions(){
  const color = currentDetail.colors.find(c => c.id === selectedColorId);
  if(color && color.sizes && color.sizes.length) return color.sizes;
  return currentDetail.sizes;
}

function currentStock(){
  const color = currentDetail.colors.find(c => c.id === selectedColorId);
  if(color && color.sizes && color.sizes.length){
    const size = color.sizes.find(s => s.id === selectedSizeId);
    return size ? size.stock : 0;
  }
  let stock = color ? color.stock : currentDetail.stock;
  if(currentDetail.sizes.length){
    const size = currentDetail.sizes.find(s => s.id === selectedSizeId);
    const sizeStock = size ? size.stock : 0;
    stock = color ? Math.min(stock, sizeStock) : sizeStock;
  }
  return stock;
}

function selectColor(colorId){
  selectedColorId = colorId;
  const sizeOptions = currentSizeOptions();
  selectedSizeId = sizeOptions.length ? sizeOptions[0].id : null;
  renderProductDetail();
}

function selectSize(sizeId){
  selectedSizeId = sizeId;
  renderProductDetail();
}

function relatedProducts(){
  return PRODUCTS.filter(p => p.cat === currentDetail.cat && p.id !== currentDetail.id).slice(0, 4);
}

/* Stock total de un color para pintarlo "sin stock": si tiene talles
   propios, es la suma de esos talles (el .stock plano del color ya no
   se actualiza en ese modo); si no, es el .stock de siempre. */
function colorTotalStock(color){
  if(color.sizes && color.sizes.length) return color.sizes.reduce((s, sz) => s + sz.stock, 0);
  return color.stock;
}

function renderProductDetail(){
  const body = document.getElementById("productDetailBody");
  const images = currentGalleryImages();
  const stock = currentStock();
  const selectedColor = currentDetail.colors.find(c => c.id === selectedColorId);
  const sizeOptions = currentSizeOptions();
  const selectedSize = sizeOptions.find(s => s.id === selectedSizeId);
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
          <span class="cat-tag">${currentDetail.cat}</span>
          <button type="button" class="share-btn" onclick="shareProduct()" title="Compartir" aria-label="Compartir producto">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 10.5 15.4 6.5M8.6 13.5l6.8 4"/></svg>
          </button>
        </div>
        <h2>${currentDetail.name}</h2>
        ${currentDetail.originalPrice
          ? `<span class="price-row"><span class="price-old">${formatPrice(currentDetail.originalPrice)}</span><span class="price">${formatPrice(currentDetail.price)}</span></span>`
          : `<span class="price">${formatPrice(currentDetail.price)}</span>`}
        ${currentDetail.description ? `<p class="desc">${currentDetail.description}</p>` : ""}
        ${currentDetail.show_low_stock_badge && stock > 0 && stock <= LOW_STOCK_THRESHOLD ? `<span class="low-stock" style="margin-bottom:14px;">¡Últimas unidades!</span>` : ""}
        ${currentDetail.colors.length ? `
          <div class="color-picker">
            <h5>Color${selectedColor ? `: ${selectedColor.name}` : ""}</h5>
            <div class="color-options">
              ${currentDetail.colors.map(c => `
                <span class="color-swatch ${c.id === selectedColorId ? "selected" : ""} ${colorTotalStock(c) <= 0 ? "out-of-stock" : ""}"
                      style="background:${c.hex};" title="${c.name}${colorTotalStock(c) <= 0 ? " (sin stock)" : ""}"
                      onclick="selectColor(${c.id})"></span>
              `).join("")}
            </div>
          </div>
        ` : ""}
        ${sizeOptions.length ? `
          <div class="size-picker">
            <h5>Talle${selectedSize ? `: ${selectedSize.name}` : ""}</h5>
            <div class="size-options">
              ${sizeOptions.map(s => `
                <span class="size-pill ${s.id === selectedSizeId ? "selected" : ""} ${s.stock <= 0 ? "out-of-stock" : ""}"
                      title="${s.stock <= 0 ? "Sin stock" : ""}"
                      onclick="selectSize(${s.id})">${s.name}</span>
              `).join("")}
            </div>
          </div>
        ` : ""}
        ${stock > 0
          ? `<button class="btn btn-primary" onclick="addToCartFromDetail()">Agregar al carrito</button>`
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

/* "Avisame cuando haya stock": si la combinación elegida (color/talle, o
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
  const selectedColor = currentDetail.colors.find(c => c.id === selectedColorId);
  const selectedSize = currentSizeOptions().find(s => s.id === selectedSizeId);
  try{
    const res = await fetch(`${API_BASE}/api/stock-notify`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        email, product_id: currentDetail.id,
        color_id: selectedColor ? selectedColor.id : null,
        size_id: selectedSize ? selectedSize.id : null,
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
  const text = `¡Mirá "${currentDetail.name}" en Vua Showroom! ${formatPrice(currentDetail.price)}`;
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
   fotos del detalle de producto como para la foto de tapa de un conjunto. */
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
  const selectedColor = currentDetail.colors.find(c => c.id === selectedColorId);
  const selectedSize = currentSizeOptions().find(s => s.id === selectedSizeId);
  const cartId = currentDetail.id;
  const colorId = selectedColor ? selectedColor.id : null;
  const colorName = selectedColor ? selectedColor.name : null;
  const sizeId = selectedSize ? selectedSize.id : null;
  const sizeName = selectedSize ? selectedSize.name : null;
  const img = currentGalleryImages()[0];

  const existing = cart.find(i => i.id === cartId && (i.colorId || null) === colorId && (i.sizeId || null) === sizeId);
  if(existing){ existing.qty += 1; } else {
    cart.push({
      id: cartId, name: currentDetail.name, price: currentDetail.price, img,
      colorId, colorName, sizeId, sizeName, qty: 1
    });
  }
  saveCart();
  const variant = [colorName, sizeName ? `Talle ${sizeName}` : null].filter(Boolean).join(" · ");
  showToast(`${currentDetail.name}${variant ? " · " + variant : ""} agregado al carrito`);
  closeProductDetail();
  // Si este producto se abrió porque faltaba elegir color/talle dentro de
  // un conjunto, seguimos con el próximo producto pendiente del conjunto.
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
    const variant = [i.colorName, i.sizeName ? `Talle ${i.sizeName}` : null].filter(Boolean).join(" · ");
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

/* Los medios de pago que se ven acá los prende/apaga tu prima desde
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

/* Mapea nombres de tarjetas (lo que tu prima escribe en /admin/pagos) a un
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
          color_id: i.colorId || null, color_name: i.colorName || null,
          size_id: i.sizeId || null, size_name: i.sizeName || null,
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
          color_id: i.colorId || null, color_name: i.colorName || null,
          size_id: i.sizeId || null, size_name: i.sizeName || null
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

  let msg = `¡Hola Vua Showroom! Quiero hacer un pedido:%0A%0A`;
  cart.forEach(i => {
    const variant = [i.colorName, i.sizeName ? `Talle ${i.sizeName}` : null].filter(Boolean).join(", ");
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
  m.style.display = m.style.display === "flex" ? "none" : "flex";
}

/* CONJUNTOS: looks armados por tu prima desde /admin/conjuntos con
   productos que ya existen en el catálogo. Cada producto mantiene su
   propio precio y stock — el conjunto es solo una forma de mostrarlos
   juntos y agregarlos todos al carrito de una sola vez. */
let SETS_BY_ID = {};

async function loadSets(){
  try{
    const res = await fetch(`${API_BASE}/api/sets`);
    if(!res.ok) return;
    const sets = await res.json();
    renderSets(sets);
  }catch(err){
    console.error("No se pudieron cargar los conjuntos", err);
  }
}

/* Precio "de catálogo" de cada producto del conjunto, ya con su propio
   % de descuento (si tiene) aplicado — es la base sobre la que se
   prorratea el precio especial del conjunto, si la dueña cargó uno. */
function setItemBasePrice(it){
  const hasDiscount = it.discount_percent !== null && it.discount_percent !== undefined;
  return hasDiscount ? Math.round(it.price * (1 - it.discount_percent / 100)) : it.price;
}

/* Si el conjunto tiene un precio especial (menor a la suma normal de sus
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
  const section = document.getElementById("conjuntos");
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
        <img class="set-cover" src="${coverImage}" alt="${s.name}" onclick="openImageLightbox('${coverImage}', '${s.name.replace(/'/g, "\\'")}')">
        <div class="set-info">
          <h3>${s.name}</h3>
          ${s.description ? `<p class="set-desc">${s.description}</p>` : ""}
          <div class="set-items">${itemsHtml}</div>
          ${totalHtml}
          <button class="btn btn-primary" onclick="addSetToCart(${s.id})">Agregar conjunto al carrito</button>
        </div>
      </div>
    `;
  }).join("");
}

/* Arma directamente el item de carrito con los datos que ya trae
   /api/sets (no depende de que el producto esté en el PRODUCTS del
   catálogo actual, que puede estar filtrado por categoría). `price` ya
   viene calculado (normal o prorrateado si el conjunto tiene precio
   especial) — no se recalcula acá para no aplicar el descuento 2 veces. */
function addSetItemToCart(item, price){
  const existing = cart.find(i => i.id === item.id && !i.colorId && !i.sizeId);
  if(existing){
    existing.qty += 1;
  } else {
    cart.push({
      id: item.id, name: item.name, price, img: item.image_url,
      colorId: null, colorName: null, sizeId: null, sizeName: null, qty: 1,
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
    // En vez de solo avisar que hace falta elegir color/talle, abrimos
    // directo la ficha del primer producto que lo necesita — igual que
    // si el cliente hubiera tocado ese producto desde el catálogo.
    if(added > 0){
      showToast(`Se agregaron ${added} producto${added === 1 ? "" : "s"} del conjunto. Elegí color/talle para el resto.`);
    }
    if(needsVariant.length > 1){
      pendingSetVariantQueue = needsVariant.slice(1);
    }
    openSetVariantItem(needsVariant[0]);
  } else {
    showToast("¡Conjunto agregado al carrito!");
  }
}

/* Si un conjunto tiene más de un producto con color/talle, después de
   elegir el primero seguimos ofreciendo el siguiente automáticamente en
   vez de dejar que el cliente tenga que ir a buscarlo a mano. Cada
   entrada de la cola es {item, price} — el precio ya viene prorrateado
   si el conjunto tiene un precio especial cargado. */
let pendingSetVariantQueue = [];

async function openSetVariantItem(entry){
  await openProductDetail(entry.item.id);
  // Si el conjunto tiene precio especial, el precio de este producto en
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
  showToast(`Ahora elegí color/talle para "${next.item.name}"`);
  openSetVariantItem(next);
}

initCatalogFromUrl();
renderCart();
checkAuth();
loadHeroSlides();
loadSets();
loadShippingZones();
document.querySelectorAll(".js-instagram-link").forEach(el => { el.href = INSTAGRAM_URL; });

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
