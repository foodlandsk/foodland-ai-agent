(function () {
  const config = window.FoodlandAI || {};
  const apiBaseUrl = config.apiBaseUrl || "https://ai.foodland.sk";
  const demoMode = Boolean(config.demoMode);
  const maxQuestionsPerMinute = config.maxQuestionsPerMinute || 8;
  const recentQuestions = [];

  const demoProducts = [
    {
      title: "Suši ryža KIMPO 1 kg",
      effective_price: 3.33,
      currency: "EUR",
      availability: "in_stock",
      brand: "KIMPO",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/susi-ryza-kimpo-1-kg-3905.jpg?ft=1727720136&nwtrmrk=1",
      link: "https://www.foodland.sk/susi-ryza/susi-ryza-kimpo-1-kg/",
    },
    {
      title: "AKA MISO polievka prášok s tofu LOBO 30 g",
      effective_price: 2.97,
      currency: "EUR",
      availability: "in_stock",
      brand: "LOBO",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/aka-miso-polievka-prasok-s-tofu-lobo-30g-1466.jpg?ft=1680869315&nwtrmrk=1",
      link: "https://www.foodland.sk/instantne-polievky/aka-miso-polievka-prasok-s-tofu-lobo-30g/",
    },
  ];

  const style = document.createElement("style");
  style.textContent = `
    .fl-ai-root, .fl-ai-root * { box-sizing: border-box; letter-spacing: 0; }
    .fl-ai-root {
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: 999999;
      font-family: "Open Sans", Arial, sans-serif;
      color: #221F20;
    }
    .fl-ai-launcher {
      width: 62px;
      height: 62px;
      display: grid;
      place-items: center;
      border: 0;
      border-radius: 50%;
      background: #299B5E;
      color: #fff;
      cursor: pointer;
      box-shadow: 0 14px 34px rgba(41, 155, 94, 0.34);
      transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
    }
    .fl-ai-launcher:hover {
      transform: translateY(-2px);
      background: #238750;
      box-shadow: 0 18px 40px rgba(41, 155, 94, 0.42);
    }
    .fl-ai-launcher svg { width: 28px; height: 28px; display: block; }
    .fl-ai-panel {
      position: absolute;
      right: 0;
      bottom: 76px;
      width: min(410px, calc(100vw - 32px));
      height: min(640px, calc(100vh - 116px));
      display: none;
      flex-direction: column;
      overflow: hidden;
      border: 1px solid #d9e5dc;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 24px 60px rgba(20, 36, 28, 0.24);
    }
    .fl-ai-panel.is-open { display: flex; }
    .fl-ai-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 14px 14px 12px 16px;
      background: #299B5E;
      color: #fff;
    }
    .fl-ai-brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
    .fl-ai-mark {
      width: 34px;
      height: 34px;
      display: grid;
      flex: 0 0 auto;
      place-items: center;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.16);
      font-weight: 800;
      font-size: 15px;
    }
    .fl-ai-title { margin: 0; color: #fff; font-size: 15px; line-height: 1.2; font-weight: 800; }
    .fl-ai-status { margin-top: 2px; color: #E8F6EE; font-size: 12px; line-height: 1.2; }
    .fl-ai-close {
      width: 34px;
      height: 34px;
      display: grid;
      place-items: center;
      border: 0;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
      cursor: pointer;
    }
    .fl-ai-notice {
      padding: 9px 14px;
      border-bottom: 1px solid #e6eee8;
      background: #F2FAF5;
      color: #4D4D4D;
      font-size: 12px;
      line-height: 1.35;
    }
    .fl-ai-messages {
      flex: 1;
      overflow: auto;
      padding: 14px;
      background: #F8F8F8;
    }
    .fl-ai-message {
      max-width: 90%;
      margin: 0 0 10px;
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 14px;
      line-height: 1.45;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .fl-ai-message.user {
      margin-left: auto;
      background: #299B5E;
      color: white;
      border-bottom-right-radius: 3px;
    }
    .fl-ai-message.assistant {
      background: white;
      color: #221F20;
      border: 1px solid #e0e8e2;
      border-bottom-left-radius: 3px;
    }
    .fl-ai-message.error { border-color: #f0c7bc; background: #fff5f2; color: #7a2e1d; }
    .fl-ai-loading { display: inline-flex; align-items: center; gap: 6px; }
    .fl-ai-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #299B5E;
      animation: fl-ai-pulse 900ms ease-in-out infinite;
    }
    .fl-ai-dot:nth-child(2) { animation-delay: 120ms; }
    .fl-ai-dot:nth-child(3) { animation-delay: 240ms; }
    .fl-ai-products { display: grid; gap: 10px; margin: 0 0 12px; }
    .fl-ai-product {
      display: grid;
      grid-template-columns: 72px minmax(0, 1fr);
      gap: 10px;
      padding: 10px;
      border: 1px solid #dde7df;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 20px rgba(29, 48, 38, 0.06);
    }
    .fl-ai-product img {
      width: 72px;
      height: 72px;
      object-fit: contain;
      border-radius: 6px;
      border: 1px solid #edf1ee;
      background: #f1f5f2;
    }
    .fl-ai-product-image-fallback {
      width: 72px;
      height: 72px;
      display: none;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      border: 1px solid #edf1ee;
      background: #f1f5f2;
      color: #299B5E;
      font-size: 11px;
      font-weight: 800;
      text-align: center;
      line-height: 1.15;
      padding: 8px;
    }
    .fl-ai-product-title {
      margin: 0;
      color: #221F20;
      font-size: 13px;
      line-height: 1.25;
      font-weight: 800;
    }
    .fl-ai-product-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 7px 0;
      color: #5d6d63;
      font-size: 12px;
      line-height: 1.25;
    }
    .fl-ai-price { color: #299B5E; font-weight: 800; }
    .fl-ai-product-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 32px;
      padding: 7px 10px;
      border-radius: 6px;
      background: #299B5E;
      color: #fff;
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }
    .fl-ai-show-more {
      min-height: 38px;
      border: 1px solid #299B5E;
      border-radius: 6px;
      background: #fff;
      color: #238750;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
    }
    .fl-ai-show-more:hover {
      background: #F2FAF5;
    }
    .fl-ai-form {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid #e0e8e2;
      background: white;
    }
    .fl-ai-input {
      width: 100%;
      min-width: 0;
      border: 1px solid #cbd9cf;
      border-radius: 6px;
      padding: 11px 12px;
      color: #221F20;
      font-size: 14px;
      line-height: 1.3;
      outline: none;
    }
    .fl-ai-input:focus {
      border-color: #299B5E;
      box-shadow: 0 0 0 3px rgba(41, 155, 94, 0.13);
    }
    .fl-ai-submit {
      min-width: 82px;
      border: 0;
      border-radius: 6px;
      padding: 0 14px;
      background: #299B5E;
      color: white;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
    }
    .fl-ai-submit:disabled { cursor: not-allowed; opacity: 0.55; }
    @keyframes fl-ai-pulse {
      0%, 100% { opacity: 0.35; transform: translateY(0); }
      50% { opacity: 1; transform: translateY(-2px); }
    }
    @media (max-width: 520px) {
      .fl-ai-root { right: 12px; bottom: 12px; }
      .fl-ai-panel {
        position: fixed;
        inset: auto 10px 84px 10px;
        width: auto;
        height: min(650px, calc(100vh - 104px));
      }
      .fl-ai-launcher { width: 58px; height: 58px; }
      .fl-ai-form { grid-template-columns: 1fr; }
      .fl-ai-submit { min-height: 40px; }
    }
    @media (prefers-reduced-motion: reduce) {
      .fl-ai-launcher, .fl-ai-dot { transition: none; animation: none; }
    }
  `;
  document.head.appendChild(style);

  const root = document.createElement("div");
  root.className = "fl-ai-root";
  root.innerHTML = `
    <section class="fl-ai-panel" aria-label="Foodland poradca">
      <header class="fl-ai-header">
        <div class="fl-ai-brand">
          <div class="fl-ai-mark">FL</div>
          <div>
            <p class="fl-ai-title">Foodland poradca</p>
            <div class="fl-ai-status">Produkty, ceny a odporúčania</div>
          </div>
        </div>
        <button class="fl-ai-close" type="button" aria-label="Minimalizovať chat">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M6 12h12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </button>
      </header>
      <div class="fl-ai-notice">Pri alergiách, zložení a dostupnosti si prosím overte detail produktu.</div>
      <div class="fl-ai-messages" aria-live="polite"></div>
      <form class="fl-ai-form">
        <input class="fl-ai-input" type="text" placeholder="Napíšte, čo hľadáte..." autocomplete="off" />
        <button class="fl-ai-submit" type="submit">Poslať</button>
      </form>
    </section>
    <button class="fl-ai-launcher" type="button" aria-label="Otvoriť Foodland poradcu">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 6.8A4.8 4.8 0 0 1 9.8 2h4.4A4.8 4.8 0 0 1 19 6.8v4.8a4.8 4.8 0 0 1-4.8 4.8h-2.8L7 20v-3.8a4.8 4.8 0 0 1-2-3.9V6.8Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/>
        <path d="M8.5 8.5h7M8.5 12h4.8" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>
      </svg>
    </button>
  `;
  document.body.appendChild(root);

  const panel = root.querySelector(".fl-ai-panel");
  const launcher = root.querySelector(".fl-ai-launcher");
  const closeButton = root.querySelector(".fl-ai-close");
  const messages = root.querySelector(".fl-ai-messages");
  const form = root.querySelector(".fl-ai-form");
  const input = root.querySelector(".fl-ai-input");
  const submit = root.querySelector(".fl-ai-submit");

  function openPanel() {
    panel.classList.add("is-open");
    if (messages.children.length === 0) {
      addMessage("assistant", "Dobrý deň, s čím vám pomôžem? Môžete sa pýtať na produkty, ceny alebo odporúčania.");
    }
    window.setTimeout(function () { input.focus(); }, 50);
  }

  function closePanel() {
    panel.classList.remove("is-open");
  }

  function addMessage(role, text, variant) {
    const message = document.createElement("div");
    message.className = `fl-ai-message ${role}${variant ? ` ${variant}` : ""}`;
    message.textContent = text;
    messages.appendChild(message);
    scrollToBottom();
    return message;
  }

  function addLoadingMessage() {
    const message = document.createElement("div");
    message.className = "fl-ai-message assistant";
    message.innerHTML = `<span class="fl-ai-loading">Hľadám vo Foodland produktoch <span class="fl-ai-dot"></span><span class="fl-ai-dot"></span><span class="fl-ai-dot"></span></span>`;
    messages.appendChild(message);
    scrollToBottom();
    return message;
  }

  function addProducts(products) {
    if (!Array.isArray(products) || products.length === 0) return;

    const wrap = document.createElement("div");
    wrap.className = "fl-ai-products";
    const initialCount = 4;
    const renderProduct = function (product) {
      const price = typeof product.effective_price === "number"
        ? `${product.effective_price.toFixed(2)} ${product.currency || "EUR"}`
        : "Cena neuvedená";
      const availability = product.availability === "in_stock" ? "Skladom" : "Overiť dostupnosť";
      const card = document.createElement("article");
      card.className = "fl-ai-product";
      card.innerHTML = `
        <div>
          <img src="${escapeAttr(product.image_link || "")}" alt="${escapeAttr(product.title || "Produkt Foodland")}" loading="lazy" />
          <div class="fl-ai-product-image-fallback">Foodland produkt</div>
        </div>
        <div>
          <h3 class="fl-ai-product-title">${escapeHtml(product.title || "Produkt Foodland")}</h3>
          <div class="fl-ai-product-meta">
            <span class="fl-ai-price">${escapeHtml(price)}</span>
            <span>${escapeHtml(availability)}</span>
            ${product.brand ? `<span>${escapeHtml(product.brand)}</span>` : ""}
          </div>
          <a class="fl-ai-product-link" href="${escapeAttr(product.link || "#")}" target="_blank" rel="noopener">Zobraziť produkt</a>
        </div>
      `;
      const image = card.querySelector("img");
      const fallback = card.querySelector(".fl-ai-product-image-fallback");
      image.addEventListener("error", function () {
        image.style.display = "none";
        fallback.style.display = "flex";
      });
      wrap.appendChild(card);
    };

    products.slice(0, initialCount).forEach(renderProduct);

    if (products.length > initialCount) {
      const button = document.createElement("button");
      button.className = "fl-ai-show-more";
      button.type = "button";
      button.textContent = `Zobraziť ďalšie (${products.length - initialCount})`;
      button.addEventListener("click", function () {
        products.slice(initialCount).forEach(renderProduct);
        button.remove();
        scrollToBottom();
      });
      wrap.appendChild(button);
    }

    messages.appendChild(wrap);
    scrollToBottom();
  }

  function scrollToBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function canAskNow() {
    const now = Date.now();
    const windowStart = now - 60000;
    while (recentQuestions.length && recentQuestions[0] < windowStart) {
      recentQuestions.shift();
    }
    if (recentQuestions.length >= maxQuestionsPerMinute) return false;
    recentQuestions.push(now);
    return true;
  }

  async function askBackend(text) {
    if (demoMode) {
      await new Promise(function (resolve) { window.setTimeout(resolve, 600); });
      return {
        answer: "Našiel som niekoľko vhodných produktov. Pozrite si odporúčania nižšie.",
        products: demoProducts,
      };
    }

    const response = await fetch(`${apiBaseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, limit: 6 }),
    });
    if (response.status === 429) throw new Error("RATE_LIMIT");
    if (!response.ok) throw new Error("REQUEST_FAILED");
    return response.json();
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
  }

  launcher.addEventListener("click", function () {
    if (panel.classList.contains("is-open")) closePanel();
    else openPanel();
  });
  closeButton.addEventListener("click", closePanel);

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    if (!canAskNow()) {
      addMessage("assistant", "Poslali ste veľa otázok za krátky čas. Skúste prosím o chvíľu.", "error");
      return;
    }

    input.value = "";
    submit.disabled = true;
    addMessage("user", text);
    const loading = addLoadingMessage();

    try {
      const data = await askBackend(text);
      loading.textContent = data.answer || "Nenašiel som presnú odpoveď. Skúste napísať názov produktu alebo kategóriu inak.";
      addProducts(data.products);
    } catch (error) {
      loading.classList.add("error");
      loading.textContent = error.message === "RATE_LIMIT"
        ? "Poslali ste veľa otázok za krátky čas. Skúste to prosím o chvíľu."
        : "Momentálne sa nepodarilo odoslať otázku. Skúste to prosím neskôr.";
    } finally {
      submit.disabled = false;
      input.focus();
    }
  });
})();
