(function () {
  const config = window.FoodlandAI || {};
  const apiBaseUrl = config.apiBaseUrl || "https://ai.foodland.sk";
  const isDemoPage = window.location.protocol === "file:" || /\/static\/widget\.html$/.test(window.location.pathname);
  const demoMode = Boolean(config.demoMode && config.allowDemoMode && isDemoPage);
  const maxQuestionsPerMinute = config.maxQuestionsPerMinute || 8;
  const recentQuestions = [];
  let lastProductSubject = "";
  let lastRecipeSubject = "";

  const demoProducts = [
    {
      title: "Kimchi krajané JONGGA 1000 g",
      effective_price: 11.90,
      currency: "EUR",
      availability: "in_stock",
      brand: "JONGGA",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/kimchi-krajane-jongga-1000-g-3315.jpg?ft=1700865338&nwtrmrk=1",
      link: "https://www.foodland.sk/konzervovana-zelenina/kimchi-krajane-jongga-1000-g/",
    },
    {
      title: "Kimchi Nakladaná kapusta MAT KIMCHI JONGGA 300g",
      effective_price: 4.52,
      currency: "EUR",
      availability: "in_stock",
      brand: "JONGGA",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/nakladana-kapusta-mat-kimchi-jongga-300g-921.jpg?ft=1720100911&nwtrmrk=1",
      link: "https://www.foodland.sk/hotove-jedla/nakladana-kapusta-mat-kimchi-jongga-300g/",
    },
  ];

  const srirachaDemoProducts = [
    {
      title: "Čili omáčka Sriracha COCK BRAND 490g/ 440ml",
      effective_price: 4.76,
      currency: "EUR",
      availability: "in_stock",
      brand: "COCK BRAND",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/cock-brand-sriracha-cili-omacka-490g-1315.jpg?ft=1588069091&nwtrmrk=1",
      link: "https://www.foodland.sk/sriracha-cili-omacky/cili-omacka-sriracha-cock-brand-490g/",
    },
    {
      title: "Spicy Sriracha Mayo čili omáčka FLYING GOOSE 200ml",
      effective_price: 3.33,
      currency: "EUR",
      availability: "in_stock",
      brand: "FLYING GOOSE",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/spicy-sriracha-mayo-cili-omacka-flying-goose-200-ml-1457.jpg?ft=1680643653&nwtrmrk=1",
      link: "https://www.foodland.sk/sriracha-cili-omacky/spicy-sriracha-mayo-cili-omacka-flying-goose-200-ml/",
    },
  ];

  const soySauceDemoProducts = [
    {
      title: "Bezlepková sójová omáčka MEGACHEF 200 ml",
      effective_price: 3.45,
      currency: "EUR",
      availability: "in_stock",
      brand: "MEGACHEF",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/bezlepkova-sojova-omacka-megachef-200-ml-591.jpg?ft=1680262409&nwtrmrk=1",
      link: "https://www.foodland.sk/sojove-omacky/bezlepkova-sojova-omacka-megachef-200-ml/",
    },
    {
      title: "Double Deluxe sójová omáčka LEE KUM KEE 500ml",
      effective_price: 3.93,
      currency: "EUR",
      availability: "in_stock",
      brand: "LEE KUM KEE",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/lee-kum-kee-double-deluxe-sojova-omacka-500-ml-1190.jpg?ft=1680861172&nwtrmrk=1",
      link: "https://www.foodland.sk/sojove-omacky/double-deluxe-sojova-omacka-lee-kum-kee-500-ml/",
    },
  ];

  const demoRecipeCatalog = {
    kimchi: [
      {
        title: "Tradičný Kimchi recept",
        cuisine: "Kórejská",
        note: "",
        link: "https://www.foodland.sk/recepty/tradicny-kimchi-recept/",
      },
      {
        title: "Kimchi Ramen",
        cuisine: "Kórejská",
        note: "",
        link: "https://www.foodland.sk/recepty/kimchi-ramen/",
      },
    ],
    ramen: [
      {
        title: "Shoyu Ramen",
        cuisine: "Japonská",
        note: "",
        link: "https://www.foodland.sk/recepty/shoyu-ramen-tajomstvo-najoblubenejsej-japonskej-polievky/",
      },
      {
        title: "Kimchi Ramen",
        cuisine: "Kórejská",
        note: "",
        link: "https://www.foodland.sk/recepty/kimchi-ramen/",
      },
    ],
    pho: [
      {
        title: "Vietnamská hovädzia polievka PHỞ BÒ",
        cuisine: "Vietnamská",
        note: "",
        link: "https://www.foodland.sk/recepty/ako-sa-vari-vietnamska-hovadzia-polievka-pho-bo/",
      },
      {
        title: "Vietnamská kuracia polievka PHỞ GÀ",
        cuisine: "Vietnamská",
        note: "",
        link: "https://www.foodland.sk/recepty/pho-ga/",
      },
    ],
    pad_thai: [
      {
        title: "Vegánske Pad Thai",
        cuisine: "Thajská",
        note: "",
        link: "https://www.foodland.sk/recepty/veganske-pad-thai/",
      },
      {
        title: "Kuracie Pad Thai",
        cuisine: "Thajská",
        note: "",
        link: "https://www.foodland.sk/recepty/kuracie-pad-thai/",
      },
    ],
  };

  const kimchiIngredientDemoProducts = [
    {
      title: "Čili pasta Gochujang Ofood DAESANG 500g",
      effective_price: 4.76,
      currency: "EUR",
      availability: "in_stock",
      brand: "DAESANG",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/daesang-cili-pasta-gochujang-500g-1273.jpg?ft=1680816568&nwtrmrk=1",
      link: "https://www.foodland.sk/pasty-korenia/daesang-cili-pasta-gochujang-500g/",
    },
    {
      title: "Červená čili paprika pálivá mletá LIM GA NE 1000g",
      effective_price: 11.90,
      currency: "EUR",
      availability: "in_stock",
      brand: "LIM GA NE",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/cervena-cili-paprika-paliva-mleta-lim-ga-ne-500g-1724.jpg?ft=1644346302&nwtrmrk=1",
      link: "https://www.foodland.sk/horeca-hotel-restauracia-catering/cervena-cili-paprika-paliva-mleta-lim-ga-ne-1000g/",
    },
    {
      title: "Rybacia omáčka 40N THUAN PHAT 620ml",
      effective_price: 5.35,
      currency: "EUR",
      availability: "in_stock",
      brand: "THUAN PHAT",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/rybacia-omacka-40n-thuan-phat-620ml-1251.jpg?ft=1679693791&nwtrmrk=1",
      link: "https://www.foodland.sk/rybacie-omacky/rybacia-omacka-40n-thuan-phat-620ml/",
    },
    {
      title: "Ryžová múka COCK BRAND 400 g",
      effective_price: 1.58,
      currency: "EUR",
      availability: "in_stock",
      brand: "COCK BRAND",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/ryzova-muka-cock-brand-400-g-204.jpg?ft=1683916910&nwtrmrk=1",
      link: "https://www.foodland.sk/muka-skrob-a-ryzovy-papier/ryzova-muka-cock-brand-400-g/",
    },
    {
      title: "Čistý čierny sezamový olej 100% LEE KUM KEE 207 ml",
      effective_price: 4.17,
      currency: "EUR",
      availability: "in_stock",
      brand: "Lee Kum Kee",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/cisty-cierny-sezamovy-olej-100-lee-kum-kee-207-ml-1797.jpg?ft=1739209284&nwtrmrk=1",
      link: "https://www.foodland.sk/olej-na-dochucovanie/cisty-cierny-sezamovy-olej-100-lee-kum-kee-207-ml/",
    },
    {
      title: "Bezlepková sójová omáčka MEGACHEF 200 ml",
      effective_price: 3.45,
      currency: "EUR",
      availability: "in_stock",
      brand: "MEGACHEF",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/bezlepkova-sojova-omacka-megachef-200-ml-591.jpg?ft=1680262409&nwtrmrk=1",
      link: "https://www.foodland.sk/sojove-omacky/bezlepkova-sojova-omacka-megachef-200-ml/",
    },
  ];

  const padThaiIngredientDemoProducts = [
    {
      title: "Chantaboon ryžové rezance tyčinky 3 mm FARMER 400 g",
      effective_price: 2.14,
      currency: "EUR",
      availability: "in_stock",
      brand: "FARMER",
      image_link: "",
      link: "https://www.foodland.sk/ryzove-rezance/chantaboon-ryzove-rezance-tycinky-3-mm-farmer-400-g/",
    },
    {
      title: "Pad Thai Omáčka (thajské vyprážané rezance) POR KWAN 225g",
      effective_price: 2.97,
      currency: "EUR",
      availability: "in_stock",
      brand: "POR KWAN",
      image_link: "",
      link: "https://www.foodland.sk/omacky-a-marinady/pad-thai-omacka-thajske-vyprazane-rezance-por-kwan-225g/",
    },
    {
      title: "Rybacia omáčka 40N THUAN PHAT 620ml",
      effective_price: 5.35,
      currency: "EUR",
      availability: "in_stock",
      brand: "THUAN PHAT",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/rybacia-omacka-40n-thuan-phat-620ml-1251.jpg?ft=1679693791&nwtrmrk=1",
      link: "https://www.foodland.sk/rybacie-omacky/rybacia-omacka-40n-thuan-phat-620ml/",
    },
  ];

  const phoIngredientDemoProducts = [
    {
      title: "Chantaboon ryžové rezance tyčinky 3 mm FARMER 400 g",
      effective_price: 2.14,
      currency: "EUR",
      availability: "in_stock",
      brand: "FARMER",
      image_link: "",
      link: "https://www.foodland.sk/ryzove-rezance/chantaboon-ryzove-rezance-tycinky-3-mm-farmer-400-g/",
    },
    {
      title: "Rybacia omáčka 40N THUAN PHAT 620ml",
      effective_price: 5.35,
      currency: "EUR",
      availability: "in_stock",
      brand: "THUAN PHAT",
      image_link: "https://www.foodland.sk/sub/foodland.sk/shop/product/rybacia-omacka-40n-thuan-phat-620ml-1251.jpg?ft=1679693791&nwtrmrk=1",
      link: "https://www.foodland.sk/rybacie-omacky/rybacia-omacka-40n-thuan-phat-620ml/",
    },
    {
      title: "Hoisin omáčka FLYING GOOSE BRAND 200ml",
      effective_price: 2.71,
      currency: "EUR",
      availability: "in_stock",
      brand: "FLYING GOOSE",
      image_link: "",
      link: "https://www.foodland.sk/hoisin-omacky/hoisin-omacka-flying-goose-brand-200ml/",
    },
  ];

  function removeDiacritics(value) {
    return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function normalizedInput(value) {
    return removeDiacritics(String(value || "").toLowerCase());
  }

  function rememberProductSubject(text) {
    const normalizedText = normalizedInput(text);
    const recipeSubject = detectRecipeSubject(normalizedText);
    if (isRecipeRequest(normalizedText) && recipeSubject) {
      lastRecipeSubject = recipeSubject;
      lastProductSubject = "";
      return;
    }

    if (normalizedText.includes("kimchi") || normalizedText.includes("kimci")) {
      lastProductSubject = "kimchi";
    } else if (isSoySauceRequest(normalizedText)) {
      lastProductSubject = "sojova omacka";
    } else if (normalizedText.includes("sushi") || normalizedText.includes("susi")) {
      lastProductSubject = "sushi";
    } else if (normalizedText.includes("ramen") || normalizedText.includes("ramyun") || normalizedText.includes("ramyeon")) {
      lastProductSubject = "ramen";
    } else if (normalizedText.includes("pho") || normalizedText.includes("phở")) {
      lastProductSubject = "pho";
    } else if (normalizedText.includes("gochujang") || normalizedText.includes("gochuang")) {
      lastProductSubject = "gochujang";
    }
  }

  function withFollowUpContext(text) {
    const normalizedText = normalizedInput(text).trim();
    const hasKnownSubject = ["kimchi", "kimci", "sushi", "susi", "ramen", "ramyun", "ramyeon", "pho", "phở", "gochujang", "gochuang", "sojova", "sojove", "sojovy", "omacka", "omacky"].some(function (subject) {
      return normalizedText.includes(subject);
    });
    const isExplicitProductQuery = isSoySauceRequest(normalizedText)
      || normalizedText.includes("srirach")
      || normalizedText.includes("srirac");
    const isRelatedFollowUp = [
      "na vyrobu",
      "na pripravu",
      "ingrediencie",
      "suroviny",
      "co k tomu",
      "co este",
      "co potrebujem",
      "co kupit",
      "suvisiace",
    ].some(function (marker) {
      return normalizedText.includes(marker);
    });

    const recipeSubject = detectRecipeSubject(normalizedText);
    const isRecipeFollowUp = lastRecipeSubject
      && recipeSubject
      && !isIngredientRequest(normalizedText)
      && !isRecipeRequest(normalizedText)
      && normalizedText.length <= 40;
    if (isRecipeFollowUp) {
      return `recept ${text}`;
    }

    if (lastProductSubject && !hasKnownSubject && !isExplicitProductQuery && isRelatedFollowUp) {
      return `${lastProductSubject} ${text}`;
    }
    return text;
  }

  function isSoySauceRequest(normalizedText) {
    return (normalizedText.includes("sojov") || normalizedText.includes("soy sauce") || normalizedText.includes("tamari"))
      && (normalizedText.includes("omack") || normalizedText.includes("sauce") || normalizedText.includes("tamari"));
  }

  function isIngredientRequest(normalizedText) {
    return [
      "na vyrobu",
      "na pripravu",
      "ingrediencie",
      "suroviny",
      "co potrebujem",
      "co kupit",
      "nakupny zoznam",
      "urobit",
      "spravit",
      "pripravit",
    ].some(function (marker) {
      return normalizedText.includes(marker);
    });
  }

  function isRecipeRequest(normalizedText) {
    if (["recept", "reept", "recet", "receppt", "navod", "postup"].some(function (marker) {
      return normalizedText.includes(marker);
    })) return true;
    return normalizedText.split(/\s+/).some(function (token) {
      return token.startsWith("rec") || token.startsWith("recep");
    });
  }

  function detectRecipeSubject(normalizedText) {
    if (normalizedText.includes("pad thai") || normalizedText.includes("padthai")) return "pad_thai";
    if (normalizedText.includes("pho") || normalizedText.includes("phở")) return "pho";
    if (normalizedText.includes("ramen") || normalizedText.includes("ramyun") || normalizedText.includes("ramyeon")) return "ramen";
    if (normalizedText.includes("kimchi") || normalizedText.includes("kimci")) return "kimchi";
    return "";
  }

  function demoRecipesForText(normalizedText) {
    const subject = detectRecipeSubject(normalizedText);
    if (!subject) return [];
    return demoRecipeCatalog[subject] || [];
  }

  function isKimchiIngredientRequest(normalizedText) {
    const mentionsKimchi = normalizedText.includes("kimchi") || normalizedText.includes("kimci");
    return mentionsKimchi && isIngredientRequest(normalizedText);
  }

  function demoIngredientProductsForText(normalizedText) {
    const subject = detectRecipeSubject(normalizedText);
    if (!isIngredientRequest(normalizedText)) return [];
    if (subject === "pad_thai") return padThaiIngredientDemoProducts;
    if (subject === "pho") return phoIngredientDemoProducts;
    if (subject === "kimchi") return kimchiIngredientDemoProducts;
    return [];
  }

  const style = document.createElement("style");
  style.textContent = `
    .fl-ai-root, .fl-ai-root * { box-sizing: border-box; letter-spacing: 0; }
    .fl-ai-root {
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: 2147483000;
      font-family: "Open Sans", Arial, sans-serif;
      color: #221F20;
      pointer-events: none;
    }
    .fl-ai-launcher {
      position: relative;
      z-index: 2147483002;
      width: 62px;
      height: 62px;
      display: grid;
      place-items: center;
      border: 0;
      border-radius: 50%;
      background: #299B5E;
      color: #fff;
      cursor: pointer;
      pointer-events: auto;
      transition: transform 160ms ease, background 160ms ease;
    }
    .fl-ai-launcher:hover {
      transform: translateY(-2px);
      background: #238750;
    }
    .fl-ai-launcher svg { width: 28px; height: 28px; display: block; }
    .fl-ai-launcher-wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 7px;
      pointer-events: auto;
    }
    .fl-ai-agent-name {
      background: rgba(20, 40, 28, 0.72);
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.6px;
      padding: 3px 9px;
      border-radius: 10px;
      white-space: nowrap;
      pointer-events: none;
      backdrop-filter: blur(4px);
    
        .fl-ai-avatar {
          width: 60px;
          height: 60px;
          border-radius: 50%;
          object-fit: cover;
          object-position: 50% 20%;
          border: 2.5px solid rgba(255,255,255,0.92);
          display: block;
        }}
    .fl-ai-panel {
      position: fixed;
      right: 20px;
      bottom: 96px;
      z-index: 2147483001;
      width: min(410px, calc(100vw - 32px));
      height: min(640px, calc(100vh - 116px));
      display: none;
      flex-direction: column;
      pointer-events: auto;
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
      border: 1.5px solid #299B5E;
      background: transparent;
      color: #299B5E;
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }
    .fl-ai-product-link:hover { background: #f2faf5; }
    .fl-ai-product-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    .fl-ai-cart-btn {
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
      cursor: pointer;
      border: 0;
      transition: background 120ms ease;
    }
    .fl-ai-cart-btn:hover:not(:disabled) { background: #238750; }
    .fl-ai-cart-btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .fl-ai-cart-btn.is-added { background: #238750; }
    .fl-ai-recipes { display: grid; gap: 10px; margin: 0 0 12px; }
    .fl-ai-recipe {
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid #dde7df;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 20px rgba(29, 48, 38, 0.06);
    }
    .fl-ai-recipe-title {
      margin: 0;
      color: #221F20;
      font-size: 14px;
      line-height: 1.28;
      font-weight: 800;
    }
    .fl-ai-recipe-meta {
      color: #5d6d63;
      font-size: 12px;
      line-height: 1.35;
    }
    .fl-ai-notice[hidden] { display: none; }
    .fl-ai-recipe-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: max-content;
      max-width: 100%;
      min-height: 32px;
      padding: 7px 10px;
      border-radius: 6px;
      background: #299B5E;
      color: #fff;
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
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
    .fl-ai-suggestions { display: flex; flex-wrap: wrap; gap: 6px; padding: 2px 0 8px; }
    .fl-ai-suggestion {
      padding: 5px 12px;
      border: 1px solid #299B5E;
      border-radius: 20px;
      background: #f2faf5;
      color: #299B5E;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      line-height: 1.35;
      transition: background 120ms ease, color 120ms ease;
    }
    .fl-ai-suggestion:hover { background: #299B5E; color: #fff; }
    .fl-ai-show-more {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      padding: 9px 14px;
      border: 1px dashed #299B5E;
      border-radius: 8px;
      background: #f2faf5;
      color: #299B5E;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      transition: background 120ms ease;
    }
    .fl-ai-show-more:hover { background: #e6f5ee; }
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
      <div class="fl-ai-notice" hidden>Pri alergiách, zložení a dostupnosti si prosím overte detail produktu.</div>
      <div class="fl-ai-messages" aria-live="polite"></div>
      <form class="fl-ai-form">
        <input class="fl-ai-input" type="text" placeholder="Napíšte, čo hľadáte..." autocomplete="off" />
        <button class="fl-ai-submit" type="submit">Poslať</button>
      </form>
    </section>
    <div class="fl-ai-launcher-wrap">
      <img class="fl-ai-avatar" src="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiIHN0YW5kYWxvbmU9Im5vIj8+CjxzdmcKICAgeG1sbnM6ZGM9Imh0dHA6Ly9wdXJsLm9yZy9kYy9lbGVtZW50cy8xLjEvIgogICB4bWxuczpjYz0iaHR0cDovL2NyZWF0aXZlY29tbW9ucy5vcmcvbnMjIgogICB4bWxuczpyZGY9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkvMDIvMjItcmRmLXN5bnRheC1ucyMiCiAgIHhtbG5zOnN2Zz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciCiAgIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIKICAgdmlld0JveD0iMCAwIDI2NzYuMDUzMiAyNjc2LjA1MzIiCiAgIGhlaWdodD0iMjY3Ni4wNTMyIgogICB3aWR0aD0iMjY3Ni4wNTMyIgogICB4bWw6c3BhY2U9InByZXNlcnZlIgogICBpZD0ic3ZnMiIKICAgdmVyc2lvbj0iMS4xIj48bWV0YWRhdGEKICAgICBpZD0ibWV0YWRhdGE4Ij48cmRmOlJERj48Y2M6V29yawogICAgICAgICByZGY6YWJvdXQ9IiI+PGRjOmZvcm1hdD5pbWFnZS9zdmcreG1sPC9kYzpmb3JtYXQ+PGRjOnR5cGUKICAgICAgICAgICByZGY6cmVzb3VyY2U9Imh0dHA6Ly9wdXJsLm9yZy9kYy9kY21pdHlwZS9TdGlsbEltYWdlIiAvPjwvY2M6V29yaz48L3JkZjpSREY+PC9tZXRhZGF0YT48ZGVmcwogICAgIGlkPSJkZWZzNiI+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGg1NiIKICAgICAgIGNsaXBQYXRoVW5pdHM9InVzZXJTcGFjZU9uVXNlIj48cGF0aAogICAgICAgICBpZD0icGF0aDU0IgogICAgICAgICBkPSJtIDEzODA3LjEsMTY1MDUuOCBjIDIwLjUsLTI2LjQgNDUuNiwtNTMuNiA2MS40LC04MyAxMDA5LjksLTEyMTkuNyAxMjIzLjcsLTMwMDkuMSAxMDgwLjMsLTQ1MzUuMSBDIDE0NzU3LjEsOTg0Ni42IDEzODQwLDgxMTcuNiAxMjI1OC42LDY4MTEgYyAtMjcuOCwtMjMgLTU1LjgsLTQ1LjMgLTg1LjMsLTY2LjIgLTIuMSw0Ny43IC0xLDk4LjIgLTEwLjcsMTQ0LjkgbCAtMi4zLDQwLjEgYyA1LDY4LjcgLTEuMywxMzguNyAtNC44LDIwNy41IDM3LjgsNjguMyAxMjEuNCwxMzkuMiAxNzMuOCwxOTkuNiA4NCw5Ny43IDE2My40LDE5OSAyMzguMSwzMDQgMjM5LjMsMzM4IDQwNi45LDczMy42IDUyMi45LDExMjkuNiAzOC42LDEzMS40IDY0LjMsMjY2LjUgMTA0LjMsMzk3LjQgMzMuMywxODMuNyA4NSwzNzMuMiAxMzcsNTUyLjcgNDkuOCwyMDQuMyA5NS43LDQxNi43IDE3MS4yLDYxMy4yIDE3LjgsMTU4IDE1LDMxOS43IDE2LjQsNDc4LjUgMi44LDMwMi40IC0zLjEsNjA1LjUgMy40LDkwNy43IC0xMi43LDkxIC02LjUsMTkyLjUgLTYuOSwyODQuNSBsIC0yLjEsNTI1LjEgYyAtMi4xLDMuNyAtMy42LDcuOCAtNi40LDExIC04Myw5OC40IC0xNDQuMiwyMTUgLTIxOSwzMjAuNyAtMTMzLjgsMTg4LjQgLTI3Ni4zLDM3MCAtNDI3LjQsNTQ0LjggOTQuNCwtNDIuNyAyMTIuNiwtMjI2LjEgMjc2LjcsLTMxMiAyMS44LDI5IDUzLDYyLjQgNjkuMSw5NC40IDM3LjUsNzQuOCAtMjM1LjgsMjM5LjYgLTI1NiwzMjMuNSAtOTUuMywxMTguOSAtMjQ3LjMsMjIzLjYgLTM2NC45LDMyMS43IC0zOTguNCwzMzYuMiAtODEwLjEsNjU1LjQgLTEyMzQuOCw5NTcuNiA2NC43LDgxIDMyMi45LDIyOS4zIDQyNC40LDI5Ny43IGwgNjAyLjUsNDEyLjYgYyA0NzguMiwzMzEuNSA5NDUuNyw2ODEuMiAxNDI5LjMsMTAwNC4yIHoiIC8+PC9jbGlwUGF0aD48bGluZWFyR3JhZGllbnQKICAgICAgIGlkPSJsaW5lYXJHcmFkaWVudDY0IgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KDIyNDQuNTYsLTY1MS41OCw2NTEuNTgsMjI0NC41NiwxMjU5NywxMTczOS41KSIKICAgICAgIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIgogICAgICAgeTI9IjAiCiAgICAgICB4Mj0iMSIKICAgICAgIHkxPSIwIgogICAgICAgeDE9IjAiPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wNjAiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6IzE0MTIxMiIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDYyIgogICAgICAgICBvZmZzZXQ9IjEiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiMyMTJhMmQiIC8+PC9saW5lYXJHcmFkaWVudD48Y2xpcFBhdGgKICAgICAgIGlkPSJjbGlwUGF0aDEwMiIKICAgICAgIGNsaXBQYXRoVW5pdHM9InVzZXJTcGFjZU9uVXNlIj48cGF0aAogICAgICAgICBpZD0icGF0aDEwMCIKICAgICAgICAgZD0ibSAxMDkxNy45LDYwOTkuMyBjIDQ4My42LDI1My42IDg2OCw2NDUgMTIzNy42LDEwMzggMy41LC02OC44IDkuOCwtMTM4LjggNC44LC0yMDcuNSBsIDIuMywtNDAuMSBjIC0zLC0xOTMuMiAyNS42LC0zOTIuMSA0Mi43LC01ODQuNiAzMS42LC0zNTQgNjAuMSwtNzEzLjQgMTIxLjksLTEwNjMuNyA0MS44LC0yNTkgODUuNSwtNTE3LjYgMTMxLjEsLTc3NiA0LjcsLTIxLjcgOS44LC00My4zIDEzLjIsLTY1LjIgLTU4LjUsLTgxLjEgLTIyMy4xLC0xODguMSAtMzAzLjcsLTI2OC45IC0xODguNSwtMTg4LjkgLTM1OS44LC00MDMuMiAtNTM0LjUsLTYwNS4zIC0zOTMuMiwtNDU0LjcgLTc2OSwtOTMxLjggLTExMzMuNywtMTQwOS43IC0xMzUuMSwtMTc3IC0yNjIuNiwtMzU5LjggLTM5OS40LC01MzUuNCAtMTMwLjM1LDE3My4yIC0yNDQuODMsMzU4LjUgLTM3NC45NSw1MzIuMSAtMzQyLjIyLDQ1Ni43IC03MDIuOTYsOTA0LjIgLTEwNjQuMzMsMTM0NS45IC0yMzQuMTQsMjg2LjcgLTYyNi43Myw3ODguNCAtOTM3Ljg1LDk3Ny43IDUzLjE5LDI2NS41IDEwMC40OSw1MzIgMTQxLjksNzk5LjYgMzAuODIsMTA1IDMyLjU3LDI2NS4zIDQ0Ljc5LDM3Ni43IDM5LjY1LDM2MS45IDgyLjk4LDcyOC4xIDk3Ljk0LDEwOTIuMSAxLjcyLDEwMC45IDAuOSwyMDIgMS4xMSwzMDIuOSA1NzYuMiwtNTcyLjUgMTE3Mi4wNCwtMTE1NCAyMDQyLjI5LC0xMTUwLjMgMjc3LjQsMS4xIDY0NC45LDYwLjkgODY2LjgsMjQxLjcgeiIgLz48L2NsaXBQYXRoPjxsaW5lYXJHcmFkaWVudAogICAgICAgaWQ9ImxpbmVhckdyYWRpZW50MTA4IgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KDM4MDMuNDcsNzcyLjczNiwtNzcyLjczNiwzODAzLjQ3LDg1MzQuNjIsNDE4OC44KSIKICAgICAgIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIgogICAgICAgeTI9IjAiCiAgICAgICB4Mj0iMSIKICAgICAgIHkxPSIwIgogICAgICAgeDE9IjAiPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMTA0IgogICAgICAgICBvZmZzZXQ9IjAiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiNmOGEwNjUiIC8+PHN0b3AKICAgICAgICAgaWQ9InN0b3AxMDYiCiAgICAgICAgIG9mZnNldD0iMSIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2ZkZTRiNyIgLz48L2xpbmVhckdyYWRpZW50PjxjbGlwUGF0aAogICAgICAgaWQ9ImNsaXBQYXRoMTIwIgogICAgICAgY2xpcFBhdGhVbml0cz0idXNlclNwYWNlT25Vc2UiPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTE4IgogICAgICAgICBkPSJtIDEwOTE3LjksNjA5OS4zIGMgNDgzLjYsMjUzLjYgODY4LDY0NSAxMjM3LjYsMTAzOCAzLjUsLTY4LjggOS44LC0xMzguOCA0LjgsLTIwNy41IGwgLTMxNCwtMzg5LjIgYyAtMTUxLC0xNjguMyAtMzAwLjMsLTMzOS42IC00NTcsLTUwMi41IC01ODAuMiwtNjAzLjQgLTEyMDQuOSwtMTE3Mi40IC0xODIwLjY2LC0xNzM5LjQgLTE3Ny44NiwtMTYyLjIgLTM1NC40NywtMzI1LjcgLTUyOS44MywtNDkwLjYgLTEyMy43NSwtMTE2LjcgLTI0Ni4zNCwtMjQxLjcgLTM3Ny44OSwtMzQ5LjIgLTIzNC4xNCwyODYuNyAtNjI2LjczLDc4OC40IC05MzcuODUsOTc3LjcgNTMuMTksMjY1LjUgMTAwLjQ5LDUzMiAxNDEuOSw3OTkuNiAzMC44MiwxMDUgMzIuNTcsMjY1LjMgNDQuNzksMzc2LjcgMzkuNjUsMzYxLjkgODIuOTgsNzI4LjEgOTcuOTQsMTA5Mi4xIDEuNzIsMTAwLjkgMC45LDIwMiAxLjExLDMwMi45IDU3Ni4yLC01NzIuNSAxMTcyLjA0LC0xMTU0IDIwNDIuMjksLTExNTAuMyAyNzcuNCwxLjEgNjQ0LjksNjAuOSA4NjYuOCwyNDEuNyB6IiAvPjwvY2xpcFBhdGg+PGxpbmVhckdyYWRpZW50CiAgICAgICBpZD0ibGluZWFyR3JhZGllbnQxMjYiCiAgICAgICBzcHJlYWRNZXRob2Q9InBhZCIKICAgICAgIGdyYWRpZW50VHJhbnNmb3JtPSJtYXRyaXgoLTE1NzUuNDgsLTQyOTQuODcsNDI5NC44NywtMTU3NS40OCwxMDM2OC4zLDc3NDIuMykiCiAgICAgICBncmFkaWVudFVuaXRzPSJ1c2VyU3BhY2VPblVzZSIKICAgICAgIHkyPSIwIgogICAgICAgeDI9IjEiCiAgICAgICB5MT0iMCIKICAgICAgIHgxPSIwIj48c3RvcAogICAgICAgICBpZD0ic3RvcDEyMiIKICAgICAgICAgb2Zmc2V0PSIwIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojYWExZTI0IiAvPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMTI0IgogICAgICAgICBvZmZzZXQ9IjEiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiNlYTgxNGMiIC8+PC9saW5lYXJHcmFkaWVudD48Y2xpcFBhdGgKICAgICAgIGlkPSJjbGlwUGF0aDE0MCIKICAgICAgIGNsaXBQYXRoVW5pdHM9InVzZXJTcGFjZU9uVXNlIj48cGF0aAogICAgICAgICBpZD0icGF0aDEzOCIKICAgICAgICAgZD0ibSAxMjg0OS42LDQ1OTMuNCBjIDI2LjksLTEuOCA2Mi44LDAuMSA4Ni40LC0xMi4zIC0zOC44LC04NS40IC0xNTIuMiwtMjAyLjIgLTIxMi43LC0yODEuMiAtMjE3LjYsLTI4OCAtNDM3LjcsLTU3NCAtNjYwLjIsLTg1OC4xIEwgMTA0MzMuOSwxMjk4LjEgQyAxMDEwNy4zLDg2Ny41IDk3NjUuMzEsNDQyLjgwMSA5NDU1Ljk0LDAgaCAtNjAzLjU4IGwgOTE0Ljk5LDExNTQuOSBjIDgzLjA3LDEyMC44IDE4OCwyMzQuOCAyNzkuODUsMzQ5LjkgMTkuNywyNC42IDM2LjYsNDkuMSA1Myw3Ni4xIDEzNi44LDE3NS42IDI2NC4zLDM1OC40IDM5OS40LDUzNS40IDM2NC43LDQ3Ny45IDc0MC41LDk1NSAxMTMzLjcsMTQwOS43IDE3NC43LDIwMi4xIDM0Niw0MTYuNCA1MzQuNSw2MDUuMyA4MC42LDgwLjggMjQ1LjIsMTg3LjggMzAzLjcsMjY4LjkgMTMxLjgsNDMuMyAxNTMuMywxNjEuOSAzNzguMSwxOTMuMiB6IiAvPjwvY2xpcFBhdGg+PGxpbmVhckdyYWRpZW50CiAgICAgICBpZD0ibGluZWFyR3JhZGllbnQxNDYiCiAgICAgICBzcHJlYWRNZXRob2Q9InBhZCIKICAgICAgIGdyYWRpZW50VHJhbnNmb3JtPSJtYXRyaXgoMTE0My4yOCwtMTk1OC41NiwxOTU4LjU2LDExNDMuMjgsMTAzNzMuNiwzMTgyLjIpIgogICAgICAgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiCiAgICAgICB5Mj0iMCIKICAgICAgIHgyPSIxIgogICAgICAgeTE9IjAiCiAgICAgICB4MT0iMCI+PHN0b3AKICAgICAgICAgaWQ9InN0b3AxNDIiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2YzZGRkNCIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDE0NCIKICAgICAgICAgb2Zmc2V0PSIxIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojZjBmNWUyIiAvPjwvbGluZWFyR3JhZGllbnQ+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGgyMDAiCiAgICAgICBjbGlwUGF0aFVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxOTgiCiAgICAgICAgIGQ9Im0gMTA4MDkuOCwxMjI2Mi40IGMgMTcuOCw3Mi44IDM4LjksMTU1LjcgODAsMjE4LjggMTA1LjQsMTYxLjggNTYzLjksMjcyLjIgNzU2LjMsMzE4IDQ0Ni42LDEwNi4zIDc0NS41LDE1MC42IDExNDkuMSwtOTguNSAtMTIuOCwtMjAuOCAtMjIuNywtMzcuOCAtNDAuOCwtNTQuOCAtOTEuNSwzMC4yIC0xNzAuMSwzNy4yIC0yNjYsMzcuNSAtMjUzLjUsLTI2LjEgLTUwNS4yLC0xMTYuNyAtNzUwLjIsLTE4NS4yIC0zMDguMSwtODMuOSAtNjE3LjYsLTE2Mi41IC05MjguNCwtMjM1LjggeiIgLz48L2NsaXBQYXRoPjxsaW5lYXJHcmFkaWVudAogICAgICAgaWQ9ImxpbmVhckdyYWRpZW50MjA2IgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KC0xNzM1LjI2LDQzMS45NDIsLTQzMS45NDIsLTE3MzUuMjYsMTI2NzMuOSwxMjI5Ny43KSIKICAgICAgIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIgogICAgICAgeTI9IjAiCiAgICAgICB4Mj0iMSIKICAgICAgIHkxPSIwIgogICAgICAgeDE9IjAiPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMjAyIgogICAgICAgICBvZmZzZXQ9IjAiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiMxYTFhMWMiIC8+PHN0b3AKICAgICAgICAgaWQ9InN0b3AyMDQiCiAgICAgICAgIG9mZnNldD0iMSIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6IzFhNDY0ZiIgLz48L2xpbmVhckdyYWRpZW50PjxjbGlwUGF0aAogICAgICAgaWQ9ImNsaXBQYXRoMjIyIgogICAgICAgY2xpcFBhdGhVbml0cz0idXNlclNwYWNlT25Vc2UiPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjIwIgogICAgICAgICBkPSJtIDc3OTIuOTEsMTE0NTkuMSBjIDQ5Ljk4LDQyIDExOC4wNiw5OS4zIDE4MC45OCwxMTkuMiAxOS44Miw2LjIgMTEuMzcsNi4zIDMwLjE0LC00IGwgLTEuODQsLTI0LjIgYyAwLjczLC0xMzMuOSAwLjYxLC0yNTguMyAxMDEuMzMsLTM2MC44IDUxLC01MS45IDEyMC4xMywtODMuOCAxOTMuNSwtODIuMiA3Ni42OSwxLjcgMTQ2LjA3LDM5LjkgMTk2Ljk3LDk1LjkgNzAuMDgsNzcuMiA5Mi40LDE2OC4zIDEwOCwyNjcuNyA3NC44OSwtNTYgMTkzLjIsLTEzMi40IDIzOS4zNywtMjE2LjQgLTY2Ljk5LC0zOS44IC0xMzIuODQsLTc2LjggLTIwNC4yMSwtMTA4LjIgLTQ1LjgxLC0yMC4yIC05OS44OCwtMzUuMiAtMTQyLjc4LC02MCAtOSwtMi4zIC0xNy45OCwtNC43IC0yNy4wMywtNi43IC0zMjAuMywtNzEuOCAtNTYwLjYzLDYwLjcgLTgyMy40LDIzMC4xIDQ0LjM4LDU3LjEgOTAuODksMTA2LjMgMTQ4Ljk3LDE0OS42IHoiIC8+PC9jbGlwUGF0aD48bGluZWFyR3JhZGllbnQKICAgICAgIGlkPSJsaW5lYXJHcmFkaWVudDIyOCIKICAgICAgIHNwcmVhZE1ldGhvZD0icGFkIgogICAgICAgZ3JhZGllbnRUcmFuc2Zvcm09Im1hdHJpeCg4OTAuMzc2LC00OTAuMzA0LDQ5MC4zMDQsODkwLjM3Niw3ODA1LjA4LDExNTU5LjkpIgogICAgICAgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiCiAgICAgICB5Mj0iMCIKICAgICAgIHgyPSIxIgogICAgICAgeTE9IjAiCiAgICAgICB4MT0iMCI+PHN0b3AKICAgICAgICAgaWQ9InN0b3AyMjQiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2M1YzFiYiIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDIyNiIKICAgICAgICAgb2Zmc2V0PSIxIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojZmZmZmZmIiAvPjwvbGluZWFyR3JhZGllbnQ+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGgyNDAiCiAgICAgICBjbGlwUGF0aFVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyMzgiCiAgICAgICAgIGQ9Im0gMTAwNjksMTU3MTUuNyBjIDE1Ny44LC0xMTQuNyAzMjcuNiwtMjExLjQgNDg0LC0zMjguOCAxOTMuMywtMTQ1IDM4Mi4zLC0yOTUuNSA1NzcuMiwtNDM4LjUgNzAuNSwtNTEuNyAxNDQuNSwtMTE0LjMgMjIwLjcsLTE1Ny4xIDQyNC43LC0zMDIuMiA4MzYuNCwtNjIxLjQgMTIzNC44LC05NTcuNiAxMTcuNiwtOTguMSAyNjkuNiwtMjAyLjggMzY0LjksLTMyMS43IDIwLjIsLTgzLjkgMjkzLjUsLTI0OC43IDI1NiwtMzIzLjUgLTE2LjEsLTMyIC00Ny4zLC02NS40IC02OS4xLC05NC40IC02NC4xLDg1LjkgLTE4Mi4zLDI2OS4zIC0yNzYuNywzMTIgLTIyMi40LDIyOC44IC00NjEuOCw0NTMuMSAtNzEwLjcsNjUzLjEgLTM2My42LDI5Mi4yIC03NTQuNiw1NTQuMiAtMTEzMC43LDgzMC41IC0zMjAuMiwyMzUuMiAtNjMyLjUsNTAwLjEgLTk3Ni41LDY5OS44IC0zNTkuMzIsLTE4MC41IC02OTkuODQsLTQwNi45IC0xMDM4LjI5LC02MjMuMiAtMzk5Ljg2LC0yNTUuNSAtODAxLjk5LC01MTEuNCAtMTE4OC45MywtNzg2LjIgLTE1My4xNSwtOTYuMSAtMjk5LjM4LC0yMDEuOCAtNDM4LjcxLC0zMTcuMSAtMTE1LjU0LC05Ni4zIC0yMjYuNTksLTIwMSAtMzQ1Ljg0LC0yOTIuNSAtMjAuMzYsLTE1LjYgLTMzLjYsLTIzLjEgLTU4Ljg0LC0yNi45IDMzMC4yNSw0NTQuOSA4NTguNzEsNzg1LjcgMTMyMC4yMywxMDkyLjEgMTU2LjIyLDc1LjQgNDI3LjgsMjc3LjcgNTgzLjA2LDM4MS41IDQxMC45LDI0Ny40IDc1Ni43OCw0ODIuNyAxMTkzLjQyLDY5OC41IHoiIC8+PC9jbGlwUGF0aD48bGluZWFyR3JhZGllbnQKICAgICAgIGlkPSJsaW5lYXJHcmFkaWVudDI0NiIKICAgICAgIHNwcmVhZE1ldGhvZD0icGFkIgogICAgICAgZ3JhZGllbnRUcmFuc2Zvcm09Im1hdHJpeCgxMzg4LjUzLC0zMzAxLjUzLDMzMDEuNTMsMTM4OC41Myw5MjU4LjQsMTUzNTkpIgogICAgICAgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiCiAgICAgICB5Mj0iMCIKICAgICAgIHgyPSIxIgogICAgICAgeTE9IjAiCiAgICAgICB4MT0iMCI+PHN0b3AKICAgICAgICAgaWQ9InN0b3AyNDIiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2RhM2QyNiIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDI0NCIKICAgICAgICAgb2Zmc2V0PSIxIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojZWE4MTUxIiAvPjwvbGluZWFyR3JhZGllbnQ+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGgyNzQiCiAgICAgICBjbGlwUGF0aFVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNzIiCiAgICAgICAgIGQ9Im0gNzY5NC43LDEyODc3LjUgYyAzNjYuMjEsNC41IDcyOS4wMSwtNzUgMTA3Ni4yLC0xODYuOCA2OS40NSwtMjIuNCAxNTcuMDksLTQ1LjUgMjE5LjY2LC04MS4zIDI5LjU5LC05My44IC00Ni45OCwtMTc0LjQgLTQyLjIzLC0yNjUuNSAtMTc2LjIyLDM2LjkgLTM1Mi4yNCw5NS4yIC01MjYuNjUsMTQxLjUgLTIwNS45Myw1OC41IC03MTguODYsMjA4LjUgLTkxMS4yNCwyMDYuNSAtMjYwLjMyLC0yLjYgLTQ2Ny43MywtMTc4LjMgLTYzOC43MiwtMzU1IDE1LjExLDIzIDMxLjQsNDQuOSA0OC40Nyw2Ni41IDE5Ni40LDI0OC4yIDQ1NS44NCw0MzguMSA3NzQuNTEsNDc0LjEgeiIgLz48L2NsaXBQYXRoPjxsaW5lYXJHcmFkaWVudAogICAgICAgaWQ9ImxpbmVhckdyYWRpZW50MjgwIgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KDE2NzQuMjEsLTYwMS43NDYsNjAxLjc0NiwxNjc0LjIxLDcxODUuNDQsMTI3NDQuOCkiCiAgICAgICBncmFkaWVudFVuaXRzPSJ1c2VyU3BhY2VPblVzZSIKICAgICAgIHkyPSIwIgogICAgICAgeDI9IjEiCiAgICAgICB5MT0iMCIKICAgICAgIHgxPSIwIj48c3RvcAogICAgICAgICBpZD0ic3RvcDI3NiIKICAgICAgICAgb2Zmc2V0PSIwIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojMTQxMjEyIiAvPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMjc4IgogICAgICAgICBvZmZzZXQ9IjEiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiMxZTNjNGEiIC8+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PGcKICAgICB0cmFuc2Zvcm09Im1hdHJpeCgxLjMzMzMzMzMsMCwwLC0xLjMzMzMzMzMsMCwyNjc2LjA1MzMpIgogICAgIGlkPSJnMTAiPjxnCiAgICAgICB0cmFuc2Zvcm09InNjYWxlKDAuMSkiCiAgICAgICBpZD0iZzEyIj48ZwogICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMjMxMjkpIgogICAgICAgICBpZD0iZzE0Ij48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMTYiCiAgICAgICAgICAgc3R5bGU9ImZpbGw6I2RkMWUyNjtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICBkPSJNIDAsMTYzMDAuMyBIIDE2MzAwLjMgViAwIEggMTYwMzAuNyAxNDkyOC44IDEwNTMwLjYgOTkwMi4xNSA3Njc5LjcxIDcxODkuNTEgNjQwOC44MiA1NzE1LjAyIDM1MjcgMTM0OS4yNyAyOTAuMjEzIDAgdiAxNjMwMC4zIiAvPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDE4IgogICAgICAgICBzdHlsZT0iZmlsbDojNDcyMDI4O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDEyMzI3LjIsNTI0MS40IGMgMTI5LC0xLjUgMTA0OC4yLC0xOC42IDEwODQuNCwtNDEuNCAtMTI3LjYsLTIxNS4xIC0zMjEuMywtMzkxLjUgLTQ1NS45LC02MDMuNSAtMzMuMiwwLjYgLTc0LjQsNi4zIC0xMDYuMSwtMy4xIC0yMjQuOCwtMzEuMyAtMjQ2LjMsLTE0OS45IC0zNzguMSwtMTkzLjIgLTMuNCwyMS45IC04LjUsNDMuNSAtMTMuMiw2NS4yIC00NS42LDI1OC40IC04OS4zLDUxNyAtMTMxLjEsNzc2IiAvPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4xNDg4MykiCiAgICAgICAgIGlkPSJnMjAiPjxwYXRoCiAgICAgICAgICAgaWQ9InBhdGgyMiIKICAgICAgICAgICBzdHlsZT0iZmlsbDojMWIxYjFkO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgIGQ9Im0gMTAyMjcuMywxNjI5MC42IGMgNjMuMyw5LjQgMTI1LjYsLTIxLjMgMTc1LjgsLTU4LjEgMTgwLjMsLTEzMi4xIDMyMC4xLC0zODMgMzQ5LjIsLTYwMy40IDguNSwtNjQuMSA2LC0xMjYuNyAtOC43LC0xODkuNyAtNzAuNSwyMi42IC0xNDAuNSw4Mi4zIC0yMDkuNSwxMTQuOCAtMjIwLjUsMTA0IC00NDEuNywxOTEuNSAtNjc3LjI4LDI1NS4xIC03MS45OCwxNTQuMyAtMTc1LjY2LDI3NyAtMzA1LjcsMzg0LjkgMjIwLjMxLDU5LjYgNDU2LjM4LDQzLjkgNjc2LjE4LDk2LjQiIC8+PC9nPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjQiCiAgICAgICAgIHN0eWxlPSJmaWxsOiM0NzIwMjg7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTI0Mi4xLDE0NDguMyBjIDUzLjE5LC05MiA3MS42OCwtMjM1LjcgMTAxLjQ3LC0zNDAuNSBMIDE1MjguODQsNDY4LjgwMSBDIDE1NzIuMzIsMzEzLjIwMyAxNjA5LjE5LDE1Mi45MDIgMTY2MS4zNCwwIEggMzU3LjMzNiBjIDIwMi4zNzEsMzgyLjIwMyA0MjAuNjAyLDc1NS4xMDIgNjU0LjY5NCwxMTE4LjggNzAuODUsMTA5LjEgMTQwLjM5LDIzNS40IDIzMC4wNywzMjkuNSIgLz48ZwogICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMjEwOTQpIgogICAgICAgICBpZD0iZzI2Ij48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMjgiCiAgICAgICAgICAgc3R5bGU9ImZpbGw6Izk0MTkzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICBkPSJNIDE1NTczLjQsMTIxOC43MiBDIDE1NzYyLjYsMTA0Mi4yNSAxNTk3OCw1OTEuMTkzIDE2MTA1LjksMzU0LjQzNyAxNjE2OS42LDIzNi42NzYgMTYyNDAuNywxMTkuOTA5IDE2MzAwLDAgaCAtMTEyMC40IGMgNDQuMSwxMDIuODEyIDc2LjksMjE1Ljc4MyAxMTMuMSwzMjEuODE3IDk5LjcsMjk2Ljk1NyAxOTMuMyw1OTUuOTgxIDI4MC43LDg5Ni45MDMiIC8+PC9nPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4xOTY4OCkiCiAgICAgICAgIGlkPSJnMzAiPjxwYXRoCiAgICAgICAgICAgaWQ9InBhdGgzMiIKICAgICAgICAgICBzdHlsZT0iZmlsbDojMWEzZDQ3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgIGQ9Im0gNjk3Ni44MiwxNTYyNy40IGMgNjAuNzUsNDMuNyAxNDguMjYsMTY3LjUgMjExLjcyLDIyNy4xIDMzNywzMTYuMyA4MjUuMTcsNDQ1LjUgMTI3OC45OSw0MjguNyAzOTYuOTQsLTE0LjggODAyLjc1LC0xNDUuNSAxMTA5LjEzLC00MDMuOSA4Ny44OSwtNzQuMSAxNjIsLTE1OC45IDI0MC4wNCwtMjQyLjcgLTIxMC45NywtNTAuNCAtNDM3LjU2LC0zNS4zIC02NDkuMDIsLTkyLjYgLTM1LjA5LDIyLjEgLTcwLjQzLDQzLjYgLTEwNi4xOSw2NC40IC0zNDkuODMsMjAzLjcgLTcwNC41LDI0OS44IC0xMDk1LjE4LDE0NyAtMTQwLjMyLC01My40IC0yNjUuMjcsLTEyMy4zIC0zOTEuMDQsLTIwNC41IC0xMzQuODUsMzguMSAtMjg3LjE1LDU2LjkgLTQyNi43NCw2Ny43IC01MS45OSw0IC0xMDQuOTksMSAtMTU2LjY0LDcgbCAtMTUuMDcsMS44IiAvPjwvZz48ZwogICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMTU2OTYpIgogICAgICAgICBpZD0iZzM0Ij48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMzYiCiAgICAgICAgICAgc3R5bGU9ImZpbGw6I2IxMWUyYTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICBkPSJtIDEyODA3LjMsMjcxMS4wNiBjIDY5LjksLTU3LjU2IDQ0NiwtMTYyLjkyIDU1Ny45LC0yMDEuNDcgMTAwMi4yLC0zNDQuODcgMjAxMC41LC03MDkuMDEgMjkzNC44LC0xMjM0LjAxIC05MS40LC0zMTQuOTYgLTE4OS40LC02MjcuOTM2IC0yOTMuOCwtOTM4Ljc0NyBDIDE1OTY4LjQsMjI1Ljg1MSAxNTkzNCwxMDcuNjA5IDE1ODg3LjgsMCBoIC00NjgwLjcgYyAxODkuOCwyMzguMzgzIDM2MC4yLDQ4OS4zODQgNTI5LjQsNzQyLjU0OSA0MzMuMyw2NDguMDgxIDc3Ny42LDEyNDIuOTExIDEwNzAuOCwxOTY4LjUxMSIgLz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGgzOCIKICAgICAgICAgc3R5bGU9ImZpbGw6IzFiMWIxZDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA2MDY5LjgzLDE2MjgzLjQgYyA4Ny40NywtMTA5LjkgMjQ4Ljg4LC0yMDMuOCAzNjAuNTksLTI5MS4xIDM4NC4zMiwtMzAyLjEgNzc2LjA0LC01OTQuMiAxMTc1LjE0LC04NzYuNCBsIDQ5My41OCwtMzQxLjUgYyA2Mi41LC00NC4xIDEzNi42NSwtODcuNyAxOTMuMzgsLTEzOC43IC00NjEuNTIsLTMwNi40IC05ODkuOTgsLTYzNy4yIC0xMzIwLjIzLC0xMDkyLjEgLTEzMi4xMSwtMTU3LjggLTI1Ny42NywtMzI0LjcgLTMyOC43MywtNTE5LjkgLTE2Ny41LC00NjAgLTExOC43LC0xNTQ2LjMgLTc0LjAxLC0yMDQ2IDcuNiwtODQuOSAxOC44MywtMTY5LjMgMjguMzIsLTI1My45IDMzLjg5LC04MS4zIDQyLjIsLTE5OS4yIDU4LjMzLC0yODYuNyAzNy42NSwtMjA0LjEgNzMuODksLTQwOC4zIDExOS43MywtNjEwLjggNDIuOTcsLTEyOC45IDU1LjgsLTI3Ny44IDg2LjQ0LC00MTEuMiAyNy40OCwtMTE5LjYgNzMuNzQsLTI0MS4zIDkyLjQ0LC0zNjEuOCAxMzkuNzUsLTYzNC40IDM2Mi40OCwtMTIxMy41IDc3MC4zNywtMTcyNS44IDg5LjQsLTExMi4yIDE4OC4zLC0yMTIuOSAyODMuNjMsLTMxOS42IC0wLjIxLC0xMDAuOSAwLjYxLC0yMDIgLTEuMTEsLTMwMi45IC0yNTEuMDUsMTgwLjEgLTQ4OS41Nyw0MDYuNSAtNzA1LjAxLDYyNy43IC0zMy43MywzNS4xIC02Ny4xMyw3MC42IC0xMDAuMTksMTA2LjMgLTMzLjA4LDM1LjcgLTY1LjgzLDcxLjggLTk4LjI1LDEwOC4xIC0zMi40MSwzNi4zIC02NC41LDczIC05Ni4yNSwxMDkuOSAtMzEuNzUsMzYuOSAtNjMuMTcsNzQuMSAtOTQuMjUsMTExLjYgLTMxLjA4LDM3LjUgLTYxLjgsNzUuMiAtOTIuMTgsMTEzLjMgLTMwLjM4LDM4IC02MC40Miw3Ni40IC05MC4xMSwxMTUgLTI5LjY5LDM4LjYgLTU5LjAyLDc3LjQgLTg4LDExNi42IC0yOC45OCwzOS4xIC01Ny42MSw3OC41IC04NS44NywxMTguMSAtMjguMjYsMzkuNyAtNTYuMTYsNzkuNiAtODMuNjksMTE5LjcgLTI3LjUzLDQwLjIgLTU0LjcsODAuNiAtODEuNDksMTIxLjMgLTI2Ljc5LDQwLjYgLTUzLjIyLDgxLjUgLTc5LjI3LDEyMi43IC0yNi4wNiw0MS4xIC01MS43Myw4Mi41IC03Ny4wMywxMjQuMSAtMjUuMjksNDEuNiAtNTAuMjIsODMuNCAtNzQuNzUsMTI1LjUgLTI0LjU0LDQyIC00OC42OSw4NC4zIC03Mi40NCwxMjYuOCAtMjMuNzcsNDIuNSAtNDcuMTUsODUuMiAtNzAuMTQsMTI4LjEgLTIyLjk3LDQzIC00NS41Nyw4Ni4xIC02Ny43OSwxMjkuNSAtMjIuMiw0My4zIC00NCw4Ni44IC02NS40LDEzMC42IC0yMS40MSw0My43IC00Mi40MSw4Ny42IC02My4wMiwxMzEuNyAtMjAuNiw0NC4xIC00MC44MSw4OC41IC02MC42MiwxMzIuOSAtMTkuOCw0NC41IC0zOS4xOSw4OS4yIC01OC4xOCwxMzQgLTE4Ljk4LDQ0LjkgLTM3LjU1LDg5LjkgLTU1LjcyLDEzNSAtMTguMTYsNDUuMiAtMzUuOTEsOTAuNiAtNTMuMjUsMTM2LjEgLTE3LjMzLDQ1LjUgLTM0LjI2LDkxLjEgLTUwLjc2LDEzNi45IC0xNi41Miw0NS44IC0zMi42MSw5MS44IC00OC4yNywxMzcuOSAtMTUuNjgsNDYuMSAtMzAuOTIsOTIuNCAtNDUuNzYsMTM4LjcgLTE0LjgzLDQ2LjQgLTI5LjIyLDkyLjkgLTQzLjE5LDEzOS42IC0xMy45OCw0Ni42IC0yNy41NCw5My40IC00MC42NywxNDAuMyAtMTMuMTIsNDYuOSAtMjUuODEsOTMuOSAtMzguMDksMTQxIC0xMi4yNiw0Ny4xIC0yNC4xMSw5NC4zIC0zNS41MywxNDEuNyAtMTEuNDEsNDcuMyAtMjIuMzksOTQuNyAtMzIuOTMsMTQyLjMgLTEwLjU0LDQ3LjUgLTIwLjY1LDk1LjIgLTMwLjMyLDE0Mi45IC05LjY5LDQ3LjcgLTE4LjkyLDk1LjUgLTI3LjczLDE0My40IC0yOTMuNjksMTYyOS40IC05NC4xNiwzNDYwLjkgODY4LjI4LDQ4NDkuMSIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDQwIgogICAgICAgICBzdHlsZT0iZmlsbDojY2M1OTJmO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDY5NTQuODEsOTA1My4zIGMgLTU4LjM1LDQuNSAtMTE1LjIyLDkuOSAtMTcwLjE4LDMxLjUgLTMzNC43LDEzMS4zIC01MjUuOTMsNTMzLjMgLTY1OS41Nyw4NDIuOCAtMTcwLjc4LDM5NS42IC01MTkuMzIsMTM4MC4xIC0zNDcuMDIsMTc4OC40IDI0LjI3LDU3LjUgNjEuNzQsMTA0LjYgMTIxLjM4LDEyNy4zIDEwMy4xLDM5LjQgMjEwLjQ1LDkuOCAzMDUuMTcsLTM1LjQgMTA5LjY3LC0yMjAuNCAyMDcuNjksLTUwOSAyNzkuOTgsLTc0NS45IDQ2Ljk4LC0xMTAgNjMuNDUsLTIzMS42IDEwNi43NywtMzQzIGwgNi41Myw0LjggYyAzMy44OSwtODEuMyA0Mi4yLC0xOTkuMiA1OC4zMywtMjg2LjcgMzcuNjUsLTIwNC4xIDczLjg5LC00MDguMyAxMTkuNzMsLTYxMC44IDQyLjk3LC0xMjguOSA1NS44LC0yNzcuOCA4Ni40NCwtNDExLjIgMjcuNDgsLTExOS42IDczLjc0LC0yNDEuMyA5Mi40NCwtMzYxLjgiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg0MiIKICAgICAgICAgc3R5bGU9ImZpbGw6I2IzMzQyMjtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA2NDA1Ljc5LDk5NTIuOSBjIC01My41Myw3MyAtODcuODMsMTU1LjggLTExNi41MiwyNDEuMiAtNTYuOTYsMTY5LjUgLTM3NC4zLDEyMzIuMyAtMzI1LjI2LDEzMzAuMSA0LjI5LDAuNSA4LjU4LDEuMSAxMi45MSwxLjQgNDIuMSwyLjkgOTEuNDcsLTIwLjkgMTI5LjIxLC0zOC41IDE1Ny4yNiwtNzMuMyAyMjUuOTgsLTIwMi4xIDMwNS40NCwtMzQ2LjkgMTcuMjksLTMxLjQgMzAuMTIsLTY1LjUgNTguMTcsLTg5LjEgbCAxNC44MywxMC45IGMgNDYuOTgsLTExMCA2My40NSwtMjMxLjYgMTA2Ljc3LC0zNDMgbCA2LjUzLDQuOCBjIDMzLjg5LC04MS4zIDQyLjIsLTE5OS4yIDU4LjMzLC0yODYuNyAzNy42NSwtMjA0LjEgNzMuODksLTQwOC4zIDExOS43MywtNjEwLjggLTE0OS44NSw2Ni44IC0yNDguNjQsMjIwIC00MDIuOTcsMjkzIDYuNTUsLTU2LjMgMjAuMjksLTExMS4yIDMyLjgzLC0xNjYuNCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDQ0IgogICAgICAgICBzdHlsZT0iZmlsbDojNWYxZDJjO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDUxODYuMiwzMDk1LjMgYyAxMTcuMTEsMjEuNCA0NTMuNTQsMTUyLjcgNTcyLjU3LDIwNi44IDIwMC4zOSwtMzQ4LjUgNDA0LjI3LC02OTUgNjExLjY4LC0xMDM5LjMgODMuODMsLTEzOS4zIDE3Mi4wOSwtMzE3LjggMjcwLjAzLC00NDEuOCBsIDAuOCwtNS40IEMgNjU2OC4xNCwxNzg5LjUgNjE2Ny41MSwxNDY4LjUgNjEwNC4wNSwxNDAzLjEgNjM4NC4zNSw5MTQuMzAxIDY3MDkuMjksNDU3LjcwMyA3MDM2LjgzLDAgSCA0MzQyLjc1IDE2NjEuMzQgYyAtNTIuMTUsMTUyLjkwMiAtODkuMDIsMzEzLjIwMyAtMTMyLjUsNDY4LjgwMSBMIDEzNDMuNTcsMTEwNy44IGMgLTI5Ljc5LDEwNC44IC00OC4yOCwyNDguNSAtMTAxLjQ3LDM0MC41IDc1MC4wOCw1MzUuNSAxNjE4LjMsODQ2LjQgMjQ4MS45OCwxMTQ1LjggNDg2LjEyLDE3MC43IDk3My40OSwzMzcuOCAxNDYyLjEyLDUwMS4yIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoNDYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiM2ZjJmMjI7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNTE4Ni4yLDMwOTUuMyBjIDExNy4xMSwyMS40IDQ1My41NCwxNTIuNyA1NzIuNTcsMjA2LjggMjAwLjM5LC0zNDguNSA0MDQuMjcsLTY5NSA2MTEuNjgsLTEwMzkuMyA4My44MywtMTM5LjMgMTcyLjA5LC0zMTcuOCAyNzAuMDMsLTQ0MS44IGwgMC44LC01LjQgYyAtNzMuMTQsLTI2LjEgLTQ3My43NywtMzQ3LjEgLTUzNy4yMywtNDEyLjUgbCAtNS44LC0wLjUgYyAtNDAuNiwxMTUuNCAtMjAyLjA2LDM0NSAtMjczLjYyLDQ3MyAtMjIyLjYxLDM5OC4zIC00NDcuMjMsODA1LjQgLTYzOC40MywxMjE5LjciIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg0OCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2IxMWUyYTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA2MDk4LjI1LDE0MDIuNiA1LjgsMC41IEMgNjM4NC4zNSw5MTQuMzAxIDY3MDkuMjksNDU3LjcwMyA3MDM2LjgzLDAgSCA0MzQyLjc1IGMgMTY3LjAzLDE0Ni40MDIgMzUwLjUzLDI3Ni4wMDQgNTIzLjk1LDQxNC43MDMgTCA2MDk4LjI1LDE0MDIuNiIgLz48ZwogICAgICAgICBpZD0iZzUwIj48ZwogICAgICAgICAgIGNsaXAtcGF0aD0idXJsKCNjbGlwUGF0aDU2KSIKICAgICAgICAgICBpZD0iZzUyIj48ZwogICAgICAgICAgICAgdHJhbnNmb3JtPSJzY2FsZSgxLjAxMjYyKSIKICAgICAgICAgICAgIGlkPSJnNTgiPjxwYXRoCiAgICAgICAgICAgICAgIGlkPSJwYXRoNjYiCiAgICAgICAgICAgICAgIHN0eWxlPSJmaWxsOnVybCgjbGluZWFyR3JhZGllbnQ2NCk7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICAgIGQ9Im0gMTM2MzUsMTYzMDAgYyAyMC4yLC0yNi4xIDQ1LC01Mi45IDYwLjYsLTgxLjkgOTk3LjMsLTEyMDQuNSAxMjA4LjUsLTI5NzEuNiAxMDY2LjgsLTQ0NzguNiAtMTg5LjMsLTIwMTUuNjUgLTEwOTQuOSwtMzcyMy4xIC0yNjU2LjYsLTUwMTMuNDEgLTI3LjUsLTIyLjcxIC01NS4xLC00NC43MyAtODQuMywtNjUuMzcgLTIsNDcuMSAtMC45LDk2Ljk3IC0xMC41LDE0My4wOSBsIC0yLjMsMzkuNiBjIDQuOSw2Ny44NCAtMS4zLDEzNi45NyAtNC43LDIwNC45MSAzNy4zLDY3LjQ1IDExOS44LDEzNy40NyAxNzEuNiwxOTcuMTIgODIuOSw5Ni40OCAxNjEuNCwxOTYuNTIgMjM1LjEsMzAwLjIxIDIzNi4zLDMzMy43OCA0MDEuOSw3MjQuNDUgNTE2LjQsMTExNS41MSAzOC4xLDEyOS43NyA2My41LDI2My4xOCAxMDMsMzkyLjQ1IDMyLjksMTgxLjQxIDg0LDM2OC41NSAxMzUuMyw1NDUuODEgNDkuMiwyMDEuNzUgOTQuNSw0MTEuNDggMTY5LjEsNjA1LjU4IDE3LjUsMTU2IDE0LjgsMzE1LjYgMTYuMiw0NzIuNSAyLjcsMjk4LjYgLTMuMSw1OTggMy4zLDg5Ni40IC0xMi41LDg5LjkgLTYuNCwxOTAuMSAtNi44LDI4MSBsIC0yLjEsNTE4LjUgYyAtMiwzLjYgLTMuNSw3LjcgLTYuMywxMC45IC04Miw5Ny4yIC0xNDIuNCwyMTIuMiAtMjE2LjMsMzE2LjcgLTEzMi4xLDE4NiAtMjcyLjgsMzY1LjMgLTQyMiw1MzggOTMuMiwtNDIuMiAyMDkuOSwtMjIzLjMgMjczLjIsLTMwOC4yIDIxLjUsMjguNyA1Mi40LDYxLjcgNjguMyw5My4zIDM3LDczLjkgLTIzMi45LDIzNi42IC0yNTIuOCwzMTkuNCAtOTQuMiwxMTcuNCAtMjQ0LjMsMjIwLjkgLTM2MC40LDMxNy43IC0zOTMuNCwzMzIgLTgwMCw2NDcuMyAtMTIxOS40LDk0NS43IDYzLjksODAgMzE4LjksMjI2LjQgNDE5LjEsMjk0IGwgNTk1LDQwNy41IGMgNDcyLjIsMzI3LjMgOTMzLjksNjcyLjcgMTQxMS41LDk5MS42IiAvPjwvZz48L2c+PC9nPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoNjgiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNmMGE5NmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTQxNzYuMSwxMzAzNC40IGMgNTYuOCwtOTQuNiAtMTgzLC0xMDc1LjggLTE0MC4xLC0xMjYwLjQgNTIuMiwxOS43IDExMywyNS44IDE2NS40LDIuNCAzMywtMTQuOCA1Mi43LC0zOS4yIDY1LC03Mi44IDgyLjgsLTIyNy43IC0xMzUuMiwtMTI4OS4zIC0yMTYuNSwtMTU2MC40IC0yNSwtODEuMiAtNTMuNSwtMTYxLjMgLTg1LjQsLTI0MC4xIC0zMS44LC03OC44IC02NywtMTU2LjIgLTEwNS40LC0yMzIuMSAtODkuMywtMTc2LjUgLTI0Ny4yLC00NDYuMyAtNDQ2LjIsLTUxMy42IC03NS4xLC0yNS40IC0xNDUuNCwtMTguMiAtMjE4LjMsMTAuNSAzMy4zLDE4My43IDg1LDM3My4yIDEzNyw1NTIuNyA0OS44LDIwNC4zIDk1LjcsNDE2LjcgMTcxLjIsNjEzLjIgMTcuOCwxNTggMTUsMzE5LjcgMTYuNCw0NzguNSAyLjgsMzAyLjQgLTMuMSw2MDUuNSAzLjQsOTA3LjcgMTEuMSw4Ni42IDUuMiwxNzggNC44LDI2NS4zIDI4OS45LDIyOSA1MjkuOCw3MDkuNiA2NDguNywxMDQ5LjEiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg3MCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2NjNTkyZjtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxNDA3OC40LDExNTM4LjggYyAxNS42LC0xMi43IDMwLjksLTMwLjIgNDIuMSwtNDcuMSAxMTUuOCwtMTc0LjUgLTIuMSwtNTg2LjIgLTQ2LjMsLTc3OC4zIGwgLTQuNiwtMjAuMyAtMTAuMSwtNC45IGMgLTIuNCw3LjkgLTUuOCwxOC4zIC03LjYsMjYuNyAtMTEuNCw1NC40IC05LjYsMTE1LjMgLTE1LjMsMTcwLjkgLTE5LjksMTk1IC03Mi4yLDQ3OS4xIDQxLjgsNjUzIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoNzIiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNjYzU5MmY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTM1MDIuOCwxMDMzMy44IGMgNDAuNSwzOC4xIDE0OS42LDY5Ny44IDE3MS43LDgwNy44IDI1LjIsLTgwIDU0LjYsLTE1NC43IDkyLjMsLTIyOS42IDk2LjksLTE5Mi43IDI0Ni40LC0zOTkuNyAxMzQuMiwtNjIwLjEgLTczLC0xNDMuNiAtMjIyLjcsLTIwMS4xIC0zMjguMywtMzEzIC03OS42LC04NC41IC0xMjEuNywtMTkxLjcgLTIxOC4xLC0yNjAuNyBsIC0yMywyLjQgYyA0OS44LDIwNC4zIDk1LjcsNDE2LjcgMTcxLjIsNjEzLjIiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg3NCIKICAgICAgICAgc3R5bGU9ImZpbGw6IzFiMWIxZDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxNDE3Ni4xLDEzMDM0LjQgYyA1Ni44LC05NC42IC0xODMsLTEwNzUuOCAtMTQwLjEsLTEyNjAuNCAtMjIwLjMsLTE0OC43IC0yOTcuMiwtMzg2IC0zNjEuNSwtNjMyLjQgLTIyLjEsLTExMCAtMTMxLjIsLTc2OS43IC0xNzEuNywtODA3LjggMTcuOCwxNTggMTUsMzE5LjcgMTYuNCw0NzguNSAyLjgsMzAyLjQgLTMuMSw2MDUuNSAzLjQsOTA3LjcgMTEuMSw4Ni42IDUuMiwxNzggNC44LDI2NS4zIDI4OS45LDIyOSA1MjkuOCw3MDkuNiA2NDguNywxMDQ5LjEiIC8+PGcKICAgICAgICAgdHJhbnNmb3JtPSJzY2FsZSgxLjAxMjYyKSIKICAgICAgICAgaWQ9Imc3NiI+PHBhdGgKICAgICAgICAgICBpZD0icGF0aDc4IgogICAgICAgICAgIHN0eWxlPSJmaWxsOiMyMTJiMzE7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSAxMzYzNSwxNjMwMCBjIDIwLjIsLTI2LjEgNDUsLTUyLjkgNjAuNiwtODEuOSAwLjYsLTEzIDAuOCwtMjIuOCA1LjQsLTM1LjEgMjQuMSwtNjQuOSA3MS44LC0xMzIuNCAxMDUuNywtMTk0LjEgNjQsLTExNi41IDEyMS40LC0yMzUuOCAxNjcuMSwtMzYwLjggMjk3LjcsLTgxMyAyNDMuNSwtMTkyOC44IDI1LjYsLTI3NTYuMiAtMTE3LjQsLTMzNS4zIC0zNTQuNCwtODA5LjkgLTY0MC42LC0xMDM2IDAuNCwtODYuMiA2LjIsLTE3Ni41IC00LjgsLTI2MiAtMTIuNSw4OS45IC02LjQsMTkwLjEgLTYuOCwyODEgbCAtMi4xLDUxOC41IGMgLTIsMy42IC0zLjUsNy43IC02LjMsMTAuOSAtODIsOTcuMiAtMTQyLjQsMjEyLjIgLTIxNi4zLDMxNi43IC0xMzIuMSwxODYgLTI3Mi44LDM2NS4zIC00MjIsNTM4IDkzLjIsLTQyLjIgMjA5LjksLTIyMy4zIDI3My4yLC0zMDguMiAyMS41LDI4LjcgNTIuNCw2MS43IDY4LjMsOTMuMyAzNyw3My45IC0yMzIuOSwyMzYuNiAtMjUyLjgsMzE5LjQgLTk0LjIsMTE3LjQgLTI0NC4zLDIyMC45IC0zNjAuNCwzMTcuNyAtMzkzLjQsMzMyIC04MDAsNjQ3LjMgLTEyMTkuNCw5NDUuNyA2My45LDgwIDMxOC45LDIyNi40IDQxOS4xLDI5NCBsIDU5NSw0MDcuNSBjIDQ3Mi4yLDMyNy4zIDkzMy45LDY3Mi43IDE0MTEuNSw5OTEuNiIgLz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGg4MCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2YwYTk2YztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMjk1MC42LDEzNTEyIGMgMjA3LjUsLTE3My41IDM2NS43LC0zODcuNiA1NTQuMSwtNTc4LjYgbCA4LjksLTQwMy44IGMgLTIuMSwzLjcgLTMuNiw3LjggLTYuNCwxMSAtODMsOTguNCAtMTQ0LjIsMjE1IC0yMTksMzIwLjcgLTEzMy44LDE4OC40IC0yNzYuMywzNzAgLTQyNy40LDU0NC44IDk0LjQsLTQyLjcgMjEyLjYsLTIyNi4xIDI3Ni43LC0zMTIgMjEuOCwyOSA1Myw2Mi40IDY5LjEsOTQuNCAzNy41LDc0LjggLTIzNS44LDIzOS42IC0yNTYsMzIzLjUiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg4MiIKICAgICAgICAgc3R5bGU9ImZpbGw6Izk0MTkzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA2NjY4LjMyLDUyNDguNCA3NzMuNzMsMS4zIGMgMTM0LjU5LC0wLjIgMjczLjgsNy41IDQwNy40NCwtNS43IGwgMTUuNDgsLTcuOCBjIC00MS40MSwtMjY3LjYgLTg4LjcxLC01MzQuMSAtMTQxLjksLTc5OS42IDMxMS4xMiwtMTg5LjMgNzAzLjcxLC02OTEgOTM3Ljg1LC05NzcuNyAzNjEuMzcsLTQ0MS43IDcyMi4xMSwtODg5LjIgMTA2NC4zMywtMTM0NS45IDEzMC4xMiwtMTczLjYgMjQ0LjYsLTM1OC45IDM3NC45NSwtNTMyLjEgLTE2LjQsLTI3IC0zMy4zLC01MS41IC01MywtNzYuMSAtOTEuODUsLTExNS4xIC0xOTYuNzgsLTIyOS4xIC0yNzkuODUsLTM0OS45IEwgODg1Mi4zNiwwIEggNzg5MS4xIDcwMzYuODMgYyAtMzI3LjU0LDQ1Ny43MDMgLTY1Mi40OCw5MTQuMzAxIC05MzIuNzgsMTQwMy4xIDYzLjQ2LDY1LjQgNDY0LjA5LDM4Ni40IDUzNy4yMyw0MTIuNSBsIC0wLjgsNS40IGMgLTk3Ljk0LDEyNCAtMTg2LjIsMzAyLjUgLTI3MC4wMyw0NDEuOCAtMjA3LjQyLDM0NC4zIC00MTEuMzEsNjkwLjggLTYxMS42OCwxMDM5LjMgNDAuNSwxNDkuNCAxNzQuMjUsMzczLjEgMjQzLjIyLDUyMy41IGwgMzc4LjE4LDgxNCBjIDkzLjIyLDIwMy4xIDE4MC4xNSw0MTMuMSAyODguMTUsNjA4LjgiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg4NCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2RmN2UzYTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA2MTA0LjA1LDE0MDMuMSBjIDYzLjQ2LDY1LjQgNDY0LjA5LDM4Ni40IDUzNy4yMyw0MTIuNSBDIDcwNDEuMTUsMTE5Ny42IDc0MzEuOTksNTc2LjgwMSA3ODkxLjEsMCBoIC04NTQuMjcgYyAtMzI3LjU0LDQ1Ny43MDMgLTY1Mi40OCw5MTQuMzAxIC05MzIuNzgsMTQwMy4xIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoODYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNiMWFiOWQ7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNzIxMi42Miw0NTYzLjMgYyAxNDEuODcsMjguOSAzNDYuNzEsLTcuNSA0NjMuNywtMTAwLjkgMi45MiwtMi4zIDUuMjIsLTUuNCA3LjgzLC04LjEgbCAzOC45MiwtMTcuNyBjIDMxMS4xMiwtMTg5LjMgNzAzLjcxLC02OTEgOTM3Ljg1LC05NzcuNyAzNjEuMzcsLTQ0MS43IDcyMi4xMSwtODg5LjIgMTA2NC4zMywtMTM0NS45IDEzMC4xMiwtMTczLjYgMjQ0LjYsLTM1OC45IDM3NC45NSwtNTMyLjEgLTE2LjQsLTI3IC0zMy4zLC01MS41IC01MywtNzYuMSAtOTEuODUsLTExNS4xIC0xOTYuNzgsLTIyOS4xIC0yNzkuODUsLTM0OS45IC0zMTUuODgsNDE1LjQgLTYxOS42LDg0MS43IC05MzEuNjMsMTI2MC4zIC0xODYuNDQsMjUwLjEgLTM5Mi40Myw0OTMuNiAtNTY2LjM4LDc1MS45IGwgLTYsMS4zIGMgLTc5LjU0LDEzNy41IC0xOTguNzEsMjcwLjUgLTI5Ni4wOCwzOTYuOCAtMTc4LjA3LDIyOS4xIC0zNTQuMjYsNDU5LjUgLTUyOC41Nyw2OTEuNSAtNzEuNSw5NCAtMTc0LjYxLDIwMS44IC0yMjYuMDcsMzA2LjYiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg4OCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2VmZWNlNztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA3Njg0LjE1LDQ0NTQuMyAzOC45MiwtMTcuNyBjIDMxMS4xMiwtMTg5LjMgNzAzLjcxLC02OTEgOTM3Ljg1LC05NzcuNyAzNjEuMzcsLTQ0MS43IDcyMi4xMSwtODg5LjIgMTA2NC4zMywtMTM0NS45IDEzMC4xMiwtMTczLjYgMjQ0LjYsLTM1OC45IDM3NC45NSwtNTMyLjEgLTE2LjQsLTI3IC0zMy4zLC01MS41IC01MywtNzYuMSAtMjgzLjAxLDQ0Mi44IC02MTAuODQsODU2LjMgLTkzNC43MiwxMjY5LjUgLTE2Ny45NiwyMTQuMyAtMzI5Ljg4LDQ0Mi44IC01MTcsNjQwLjYgLTE4MS42NSwyMTkuMyAtMzYxLjY2LDQ0MS44IC01NTMuMzMsNjUyLjUgLTU5LjY0LDY1LjYgLTM1MS4yNSwzMzQuMyAtMzU4LDM4Ni45IiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoOTAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNhMzk0OGI7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNzIxMi42Miw0NTYzLjMgYyAxNDEuODcsMjguOSAzNDYuNzEsLTcuNSA0NjMuNywtMTAwLjkgMi45MiwtMi4zIDUuMjIsLTUuNCA3LjgzLC04LjEgNi43NSwtNTIuNiAyOTguMzYsLTMyMS4zIDM1OCwtMzg2LjkgMTkxLjY3LC0yMTAuNyAzNzEuNjgsLTQzMy4yIDU1My4zMywtNjUyLjUgLTk5LjIyLC05MiAtMjMyLjYxLC0xNTMuNCAtMzI2LjE0LC0yNDcuOCBsIC02LDEuMyBjIC03OS41NCwxMzcuNSAtMTk4LjcxLDI3MC41IC0yOTYuMDgsMzk2LjggLTE3OC4wNywyMjkuMSAtMzU0LjI2LDQ1OS41IC01MjguNTcsNjkxLjUgLTcxLjUsOTQgLTE3NC42MSwyMDEuOCAtMjI2LjA3LDMwNi42IiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoOTIiCiAgICAgICAgIHN0eWxlPSJmaWxsOiM1ZjFkMmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNjY2OC4zMiw1MjQ4LjQgNzczLjczLDEuMyBjIDEzNC41OSwtMC4yIDI3My44LDcuNSA0MDcuNDQsLTUuNyBsIDE1LjQ4LC03LjggYyAtNDEuNDEsLTI2Ny42IC04OC43MSwtNTM0LjEgLTE0MS45LC03OTkuNiBsIC0zOC45MiwxNy43IGMgLTIuNjEsMi43IC00LjkxLDUuOCAtNy44Myw4LjEgLTExNi45OSw5My40IC0zMjEuODMsMTI5LjggLTQ2My43LDEwMC45IDUxLjQ2LC0xMDQuOCAxNTQuNTcsLTIxMi42IDIyNi4wNywtMzA2LjYgMTc0LjMxLC0yMzIgMzUwLjUsLTQ2Mi40IDUyOC41NywtNjkxLjUgOTcuMzcsLTEyNi4zIDIxNi41NCwtMjU5LjMgMjk2LjA4LC0zOTYuOCAtMjU3LjE1LC0yMTkuOSAtNTIwLjg4LC00MzIuNiAtNzgwLjIsLTY1MCAtMjc4LjY3LC0yMzMuNyAtNTU1LjY5LC00NzQgLTg0Mi42NiwtNjk3LjQgLTk3Ljk0LDEyNCAtMTg2LjIsMzAyLjUgLTI3MC4wMyw0NDEuOCAtMjA3LjQyLDM0NC4zIC00MTEuMzEsNjkwLjggLTYxMS42OCwxMDM5LjMgNDAuNSwxNDkuNCAxNzQuMjUsMzczLjEgMjQzLjIyLDUyMy41IGwgMzc4LjE4LDgxNCBjIDkzLjIyLDIwMy4xIDE4MC4xNSw0MTMuMSAyODguMTUsNjA4LjgiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg5NCIKICAgICAgICAgc3R5bGU9ImZpbGw6IzQ3MjAyODtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA3ODQ5LjQ5LDUyNDQgMTUuNDgsLTcuOCBjIC00MS40MSwtMjY3LjYgLTg4LjcxLC01MzQuMSAtMTQxLjksLTc5OS42IGwgLTM4LjkyLDE3LjcgYyAtMi42MSwyLjcgLTQuOTEsNS44IC03LjgzLDguMSAtMTE2Ljk5LDkzLjQgLTMyMS44MywxMjkuOCAtNDYzLjcsMTAwLjkgLTI4LjUxLDE3LjggLTQ2MS45OSw1OTAuMiAtNTMyLjkyLDY3Ni43IGwgNzM3Ljk0LC0xIGMgMTQzLjI5LC0wLjEgMjg4Ljk5LC01LjEgNDMxLjg1LDUiIC8+PGcKICAgICAgICAgaWQ9Imc5NiI+PGcKICAgICAgICAgICBjbGlwLXBhdGg9InVybCgjY2xpcFBhdGgxMDIpIgogICAgICAgICAgIGlkPSJnOTgiPjxwYXRoCiAgICAgICAgICAgICBpZD0icGF0aDExMCIKICAgICAgICAgICAgIHN0eWxlPSJmaWxsOnVybCgjbGluZWFyR3JhZGllbnQxMDgpO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgICAgZD0ibSAxMDkxNy45LDYwOTkuMyBjIDQ4My42LDI1My42IDg2OCw2NDUgMTIzNy42LDEwMzggMy41LC02OC44IDkuOCwtMTM4LjggNC44LC0yMDcuNSBsIDIuMywtNDAuMSBjIC0zLC0xOTMuMiAyNS42LC0zOTIuMSA0Mi43LC01ODQuNiAzMS42LC0zNTQgNjAuMSwtNzEzLjQgMTIxLjksLTEwNjMuNyA0MS44LC0yNTkgODUuNSwtNTE3LjYgMTMxLjEsLTc3NiA0LjcsLTIxLjcgOS44LC00My4zIDEzLjIsLTY1LjIgLTU4LjUsLTgxLjEgLTIyMy4xLC0xODguMSAtMzAzLjcsLTI2OC45IC0xODguNSwtMTg4LjkgLTM1OS44LC00MDMuMiAtNTM0LjUsLTYwNS4zIC0zOTMuMiwtNDU0LjcgLTc2OSwtOTMxLjggLTExMzMuNywtMTQwOS43IC0xMzUuMSwtMTc3IC0yNjIuNiwtMzU5LjggLTM5OS40LC01MzUuNCAtMTMwLjM1LDE3My4yIC0yNDQuODMsMzU4LjUgLTM3NC45NSw1MzIuMSAtMzQyLjIyLDQ1Ni43IC03MDIuOTYsOTA0LjIgLTEwNjQuMzMsMTM0NS45IC0yMzQuMTQsMjg2LjcgLTYyNi43Myw3ODguNCAtOTM3Ljg1LDk3Ny43IDUzLjE5LDI2NS41IDEwMC40OSw1MzIgMTQxLjksNzk5LjYgMzAuODIsMTA1IDMyLjU3LDI2NS4zIDQ0Ljc5LDM3Ni43IDM5LjY1LDM2MS45IDgyLjk4LDcyOC4xIDk3Ljk0LDEwOTIuMSAxLjcyLDEwMC45IDAuOSwyMDIgMS4xMSwzMDIuOSA1NzYuMiwtNTcyLjUgMTE3Mi4wNCwtMTE1NCAyMDQyLjI5LC0xMTUwLjMgMjc3LjQsMS4xIDY0NC45LDYwLjkgODY2LjgsMjQxLjciIC8+PC9nPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDExMiIKICAgICAgICAgc3R5bGU9ImZpbGw6I2ZjZDRhODtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMjE2MC4zLDY5MjkuOCAyLjMsLTQwLjEgYyAtMywtMTkzLjIgMjUuNiwtMzkyLjEgNDIuNywtNTg0LjYgMzEuNiwtMzU0IDYwLjEsLTcxMy40IDEyMS45LC0xMDYzLjcgNDEuOCwtMjU5IDg1LjUsLTUxNy42IDEzMS4xLC03NzYgLTk4LjksNDguOCAtMTIwLjEsMzM0IC0xNDEuMSw0MzIuOCAtMjYuOCwxMjYgLTc4LjIsMjQzLjkgLTEwMS43LDM3MS42IC0zNS43LDE5My4yIC00My40LDM4Ny42IC03MS42LDU4MS4yIC0xNSwxMDIuOCAtNDUuMywyMDYuMiAtNzEsMzA2LjkgLTE4LjMsNzEuNyAtMzQuMiwxNTQgLTY1LjksMjIwLjcgLTM0LDcxLjQgLTEwNC44LDkyLjYgLTE1Mi4yLDE1MSAtMi45LDMuNiAtNS43LDcuMyAtOC41LDExIGwgMzE0LDM4OS4yIiAvPjxnCiAgICAgICAgIGlkPSJnMTE0Ij48ZwogICAgICAgICAgIGNsaXAtcGF0aD0idXJsKCNjbGlwUGF0aDEyMCkiCiAgICAgICAgICAgaWQ9ImcxMTYiPjxwYXRoCiAgICAgICAgICAgICBpZD0icGF0aDEyOCIKICAgICAgICAgICAgIHN0eWxlPSJmaWxsOnVybCgjbGluZWFyR3JhZGllbnQxMjYpO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgICAgZD0ibSAxMDkxNy45LDYwOTkuMyBjIDQ4My42LDI1My42IDg2OCw2NDUgMTIzNy42LDEwMzggMy41LC02OC44IDkuOCwtMTM4LjggNC44LC0yMDcuNSBsIC0zMTQsLTM4OS4yIGMgLTE1MSwtMTY4LjMgLTMwMC4zLC0zMzkuNiAtNDU3LC01MDIuNSAtNTgwLjIsLTYwMy40IC0xMjA0LjksLTExNzIuNCAtMTgyMC42NiwtMTczOS40IC0xNzcuODYsLTE2Mi4yIC0zNTQuNDcsLTMyNS43IC01MjkuODMsLTQ5MC42IC0xMjMuNzUsLTExNi43IC0yNDYuMzQsLTI0MS43IC0zNzcuODksLTM0OS4yIC0yMzQuMTQsMjg2LjcgLTYyNi43Myw3ODguNCAtOTM3Ljg1LDk3Ny43IDUzLjE5LDI2NS41IDEwMC40OSw1MzIgMTQxLjksNzk5LjYgMzAuODIsMTA1IDMyLjU3LDI2NS4zIDQ0Ljc5LDM3Ni43IDM5LjY1LDM2MS45IDgyLjk4LDcyOC4xIDk3Ljk0LDEwOTIuMSAxLjcyLDEwMC45IDAuOSwyMDIgMS4xMSwzMDIuOSA1NzYuMiwtNTcyLjUgMTE3Mi4wNCwtMTE1NCAyMDQyLjI5LC0xMTUwLjMgMjc3LjQsMS4xIDY0NC45LDYwLjkgODY2LjgsMjQxLjciIC8+PC9nPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDEzMCIKICAgICAgICAgc3R5bGU9ImZpbGw6Izk0MTkzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMzQxMS42LDUyMDAgYyAyMDEuMiwtNDYwLjggNDM0LjIsLTkxMS41IDY1Ni40LC0xMzYyLjYgNTguMywtMTE4LjYgMTg2LjEsLTQzMi4yIDI2NC4zLC01MTQuNCA3NS4zLC0xNy4xIDQ0My41LC0xNDQuNyA0ODUuMywtMTg2LjQgQyAxNDQ3OC4zLDIyOTcuMSAxNDA4MCwxNjA4LjkgMTM1NzguNyw4NTkuMTAyIDEzMzgyLjksNTY2LjE5OSAxMzE4NS44LDI3NS44MDEgMTI5NjYuMiwwIGggLTc3My44IC0yNzM2LjQ2IC02MDMuNTggbCA5MTQuOTksMTE1NC45IGMgODMuMDcsMTIwLjggMTg4LDIzNC44IDI3OS44NSwzNDkuOSAxOS43LDI0LjYgMzYuNiw0OS4xIDUzLDc2LjEgMTM2LjgsMTc1LjYgMjY0LjMsMzU4LjQgMzk5LjQsNTM1LjQgMzY0LjcsNDc3LjkgNzQwLjUsOTU1IDExMzMuNywxNDA5LjcgMTc0LjcsMjAyLjEgMzQ2LDQxNi40IDUzNC41LDYwNS4zIDgwLjYsODAuOCAyNDUuMiwxODcuOCAzMDMuNywyNjguOSAxMzEuOCw0My4zIDE1My4zLDE2MS45IDM3OC4xLDE5My4yIDMxLjcsOS40IDcyLjksMy43IDEwNi4xLDMuMSAxMzQuNiwyMTIgMzI4LjMsMzg4LjQgNDU1LjksNjAzLjUiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxMzIiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNkZjdlM2E7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTQzMzIuMywzMzIzIGMgNzUuMywtMTcuMSA0NDMuNSwtMTQ0LjcgNDg1LjMsLTE4Ni40IEMgMTQ0NzguMywyMjk3LjEgMTQwODAsMTYwOC45IDEzNTc4LjcsODU5LjEwMiAxMzM4Mi45LDU2Ni4xOTkgMTMxODUuOCwyNzUuODAxIDEyOTY2LjIsMCBoIC03NzMuOCBjIDM4Ny4yLDQ4OS4zMDEgNzQ2LjUsMTAwNi40IDEwOTQuOSwxNTIzLjcgMjQ3LjEsMzYwIDQ3OSw3MjkuNCA2OTUuNiwxMTA4LjUgMTI2LjUsMjIxLjggMjU1LjMsNDUzIDM0OS40LDY5MC44IiAvPjxnCiAgICAgICAgIGlkPSJnMTM0Ij48ZwogICAgICAgICAgIGNsaXAtcGF0aD0idXJsKCNjbGlwUGF0aDE0MCkiCiAgICAgICAgICAgaWQ9ImcxMzYiPjxwYXRoCiAgICAgICAgICAgICBpZD0icGF0aDE0OCIKICAgICAgICAgICAgIHN0eWxlPSJmaWxsOnVybCgjbGluZWFyR3JhZGllbnQxNDYpO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgICAgZD0ibSAxMjg0OS42LDQ1OTMuNCBjIDI2LjksLTEuOCA2Mi44LDAuMSA4Ni40LC0xMi4zIC0zOC44LC04NS40IC0xNTIuMiwtMjAyLjIgLTIxMi43LC0yODEuMiAtMjE3LjYsLTI4OCAtNDM3LjcsLTU3NCAtNjYwLjIsLTg1OC4xIEwgMTA0MzMuOSwxMjk4LjEgQyAxMDEwNy4zLDg2Ny41IDk3NjUuMzEsNDQyLjgwMSA5NDU1Ljk0LDAgaCAtNjAzLjU4IGwgOTE0Ljk5LDExNTQuOSBjIDgzLjA3LDEyMC44IDE4OCwyMzQuOCAyNzkuODUsMzQ5LjkgMTkuNywyNC42IDM2LjYsNDkuMSA1Myw3Ni4xIDEzNi44LDE3NS42IDI2NC4zLDM1OC40IDM5OS40LDUzNS40IDM2NC43LDQ3Ny45IDc0MC41LDk1NSAxMTMzLjcsMTQwOS43IDE3NC43LDIwMi4xIDM0Niw0MTYuNCA1MzQuNSw2MDUuMyA4MC42LDgwLjggMjQ1LjIsMTg3LjggMzAzLjcsMjY4LjkgMTMxLjgsNDMuMyAxNTMuMywxNjEuOSAzNzguMSwxOTMuMiIgLz48L2c+PC9nPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4xNjQ0NCkiCiAgICAgICAgIGlkPSJnMTUwIj48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMTUyIgogICAgICAgICAgIHN0eWxlPSJmaWxsOiMxYTNkNDc7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSA4MTg4LjI3LDE2MTk0LjQgYyA0MDEuNTYsMTA1LjYgNzY2LjEyLDU4LjMgMTEyNS42OSwtMTUxLjEgMzYuNzUsLTIxLjQgNzMuMDgsLTQzLjUgMTA5LjE1LC02Ni4yIDEyOC4zLC0xMDYuNCAyMzAuNTgsLTIyNy40IDMwMS42MSwtMzc5LjcgMjMyLjM4LC02Mi43IDQ1MC42OCwtMTQ5LjEgNjY4LjE4LC0yNTEuNyA2OC4xLC0zMiAxMzcuMiwtOTAuOSAyMDYuNywtMTEzLjIgODcuNCwtNzQuMSAyMTEuMywtMTIyLjggMzA3LjEsLTE4OC4zIDMzNy40LC0yMzAuNiA3MDguNCwtNTM4LjIgOTUwLjYsLTg2OS4zIC00MTUuMywtMjc3LjMgLTgxNi44LC01NzcuNyAtMTIyNy40LC04NjIuMyBsIC01MTcuNCwtMzU0LjQgYyAtODcuMiwtNTguNyAtMzA4Ljk1LC0xODYuMSAtMzY0LjUxLC0yNTUuNyAtNjUuNDQsMzYuOCAtMTI4Ljk5LDkwLjYgLTE4OS41NCwxMzUgLTE2Ny4zNywxMjIuOCAtMzI5LjY4LDI1MiAtNDk1LjY5LDM3Ni42IC0xMzQuMzEsMTAwLjggLTI4MC4xMywxODMuOCAtNDE1LjY1LDI4Mi4zIC0zNzQuOTgsLTE4NS4zIC02NzIuMDIsLTM4Ny40IC0xMDI0Ljg5LC01OTkuOCAtMTMzLjM0LC04OS4yIC0zNjYuNTYsLTI2MyAtNTAwLjcyLC0zMjcuNyAtNDguNzIsNDMuOCAtMTEyLjQsODEuMyAtMTY2LjA4LDExOS4xIGwgLTQyMy44NywyOTMuMyBjIC0zNDIuNzUsMjQyLjQgLTY3OS4xNSw0OTMuMyAtMTAwOS4yLDc1Mi42IC05NS45Myw3NSAtMjM0LjU1LDE1NS42IC0zMDkuNjcsMjUwIDEyNC4zNywxNzguNiAyNzIuMzgsMzM2LjcgNDIwLjAzLDQ5NS44IDI5Ny43OCwzMTcuNCA2NzkuMTksNTgwLjkgMTA2Ni42Niw3NzYuMiAtMzEuMzUsMjE0IDQyLjg2LDQyNC44IDE2NS42Niw1OTkgODAuNTUsMTE0LjMgMTY1LjczLDE4My45IDMwNi4xOCwyMDcuOSBsIDE1LjQ5LC0xLjkgYyA1My4wOSwtNi4xIDEwNy41NywtMy4xIDE2MS4wMSwtNy4yIDE0My40OCwtMTEuMSAzMDAuMDIsLTMwLjMgNDM4LjYyLC02OS41IDEyOS4yOCw4My41IDI1Ny43MSwxNTUuMiA0MDEuOTQsMjEwLjIiIC8+PC9nPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4xNTY4OSkiCiAgICAgICAgIGlkPSJnMTU0Ij48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMTU2IgogICAgICAgICAgIHN0eWxlPSJmaWxsOiM1ZjFkMmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSA3ODM3LjEsMTYwODguNCBjIDEzMC4xMiw4NCAyNTkuMzksMTU2LjMgNDA0LjU2LDIxMS42IDE0MC45OSwtMTI0LjIgMjUzLjQzLC0yOTUgMzcwLjIyLC00NDIuNCAtMTIwLjM3LC0xLjkgLTI0MC4zMSwtMTAgLTM1OS44MywtMjQuNCAtMTE5LjUxLC0xNC41IC0yMzcuOTUsLTM1IC0zNTUuMzIsLTYxLjggLTEyMy44NywtMjguMSAtMjQ3LjYxLC02NS43IC0zNzIuMDgsLTg5LjcgNjkuMTYsMTY2LjMgMTY5LjExLDI5NyAzMTIuNDUsNDA2LjciIC8+PC9nPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4xNDc0OSkiCiAgICAgICAgIGlkPSJnMTU4Ij48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMTYwIgogICAgICAgICAgIHN0eWxlPSJmaWxsOiMxYjFiMWQ7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSA3Mjc3LjEsMTYzMDAgMTUuNzIsLTEuOSBjIDUzLjg3LC02LjIgMTA5LjE1LC0zLjEgMTYzLjM4LC03LjMgMTQ1LjYsLTExLjMgMzA0LjQ1LC0zMC44IDQ0NS4xMSwtNzAuNiAtMTQ0LjUyLC0xMTAuNiAtMjQ1LjI5LC0yNDIuMyAtMzE1LjAyLC00MTAgLTkzLjQzLC0zOS4zIC0xOTMuNTUsLTY0LjIgLTI4OS40NywtOTcgLTE2Ni44NywtNTcuMiAtMzQ4Ljk5LC0xMzcuOCAtNDk4LjUzLC0yMzIgLTMxLjgxLDIxNy4xIDQzLjUsNDMxIDE2OC4xMSw2MDcuOCA4MS43NCwxMTYgMTY4LjE3LDE4Ni42IDMxMC43LDIxMSIgLz48L2c+PGcKICAgICAgICAgdHJhbnNmb3JtPSJzY2FsZSgxLjE2NDQ0KSIKICAgICAgICAgaWQ9ImcxNjIiPjxwYXRoCiAgICAgICAgICAgaWQ9InBhdGgxNjQiCiAgICAgICAgICAgc3R5bGU9ImZpbGw6I2EyMWMzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICBkPSJtIDgxODguMjcsMTYxOTQuNCBjIDQwMS41NiwxMDUuNiA3NjYuMTIsNTguMyAxMTI1LjY5LC0xNTEuMSAzNi43NSwtMjEuNCA3My4wOCwtNDMuNSAxMDkuMTUsLTY2LjIgMTI4LjMsLTEwNi40IDIzMC41OCwtMjI3LjQgMzAxLjYxLC0zNzkuNyAtMTQ2LDE5LjkgLTI4OS4zMyw2Ny40IC00MzQuNzIsOTQgLTI0NC4xNSw0NC41IC00ODYuNSw1NC44IC03MzMuOTEsNjMuNSAtMTE2LjAzLDE0Ni40IC0yMjcuNzUsMzE2LjEgLTM2Ny44Miw0MzkuNSIgLz48L2c+PGcKICAgICAgICAgdHJhbnNmb3JtPSJzY2FsZSgxLjAzNDQpIgogICAgICAgICBpZD0iZzE2NiI+PHBhdGgKICAgICAgICAgICBpZD0icGF0aDE2OCIKICAgICAgICAgICBzdHlsZT0iZmlsbDojMjEyYjMxO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgIGQ9Im0gNjM0MC44MiwxNjMwMCBjIDIwNy41MiwtMjYzIDQ4NC44MywtNDcxLjEgNzQ1LjU3LC02NzguOSA0ODcuNjUsLTM4MS44IDk4NS42NiwtNzQ5LjYgMTQ5NC4wNiwtMTEwMy4yIC0xNTAuMSwtMTAwLjQgLTQxMi42NSwtMjk2IC01NjMuNjgsLTM2OC45IC01NC44NCw0OS4zIC0xMjYuNTIsOTEuNSAtMTg2Ljk1LDEzNC4xIGwgLTQ3Ny4xNiwzMzAuMiBjIC0zODUuODMsMjcyLjggLTc2NC41Myw1NTUuMiAtMTEzNi4wNyw4NDcuMiAtMTA3Ljk5LDg0LjQgLTI2NC4wNCwxNzUuMiAtMzQ4LjYsMjgxLjQgMTQwLjAxLDIwMSAzMDYuNjMsMzc5IDQ3Mi44Myw1NTguMSIgLz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxNzAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNmY2Q0YTg7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTAwNjksMTU3MTUuNyBjIDE1Ny44LC0xMTQuNyAzMjcuNiwtMjExLjQgNDg0LC0zMjguOCAxOTMuMywtMTQ1IDM4Mi4zLC0yOTUuNSA1NzcuMiwtNDM4LjUgNzAuNSwtNTEuNyAxNDQuNSwtMTE0LjMgMjIwLjcsLTE1Ny4xIDQyNC43LC0zMDIuMiA4MzYuNCwtNjIxLjQgMTIzNC44LC05NTcuNiAxMTcuNiwtOTguMSAyNjkuNiwtMjAyLjggMzY0LjksLTMyMS43IDIwLjIsLTgzLjkgMjkzLjUsLTI0OC43IDI1NiwtMzIzLjUgLTE2LjEsLTMyIC00Ny4zLC02NS40IC02OS4xLC05NC40IC02NC4xLDg1LjkgLTE4Mi4zLDI2OS4zIC0yNzYuNywzMTIgMTUxLjEsLTE3NC44IDI5My42LC0zNTYuNCA0MjcuNCwtNTQ0LjggNzQuOCwtMTA1LjcgMTM2LC0yMjIuMyAyMTksLTMyMC43IDIuOCwtMy4yIDQuMywtNy4zIDYuNCwtMTEgbCAyLjEsLTUyNS4xIGMgMC40LC05MiAtNS44LC0xOTMuNSA2LjksLTI4NC41IC02LjUsLTMwMi4yIC0wLjYsLTYwNS4zIC0zLjQsLTkwNy43IC0xLjQsLTE1OC44IDEuNCwtMzIwLjUgLTE2LjQsLTQ3OC41IC03NS41LC0xOTYuNSAtMTIxLjQsLTQwOC45IC0xNzEuMiwtNjEzLjIgLTUyLC0xNzkuNSAtMTAzLjcsLTM2OSAtMTM3LC01NTIuNyAtNDAsLTEzMC45IC02NS43LC0yNjYgLTEwNC4zLC0zOTcuNCAtMTE2LC0zOTYgLTI4My42LC03OTEuNiAtNTIyLjksLTExMjkuNiAtNzQuNywtMTA1IC0xNTQuMSwtMjA2LjMgLTIzOC4xLC0zMDQgLTUyLjQsLTYwLjQgLTEzNiwtMTMxLjMgLTE3My44LC0xOTkuNiAtMzY5LjYsLTM5MyAtNzU0LC03ODQuNCAtMTIzNy42LC0xMDM4IC0yMjEuOSwtMTgwLjggLTU4OS40LC0yNDAuNiAtODY2LjgsLTI0MS43IC04NzAuMjUsLTMuNyAtMTQ2Ni4wOSw1NzcuOCAtMjA0Mi4yOSwxMTUwLjMgLTk1LjMzLDEwNi43IC0xOTQuMjMsMjA3LjQgLTI4My42MywzMTkuNiAtNDA3Ljg5LDUxMi4zIC02MzAuNjIsMTA5MS40IC03NzAuMzcsMTcyNS44IC0xOC43LDEyMC41IC02NC45NiwyNDIuMiAtOTIuNDQsMzYxLjggLTMwLjY0LDEzMy40IC00My40NywyODIuMyAtODYuNDQsNDExLjIgLTQ1Ljg0LDIwMi41IC04Mi4wOCw0MDYuNyAtMTE5LjczLDYxMC44IC0xNi4xMyw4Ny41IC0yNC40NCwyMDUuNCAtNTguMzMsMjg2LjcgLTkuNDksODQuNiAtMjAuNzIsMTY5IC0yOC4zMiwyNTMuOSAtNDQuNjksNDk5LjcgLTkzLjQ5LDE1ODYgNzQuMDEsMjA0NiA3MS4wNiwxOTUuMiAxOTYuNjIsMzYyLjEgMzI4LjczLDUxOS45IDMzMC4yNSw0NTQuOSA4NTguNzEsNzg1LjcgMTMyMC4yMywxMDkyLjEgMTU2LjIyLDc1LjQgNDI3LjgsMjc3LjcgNTgzLjA2LDM4MS41IDQxMC45LDI0Ny40IDc1Ni43OCw0ODIuNyAxMTkzLjQyLDY5OC41IiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTcyIgogICAgICAgICBzdHlsZT0iZmlsbDojZGY3ZTNhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDExMDgxLjQsMTExODguMiBjIDI0LjEsMTEuOSA0NC4xLDI4LjYgNjUuNSw0NC44IDczLjEsLTc1IDE2My41LC0xNjcuNiAyNTguOCwtMjEzLjIgLTk2LjEsNC4zIC0yNDQuNywxMTYuNiAtMzI0LjMsMTY4LjQiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxNzQiCiAgICAgICAgIHN0eWxlPSJmaWxsOiMxYjFiMWQ7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTI3OTUuMiwxMjcwMC43IGMgMTA5LjYsLTgzLjEgMjA4LC0xNzEuMiAyODQuNCwtMjg2LjggbCAtMC42LC0xMy45IGMgLTEwNC43LDEwMi4yIC0xOTAuMiwxODIuNSAtMzI0LjYsMjQ1LjkgMTguMSwxNyAyOCwzNCA0MC44LDU0LjgiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxNzYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNiMTFlMmE7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTI0MzQuMiwxMTQzNi44IGMgMjEuOSwtNi45IDQzLjIsLTE0LjMgNjYuMiwtMTYuNyAtMTI3LjMsLTIwOS40IC0zNDEuMywtMzkwLjIgLTU4Mi41LC00NTMuOSAtMTcuMywtNC42IC0zNC41LC03IC01Mi40LC01LjcgMjQzLjgsODEuOSA0MzcuMiwyNTguOCA1NjguNyw0NzYuMyIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDE3OCIKICAgICAgICAgc3R5bGU9ImZpbGw6IzFhM2Q0NztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA4OTkwLjU2LDEyNjA5LjQgYyAxMDEuNTQsLTM4IDE2NS4zNiwtNzIuNyAyMTQsLTE3NS42IDI1LjA4LC01My4xIDQ0LjExLC0xMTAuMSA2NC4xNywtMTY1LjMgLTQ4LjAxLC0xNC4zIC0yNjQuNDUsNTYuOSAtMzIwLjQsNzUuNCAtNC43NSw5MS4xIDcxLjgyLDE3MS43IDQyLjIzLDI2NS41IiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTgwIgogICAgICAgICBzdHlsZT0iZmlsbDojZWZlY2U3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDEwMTU1LjMsMTAzNDEuMyBjIDMuOCwtNS4yIDguNiwtOS44IDExLjYsLTE1LjUgMjUuNiwtNDguNiAxNTksLTY4Ni4zIDE1OC44LC03NDkuOCAtMC4xLC00MS4yIC0xOS4xLC03Ni43IC0zNi44LC0xMTIuOSAtNS40LC0zLjMgLTExLjgsLTcuNiAtMTgsLTkuMiAtMjEuNiwtNS40IC00MC40LDAgLTU3LjcsMTQuMiAtMTI3LDEwNC43IC02Ni4zLDcwNi41IC01Ny45LDg3My4yIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTgyIgogICAgICAgICBzdHlsZT0iZmlsbDojYjExZTJhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDg5NjUuNCw3Nzg3LjggYyAxNzAuNjksMTA1LjIgNTc3LjkyLDMzMS4zIDc2Mi41MywzNjQuNCAxNy4xMSwtOTQuNSAzMC41LC0xNjEuOCA5Ny42NSwtMjM1LjEgLTQ5LjYsMi43IC05OS4yMywzLjEgLTE0OC44NywxLjEgLTQ5LjYzLC0yIC05OS4wNywtNi4zIC0xNDguMzEsLTEyLjkgLTQ5LjIzLC02LjYgLTk4LjA1LC0xNS41IC0xNDYuNDcsLTI2LjYgLTQ4LjQsLTExLjIgLTk2LjE3LC0yNC42IC0xNDMuMzMsLTQwLjIgLTM3LjUsLTEyLjYgLTY4Ljk4LC0zNS4xIC0xMDcuMjgsLTQ3LjEgLTU1LjI5LDIuMiAtMTEwLjM0LC01LjcgLTE2NS45MiwtMy42IiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTg0IgogICAgICAgICBzdHlsZT0iZmlsbDojZjAzYjRhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDk3MjcuOTMsODE1Mi4yIGMgMTE3LjcyLC00Mi4yIDIwOC40OSwtODMuOSAzMzYuMDcsLTUzLjEgNzguOCwyNC4zIDE1MCw1Mi4zIDIzMy42LDQxLjggLTMwLjQsLTMzLjYgLTI1LjYsLTk0LjYgLTUwLjUsLTEzNy41IC0yNiwtMzggLTUyLjYsLTc1LjggLTc5LjYsLTExMy4xIC0xMjEuMSwtMzIuNCAtMjI3LjMsLTE3LjEgLTM0MS45MiwyNi44IC02Ny4xNSw3My4zIC04MC41NCwxNDAuNiAtOTcuNjUsMjM1LjEiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxODYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNkZDFlMjY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTAyOTcuNiw4MTQwLjkgYyAxMzcuMiwtMzguMSAyNjkuMSwtMTIyLjYgMzk0LjksLTE4OC4yIDExMi43LC01OCAyMjYuOSwtMTEzLjEgMzQyLjUsLTE2NS4yIC02My4yLC0xMS41IC0xNjMuOSwxNS45IC0yMjkuNiwyMy4yIC0xOTcuMiw0OC45IC00MzQuNCw5Ny42IC02MzcuOSw3OS42IDI3LDM3LjMgNTMuNiw3NS4xIDc5LjYsMTEzLjEgMjQuOSw0Mi45IDIwLjEsMTAzLjkgNTAuNSwxMzcuNSIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDE4OCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2EyMWMzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA5MTMxLjMyLDc3OTEuNCBjIDM4LjMsMTIgNjkuNzgsMzQuNSAxMDcuMjgsNDcuMSA0Ny4xNiwxNS42IDk0LjkzLDI5IDE0My4zMyw0MC4yIDQ4LjQyLDExLjEgOTcuMjQsMjAgMTQ2LjQ3LDI2LjYgNDkuMjQsNi42IDk4LjY4LDEwLjkgMTQ4LjMxLDEyLjkgNDkuNjQsMS45IDk5LjI3LDEuNiAxNDguODcsLTEuMSAxMTQuNjIsLTQzLjkgMjIwLjgyLC01OS4yIDM0MS45MiwtMjYuOCAyMDMuNSwxOCA0NDAuNywtMzAuNyA2MzcuOSwtNzkuNiAtMTUyLjIsLTk1LjYgLTE0MzMuMTEsLTI2LjEgLTE2NzQuMDgsLTE5LjMiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxOTAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiM5NDE5MzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTA4MDUuNCw3ODEwLjcgYyA2NS43LC03LjMgMTY2LjQsLTM0LjcgMjI5LjYsLTIzLjIgMjUuNSwtOC4zIDYzLjYsLTE0LjIgNzguNywtMzUuOCAtMTguMSwtMTAuNSAtMzUuNiwtMTguMSAtNTUuMSwtMjUuNSAtNTMwLjcsLTEwNS43IC0xMjI1LjU0LC0xNTEuNSAtMTc1OS4xLC01Ni44IC0xMTEuMDYsMjIuNSAtMjI3LjQ4LDU4LjUgLTMzOS4xLDcxLjEgbCAtMzYuNDIsMzguMyA0MS40Miw5IGMgNTUuNTgsLTIuMSAxMTAuNjMsNS44IDE2NS45MiwzLjYgMjQwLjk3LC02LjggMTUyMS44OCwtNzYuMyAxNjc0LjA4LDE5LjMiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxOTIiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNmMGE5NmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTA4MDkuOCwxMjI2Mi40IGMgMzEwLjgsNzMuMyA2MjAuMywxNTEuOSA5MjguNCwyMzUuOCAyNDUsNjguNSA0OTYuNywxNTkuMSA3NTAuMiwxODUuMiAtNDguNywtNTQuNCAtMjY4LjYsLTk3LjIgLTM0Ny43LC0xMjYuNCAtMzU1LjksLTEzMS41IC03NjEuOSwtMzcyLjggLTEwMjkuNywtNjQxLjggLTE2NC45LC0xNjUuNiAtMzIxLjgsLTM5MS41IC00MzAuMiwtNTk4LjcgLTIxLjcsMzM0LjkgLTUuNyw2MzIuNyAxMjksOTQ1LjkiIC8+PGcKICAgICAgICAgaWQ9ImcxOTQiPjxnCiAgICAgICAgICAgY2xpcC1wYXRoPSJ1cmwoI2NsaXBQYXRoMjAwKSIKICAgICAgICAgICBpZD0iZzE5NiI+PHBhdGgKICAgICAgICAgICAgIGlkPSJwYXRoMjA4IgogICAgICAgICAgICAgc3R5bGU9ImZpbGw6dXJsKCNsaW5lYXJHcmFkaWVudDIwNik7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICBkPSJtIDEwODA5LjgsMTIyNjIuNCBjIDE3LjgsNzIuOCAzOC45LDE1NS43IDgwLDIxOC44IDEwNS40LDE2MS44IDU2My45LDI3Mi4yIDc1Ni4zLDMxOCA0NDYuNiwxMDYuMyA3NDUuNSwxNTAuNiAxMTQ5LjEsLTk4LjUgLTEyLjgsLTIwLjggLTIyLjcsLTM3LjggLTQwLjgsLTU0LjggLTkxLjUsMzAuMiAtMTcwLjEsMzcuMiAtMjY2LDM3LjUgLTI1My41LC0yNi4xIC01MDUuMiwtMTE2LjcgLTc1MC4yLC0xODUuMiAtMzA4LjEsLTgzLjkgLTYxNy42LC0xNjIuNSAtOTI4LjQsLTIzNS44IiAvPjwvZz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyMTAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNkZDFlMjY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gOTI5OS41LDc2NjkuNCBjIDUzMy41NiwtOTQuNyAxMjI4LjQsLTQ4LjkgMTc1OS4xLDU2LjggLTIwNC43LC0xODMuMSAtNTkwLjUsLTU0MC41IC04NzQuMiwtNTYwLjUgLTYxLjgsMzAuOSAtMTUyLDExLjggLTIyMC41NSwxOS42IC01OS4xMSw2LjggLTExOS4zNiwyMC43IC0xNzUuOTgsMzguOSAtMjU2LjQ1LDgyLjQgLTM2OS43OCwyMTAuNSAtNDg4LjM3LDQ0NS4yIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjEyIgogICAgICAgICBzdHlsZT0iZmlsbDojMWIxYjFkO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDc0NTQuOTIsMTE3MjQuNyBjIDM3My43OSw4OC43IDc1MS4xNywxMzYuMSAxMDk0LjQ2LC03NyAyMTYuNiwtMTM0LjQgMzY3LjI5LC0zNDIuNiA0ODguMjQsLTU2Mi41IC02My40NSw0MC40IC0xNTQuMzksMTA2IC0xOTYuMjYsMTY5LjEgLTY2Ljk5LC0zOS44IC0xMzIuODQsLTc2LjggLTIwNC4yMSwtMTA4LjIgLTQ1LjgxLC0yMC4yIC05OS44OCwtMzUuMiAtMTQyLjc4LC02MCAtOSwtMi4zIC0xNy45OCwtNC43IC0yNy4wMywtNi43IC0zMjAuMywtNzEuOCAtNTYwLjYzLDYwLjcgLTgyMy40LDIzMC4xIC05OC4zMSwxMiAtMzk4Ljk3LDI3NS40IC00NjguNTksMzU4LjkgOTMuNzQsOC41IDE4OC44OCwzMS42IDI3OS41Nyw1Ni4zIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjE0IgogICAgICAgICBzdHlsZT0iZmlsbDojZWZlY2U3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDgzMjQuMSwxMTU1OC4xIGMgMTYuNzIsLTMuNiAzNC4yMywtNy4xIDUwLjIxLC0xMy4zIDI0LjE5LC05LjMgMzcuMzEsLTI0IDQ4LjAxLC00Ny4yIDIuMzQsLTMzLjIgLTUuMTIsLTQ3LjcgLTIxLjExLC03NS4yIC0yMC44NywwLjIgLTQwLjU1LDEuNiAtNTkuNTYsMTEuNCAtMjEuNTksMTEgLTM2LjU4LDMyLjggLTQwLjcyLDU2LjQgLTQuODIsMjcuNSA5LDQ2LjYgMjMuMTcsNjcuOSIgLz48ZwogICAgICAgICBpZD0iZzIxNiI+PGcKICAgICAgICAgICBjbGlwLXBhdGg9InVybCgjY2xpcFBhdGgyMjIpIgogICAgICAgICAgIGlkPSJnMjE4Ij48cGF0aAogICAgICAgICAgICAgaWQ9InBhdGgyMzAiCiAgICAgICAgICAgICBzdHlsZT0iZmlsbDp1cmwoI2xpbmVhckdyYWRpZW50MjI4KTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICAgIGQ9Im0gNzc5Mi45MSwxMTQ1OS4xIGMgNDkuOTgsNDIgMTE4LjA2LDk5LjMgMTgwLjk4LDExOS4yIDE5LjgyLDYuMiAxMS4zNyw2LjMgMzAuMTQsLTQgbCAtMS44NCwtMjQuMiBjIDAuNzMsLTEzMy45IDAuNjEsLTI1OC4zIDEwMS4zMywtMzYwLjggNTEsLTUxLjkgMTIwLjEzLC04My44IDE5My41LC04Mi4yIDc2LjY5LDEuNyAxNDYuMDcsMzkuOSAxOTYuOTcsOTUuOSA3MC4wOCw3Ny4yIDkyLjQsMTY4LjMgMTA4LDI2Ny43IDc0Ljg5LC01NiAxOTMuMiwtMTMyLjQgMjM5LjM3LC0yMTYuNCAtNjYuOTksLTM5LjggLTEzMi44NCwtNzYuOCAtMjA0LjIxLC0xMDguMiAtNDUuODEsLTIwLjIgLTk5Ljg4LC0zNS4yIC0xNDIuNzgsLTYwIC05LC0yLjMgLTE3Ljk4LC00LjcgLTI3LjAzLC02LjcgLTMyMC4zLC03MS44IC01NjAuNjMsNjAuNyAtODIzLjQsMjMwLjEgNDQuMzgsNTcuMSA5MC44OSwxMDYuMyAxNDguOTcsMTQ5LjYiIC8+PC9nPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDIzMiIKICAgICAgICAgc3R5bGU9ImZpbGw6I2VmZWNlNztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA3NzkyLjkxLDExNDU5LjEgYyA0OS45OCw0MiAxMTguMDYsOTkuMyAxODAuOTgsMTE5LjIgMTkuODIsNi4yIDExLjM3LDYuMyAzMC4xNCwtNCBsIC0xLjg0LC0yNC4yIGMgLTEwLjA2LC00OSAtOS4wMywtOTUuOCAtOC4yNSwtMTQ1LjQgLTcyLjExLDQuOSAtMTQwLjU4LDkuMSAtMjAxLjAzLDU0LjQiIC8+PGcKICAgICAgICAgaWQ9ImcyMzQiPjxnCiAgICAgICAgICAgY2xpcC1wYXRoPSJ1cmwoI2NsaXBQYXRoMjQwKSIKICAgICAgICAgICBpZD0iZzIzNiI+PHBhdGgKICAgICAgICAgICAgIGlkPSJwYXRoMjQ4IgogICAgICAgICAgICAgc3R5bGU9ImZpbGw6dXJsKCNsaW5lYXJHcmFkaWVudDI0Nik7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICBkPSJtIDEwMDY5LDE1NzE1LjcgYyAxNTcuOCwtMTE0LjcgMzI3LjYsLTIxMS40IDQ4NCwtMzI4LjggMTkzLjMsLTE0NSAzODIuMywtMjk1LjUgNTc3LjIsLTQzOC41IDcwLjUsLTUxLjcgMTQ0LjUsLTExNC4zIDIyMC43LC0xNTcuMSA0MjQuNywtMzAyLjIgODM2LjQsLTYyMS40IDEyMzQuOCwtOTU3LjYgMTE3LjYsLTk4LjEgMjY5LjYsLTIwMi44IDM2NC45LC0zMjEuNyAyMC4yLC04My45IDI5My41LC0yNDguNyAyNTYsLTMyMy41IC0xNi4xLC0zMiAtNDcuMywtNjUuNCAtNjkuMSwtOTQuNCAtNjQuMSw4NS45IC0xODIuMywyNjkuMyAtMjc2LjcsMzEyIC0yMjIuNCwyMjguOCAtNDYxLjgsNDUzLjEgLTcxMC43LDY1My4xIC0zNjMuNiwyOTIuMiAtNzU0LjYsNTU0LjIgLTExMzAuNyw4MzAuNSAtMzIwLjIsMjM1LjIgLTYzMi41LDUwMC4xIC05NzYuNSw2OTkuOCAtMzU5LjMyLC0xODAuNSAtNjk5Ljg0LC00MDYuOSAtMTAzOC4yOSwtNjIzLjIgLTM5OS44NiwtMjU1LjUgLTgwMS45OSwtNTExLjQgLTExODguOTMsLTc4Ni4yIC0xNTMuMTUsLTk2LjEgLTI5OS4zOCwtMjAxLjggLTQzOC43MSwtMzE3LjEgLTExNS41NCwtOTYuMyAtMjI2LjU5LC0yMDEgLTM0NS44NCwtMjkyLjUgLTIwLjM2LC0xNS42IC0zMy42LC0yMy4xIC01OC44NCwtMjYuOSAzMzAuMjUsNDU0LjkgODU4LjcxLDc4NS43IDEzMjAuMjMsMTA5Mi4xIDE1Ni4yMiw3NS40IDQyNy44LDI3Ny43IDU4My4wNiwzODEuNSA0MTAuOSwyNDcuNCA3NTYuNzgsNDgyLjcgMTE5My40Miw2OTguNSIgLz48L2c+PC9nPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjUwIgogICAgICAgICBzdHlsZT0iZmlsbDojMWIxYjFkO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDExMDgxLjQsMTExODguMiBjIDEuOCwxOS40IDUuNCwzNi4zIDEyLjksNTQuMiA1NiwxMzMuNyAxNjUuNCwyNjIuMyAyNzUuNCwzNTUgNjAxLjcsNTA3LjcgMTE0NC42LC0xMjAgMTY2NC4yLDEwMC4xIC05OS42LC03OS4yIC0zNjMuNiwtMjgwLjcgLTQ5My4yLC0yNzQuNCAtMjAuNCwxIC0xMC43LDIuNCAtMzAuMywtMC45IC0zLjQsLTAuNiAtNi43LC0xLjQgLTEwLC0yLjEgLTIzLDIuNCAtNDQuMyw5LjggLTY2LjIsMTYuNyAtMTMxLjUsLTIxNy41IC0zMjQuOSwtMzk0LjQgLTU2OC43LC00NzYuMyAtNy40LC0xLjEgLTE0LjksLTIuMSAtMjIuMywtMy41IC0xNjkuMywtMzMgLTI4MCwxMC40IC00MzcuNSw2Mi44IC05NS4zLDQ1LjYgLTE4NS43LDEzOC4yIC0yNTguOCwyMTMuMiAtMjEuNCwtMTYuMiAtNDEuNCwtMzIuOSAtNjUuNSwtNDQuOCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDI1MiIKICAgICAgICAgc3R5bGU9ImZpbGw6I2ZjZDRhODtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMTcwMi43LDExNTQxLjUgYyA3LjksLTEuNCAxNi43LC0yLjQgMjQuMSwtNS45IDI1LjgsLTEyLjEgMzAuMSwtMjAuMiA0MC4xLC00NC45IC0zLjgsLTMzLjEgLTE2LC01MS41IC0zNC40LC03OC44IC0xMSwzIC0zMC45LDYuNyAtNDEuMywxMi44IC0yMi41LDEzLjMgLTIzLjgsMjEuOSAtMzAuMyw0NS4yIDUuOCwzMi4zIDIxLDQ3LjkgNDEuOCw3MS42IiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjU0IgogICAgICAgICBzdHlsZT0iZmlsbDojZWZlY2U3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDExMzQ0LjgsMTE0MTQuNCBjIDYuOCwtMzYuMyAxMy4zLC03My4xIDI1LjEsLTEwOC4xIDMyLjEsLTk1IDEwMy4xLC0xNzguMyAxOTQuOCwtMjIwLjIgNS40LC0yLjQgMTAuOCwtNC44IDE2LjIsLTYuOSA1LjUsLTIuMiAxMSwtNC4zIDE2LjYsLTYuMiA1LjYsLTEuOCAxMS4yLC0zLjYgMTYuOCwtNS4yIDUuNywtMS42IDExLjQsLTMuMSAxNy4xLC00LjQgNS44LC0xLjMgMTEuNSwtMi40IDE3LjMsLTMuNCA1LjgsLTEgMTEuNiwtMS45IDE3LjUsLTIuNiA1LjgsLTAuNyAxMS43LC0xLjMgMTcuNiwtMS43IDUuOCwtMC4zIDExLjcsLTAuNiAxNy42LC0wLjcgNS45LC0wLjEgMTEuNywtMC4xIDE3LjYsMC4yIDUuOSwwLjIgMTEuOCwwLjUgMTcuNiwxIDUuOSwwLjYgMTEuNywxLjIgMTcuNiwyLjEgNS44LDAuOCAxMS42LDEuNyAxNy40LDIuOSA1LjcsMS4xIDExLjUsMi4zIDE3LjIsMy44IDUuNywxLjQgMTEuNCwyLjkgMTcsNC43IDUuNiwxLjcgMTEuMiwzLjUgMTYuNyw1LjUgNS42LDIgMTEsNC4yIDE2LjUsNi40IDc3LjksMzIuMyAxNDIuNiw5Mi44IDE3Mi4xLDE3Mi43IDQwLjgsMTEwLjkgOC4zLDIyNS45IC0zNi44LDMyOS40IDE1Ny45LC0yNy43IDMwNy41LC05OC4xIDQ1OS45LC0xNDYuOSAtMTMxLjUsLTIxNy41IC0zMjQuOSwtMzk0LjQgLTU2OC43LC00NzYuMyAtNy40LC0xLjEgLTE0LjksLTIuMSAtMjIuMywtMy41IC0xNjkuMywtMzMgLTI4MCwxMC40IC00MzcuNSw2Mi44IC05NS4zLDQ1LjYgLTE4NS43LDEzOC4yIC0yNTguOCwyMTMuMiA2NC4yLDYyLjggMTMwLjIsMTIyLjQgMTk3LjksMTgxLjQiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNTYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNmMGE5NmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gODAyNC43MSwxMjUyMS4xIDEuNTMsMTEuOCBjIC02Mi40MywzMS43IC0xMzIuMDMsNDEuNiAtMTkzLjU3LDc0LjYgMTkzLjcyLC0yLjIgMzk5Ljc2LC0xMzMuNyA1ODkuMDEsLTEyMi4xIDE3NC40MSwtNDYuMyAzNTAuNDMsLTEwNC42IDUyNi42NSwtMTQxLjUgNTUuOTUsLTE4LjUgMjcyLjM5LC04OS43IDMyMC40LC03NS40IDM1Ni45NSwtNzc3LjMgMzk5LjU4LC0xMzMyLjggMzMwLjA1LC0yMTc0LjQgLTE3LjIyLC0yMDguNSAtNjQuODcsLTUwMS40IC0yNS4zMiwtNzAyLjQgMjUuOTEsLTEzMS42IDExMi43OSwtMjQ2LjEgMjQwLjk1LC0yOTIgMjUyLjg5LC05MC41IDQzOS43OSw3OCA2NjQuOTksNjAuOSA4NC44LC02LjQgMTg3LjcsLTkwLjMgMjY3LC01OS45IDM2LDQzLjUgMzgsOTAuMyAzMy42LDE0NS4xIC01LjgsNzEuNyAtMjcuMSwxNDMuMyAtNDUuMywyMTIuNSA2NC4yLC05NC4yIDEyMi44LC0yMDUuOCA5OC41LC0zMjMuOCAtMTcuMiwtODMuMyAtNzQuNiwtMTUzIC0xNDYuNCwtMTk2LjUgLTExOC45LC03MiAtMjY3LjUsLTg4LjQgLTM5Ni42LC0xMzcuOSAtMTQzLjksLTU1LjIgLTI3OS43LC0xMjkuOCAtNDI0LjU4LC0xODMuMyAtNTEuMTksMjIgLTEwMi43Miw0NCAtMTU2LjAyLDYwLjYgLTU1LjkxLDE3LjUgLTE3Ny45NiwzNC40IC0yMjIuNCw2MS43IC01OC41LDEwLjEgLTExOC43NSwyNS44IC0xNzMuODEsNDguMSAtOTUuNDksMzguOCAtMTgzLjg2LDEwMS42IC0yMjIuMTYsMjAwLjkgLTY0LjE3LDE2Ni4xIDQ2LjUzLDM3OS42IDExNy4wOSw1MjkgMTEuNjksNjYuMiAxMDAuMzEsMjI5LjYgMTI5LjUsMzA3LjEgMTYwLjIyLDQyNS42IDIyNi45NCw4OTguNCA4NC44NCwxMzM4LjYgLTE1Ny43NCw0ODguNiAtNTIxLjk0LDkxNC41IC05NzAuNDQsMTE2MS4zIC0xMzMuNzUsNzMuNiAtMjc5LjMsMTE4LjQgLTQxMi41NCwxODguOSBsIC0xNC45Nyw4LjEiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNTgiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNhMjFjMzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTA0NjEuMSw5MTEwLjIgYyAyOC45LC0xLjEgNTguNSwtNy41IDg3LjEsLTEyLjEgbCAxMi4zLC0yOS42IGMgLTEuOSwtMi4zIC0zLjcsLTQuNyAtNS43LC02LjkgLTczLjIsLTc1LjQgLTE5Ni41LC05MS45IC0yOTUuNCwtOTcuOSBsIC0xMDEuNSwtOSBjIDk2LjIsOTAuMyAxNjguNiwxNDEuNCAzMDMuMiwxNTUuNSIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDI2MCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2EyMWMzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA5MzcwLjIxLDg5NTIuMiBjIDMyLjU2LDM4LjcgNjQuODksODAuOCAxMDIuOTQsMTE0LjEgMzQuNTYsMzAuMyA3OS4zMyw1Ni42IDEyNi44Nyw1MS44IDg5LjYzLC05LjEgMTY0LjIxLC0xMTYuNyAyMTguMjEsLTE3OC44IC01MC40MywxMi4xIC05OC45LDIyLjYgLTE1MC42MSwyOCAtMTAwLjM3LDIwLjYgLTE5Ny40NywtNC4xIC0yOTcuNDEsLTE1LjEiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNjIiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNjYzU5MmY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gOTIwOC4zMiw5NTE3LjEgYyAwLjE3LC01LjcgMC40MywtMTEuNCAwLjUyLC0xNy4xIDAuNzEsLTQyLjUgLTkuNDQsLTg1IC0xMy4wMiwtMTI3LjMgLTEyLjY1LC0xNDguMyAxMy4wNiwtMjg3LjIgMTIyLjIzLC0zOTYuNyAxMy4zOSwtMTMuNCAyNC4zOSwtMjEuMyA0Mi44NSwtMjYuOCBsIDkuMzEsMyBjIDk5Ljk0LDExIDE5Ny4wNCwzNS43IDI5Ny40MSwxNS4xIC04OS4zMSwtNi43IC0yNzcuMjYsLTYxLjMgLTM1Mi43NiwtOS43IC0xOS4xMSwxMyAtMzEuODUsMzUuOSAtNDMuOTEsNTUuMiBsIC03MS44MiwtMTExLjUgYyA2LjU2LC0zMC40IDIwLjY5LC00My44IDQ2LjQ4LC02MC45IDk0LC02Mi4yIDE2MS45NCwtNTIuMyAyNDQuMDIsLTkxLjEgbCAtMi40MywtMTAuMiBjIC01OC41LDEwLjEgLTExOC43NSwyNS44IC0xNzMuODEsNDguMSAtOTUuNDksMzguOCAtMTgzLjg2LDEwMS42IC0yMjIuMTYsMjAwLjkgLTY0LjE3LDE2Ni4xIDQ2LjUzLDM3OS42IDExNy4wOSw1MjkiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNjQiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNkZjdlM2E7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNjk3Mi4yOSwxMzU0My42IGMgMjUuMjQsMy44IDM4LjQ4LDExLjMgNTguODQsMjYuOSAxMTkuMjUsOTEuNSAyMzAuMywxOTYuMiAzNDUuODQsMjkyLjUgMTM5LjMzLDExNS4zIDI4NS41NiwyMjEgNDM4LjcxLDMxNy4xIC0yOC4xMSwtMjQ1LjcgLTQ0Ljg2LC00OTMuMSAtNjkuNzIsLTczOS4yIC0xOC42OCwtMTg0LjkgLTUxLjQzLC0zNzguMiAtNTEuMjYsLTU2My40IDM2Ni4yMSw0LjUgNzI5LjAxLC03NSAxMDc2LjIsLTE4Ni44IDY5LjQ1LC0yMi40IDE1Ny4wOSwtNDUuNSAyMTkuNjYsLTgxLjMgMjkuNTksLTkzLjggLTQ2Ljk4LC0xNzQuNCAtNDIuMjMsLTI2NS41IC0xNzYuMjIsMzYuOSAtMzUyLjI0LDk1LjIgLTUyNi42NSwxNDEuNSAtMTg5LjI1LC0xMS42IC0zOTUuMjksMTE5LjkgLTU4OS4wMSwxMjIuMSA2MS41NCwtMzMgMTMxLjE0LC00Mi45IDE5My41NywtNzQuNiBsIC0xLjUzLC0xMS44IGMgLTEyNy4zNCw0NC41IC0yNTMuNDUsODguMSAtMzgzLjYxLDEyMy43IC04Ny4wNiwtMjkxLjIgLTE2NC4wNSwtNjA5IC0yMDcuNTksLTkwOS41IGwgMjEuNDEsLTEwLjYgYyAtOTAuNjksLTI0LjcgLTE4NS44MywtNDcuOCAtMjc5LjU3LC01Ni4zIDY5LjYyLC04My41IDM3MC4yOCwtMzQ2LjkgNDY4LjU5LC0zNTguOSAyNjIuNzcsLTE2OS40IDUwMy4xLC0zMDEuOSA4MjMuNCwtMjMwLjEgOS4wNSwyIDE4LjAzLDQuNCAyNy4wMyw2LjcgbCAyLjk0LC04LjQgQyA4MTIwLjQyLDEwODc2IDczOTAuMjIsMTEyNjEgNzA2Mi4yNywxMDk5NyBjIC0xMS4wOSwtMjMyLjIgNTQuMjYsLTQ3My43IDE1NC44MiwtNjgxLjQgMjMyLjM0LC00NzkuOSA2NTcuMTcsLTg0MS45IDkxOS4yNiwtMTMwNy42IDE3MS4wMSwtMzA0IDM2MC41NiwtOTM3LjkgNTY1LjE5LC0xMTU3LjMgMTAuNzIsLTExLjUgMzEuMDgsLTI3LjkgNDcuMjksLTI3LjUgMjEuODQsMC41IDQwLjAyLDE0LjEgNTguMTgsMjUgMzEuMzksLTExIDM5LjM5LC0yNy40IDU0LjY0LC01Ni42IDIxLjkzLC05LjkgMzguMzksLTExLjYgNjIuMzMsLTEyLjggbCAzNi40MiwtMzguMyBjIDExMS42MiwtMTIuNiAyMjguMDQsLTQ4LjYgMzM5LjEsLTcxLjEgMTE4LjU5LC0yMzQuNyAyMzEuOTIsLTM2Mi44IDQ4OC4zNywtNDQ1LjIgNTYuNjIsLTE4LjIgMTE2Ljg3LC0zMi4xIDE3NS45OCwtMzguOSA2OC41NSwtNy44IDE1OC43NSwxMS4zIDIyMC41NSwtMTkuNiAtNTkuNiwtMTIuOSAtMTE5LjgsLTIwLjIgLTE4MC43LC0yMi4xIDE1LC02Ni4zIDM2LjcsLTEyOC43IDU5LjgsLTE5Mi41IC0yMjEuNDksNS4zIC01ODUuNTEsLTQuMiAtNzU4LjczLC0xNjUgLTUxLjI0LC00Ny42IC04MS42LC0xMDkuNCAtODMuMTYsLTE3OS42IC0yLjQsLTEwNi4zIDU5LjA3LC0yMDMuOSAxMzIuMDgsLTI3Ni4zIDIzOC4zLC0yMzYuNSA2MTkuMTMsLTMxOS45IDk0My44MSwtMzE1LjkgMjEzLjgsMi42IDQxMS4zLDUyLjkgNjIwLjQsODUgLTIyMS45LC0xODAuOCAtNTg5LjQsLTI0MC42IC04NjYuOCwtMjQxLjcgLTg3MC4yNSwtMy43IC0xNDY2LjA5LDU3Ny44IC0yMDQyLjI5LDExNTAuMyAtOTUuMzMsMTA2LjcgLTE5NC4yMywyMDcuNCAtMjgzLjYzLDMxOS42IC00MDcuODksNTEyLjMgLTYzMC42MiwxMDkxLjQgLTc3MC4zNywxNzI1LjggLTE4LjcsMTIwLjUgLTY0Ljk2LDI0Mi4yIC05Mi40NCwzNjEuOCAtMzAuNjQsMTMzLjQgLTQzLjQ3LDI4Mi4zIC04Ni40NCw0MTEuMiAtNDUuODQsMjAyLjUgLTgyLjA4LDQwNi43IC0xMTkuNzMsNjEwLjggLTE2LjEzLDg3LjUgLTI0LjQ0LDIwNS40IC01OC4zMywyODYuNyAtOS40OSw4NC42IC0yMC43MiwxNjkgLTI4LjMyLDI1My45IC00NC42OSw0OTkuNyAtOTMuNDksMTU4NiA3NC4wMSwyMDQ2IDcxLjA2LDE5NS4yIDE5Ni42MiwzNjIuMSAzMjguNzMsNTE5LjkiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNjYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNhMjFjMzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gODk2MC40LDc3NDAuNSBjIDExMS42MiwtMTIuNiAyMjguMDQsLTQ4LjYgMzM5LjEsLTcxLjEgMTE4LjU5LC0yMzQuNyAyMzEuOTIsLTM2Mi44IDQ4OC4zNywtNDQ1LjIgNTYuNjIsLTE4LjIgMTE2Ljg3LC0zMi4xIDE3NS45OCwtMzguOSA2OC41NSwtNy44IDE1OC43NSwxMS4zIDIyMC41NSwtMTkuNiAtNTkuNiwtMTIuOSAtMTE5LjgsLTIwLjIgLTE4MC43LC0yMi4xIC00MiwzLjIgLTg0LjE2LDIuNiAtMTI2LjE1LDYuMyAtNDIyLjcsMzYuNyAtNjU1Ljc3LDI4Ni4yIC05MTcuMTUsNTkwLjYiIC8+PGcKICAgICAgICAgaWQ9ImcyNjgiPjxnCiAgICAgICAgICAgY2xpcC1wYXRoPSJ1cmwoI2NsaXBQYXRoMjc0KSIKICAgICAgICAgICBpZD0iZzI3MCI+PHBhdGgKICAgICAgICAgICAgIGlkPSJwYXRoMjgyIgogICAgICAgICAgICAgc3R5bGU9ImZpbGw6dXJsKCNsaW5lYXJHcmFkaWVudDI4MCk7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICBkPSJtIDc2OTQuNywxMjg3Ny41IGMgMzY2LjIxLDQuNSA3MjkuMDEsLTc1IDEwNzYuMiwtMTg2LjggNjkuNDUsLTIyLjQgMTU3LjA5LC00NS41IDIxOS42NiwtODEuMyAyOS41OSwtOTMuOCAtNDYuOTgsLTE3NC40IC00Mi4yMywtMjY1LjUgLTE3Ni4yMiwzNi45IC0zNTIuMjQsOTUuMiAtNTI2LjY1LDE0MS41IC0yMDUuOTMsNTguNSAtNzE4Ljg2LDIwOC41IC05MTEuMjQsMjA2LjUgLTI2MC4zMiwtMi42IC00NjcuNzMsLTE3OC4zIC02MzguNzIsLTM1NSAxNS4xMSwyMyAzMS40LDQ0LjkgNDguNDcsNjYuNSAxOTYuNCwyNDguMiA0NTUuODQsNDM4LjEgNzc0LjUxLDQ3NC4xIiAvPjwvZz48L2c+PC9nPjwvZz48L3N2Zz4=" alt="Mei">
          <span class="fl-ai-agent-name">Foodland Mei</span>
    <button class="fl-ai-launcher" type="button" aria-label="Otvoriť Foodland poradcu">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 6.8A4.8 4.8 0 0 1 9.8 2h4.4A4.8 4.8 0 0 1 19 6.8v4.8a4.8 4.8 0 0 1-4.8 4.8h-2.8L7 20v-3.8a4.8 4.8 0 0 1-2-3.9V6.8Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/>
        <path d="M8.5 8.5h7M8.5 12h4.8" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>
      </svg>
    </button>
    </div>
  `;
  document.body.appendChild(root);

  const panel = root.querySelector(".fl-ai-panel");
  const launcher = root.querySelector(".fl-ai-launcher");
  const closeButton = root.querySelector(".fl-ai-close");
  const notice = root.querySelector(".fl-ai-notice");
  const messages = root.querySelector(".fl-ai-messages");
  let conversationHistory = [];
  const form = root.querySelector(".fl-ai-form");
  const input = root.querySelector(".fl-ai-input");
  const submit = root.querySelector(".fl-ai-submit");

  function addSuggestions() {
    const items = ["Kimchi", "Sriracha", "Sójová omáčka", "Recept na ramen"];
    const wrap = document.createElement("div");
    wrap.className = "fl-ai-suggestions";
    items.forEach(function (label) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "fl-ai-suggestion";
      btn.textContent = label;
      btn.addEventListener("click", function () {
        wrap.remove();
        input.value = label;
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      });
      wrap.appendChild(btn);
    });
    messages.appendChild(wrap);
    scrollToBottom();
  }

    function openPanel() {
    panel.classList.add("is-open");
    if (messages.children.length === 0) {
      addMessage("assistant", "Dobrý deň, s čím vám pomôžem? Môžete sa pýtať na produkty, ceny alebo odporúčania.");
      addSuggestions();
    }
    window.setTimeout(function () { input.focus(); }, 50);
  }

  function closePanel() {
    panel.classList.remove("is-open");
  }

  function addMessage(role, text, variant) {
    const message = document.createElement("div");
    message.className = `fl-ai-message ${role}${variant ? ` ${variant}` : ""}`;
    if (role === "user" || variant === "error") {
      message.textContent = text;
    } else {
      message.innerHTML = renderText(text);
    }
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

  function addRecipes(recipes) {
    if (!Array.isArray(recipes) || recipes.length === 0) return;

    const wrap = document.createElement("div");
    wrap.className = "fl-ai-recipes";
    recipes.slice(0, 4).forEach(function (recipe) {
      const title = recipe.title || "Recept Foodland";
      const cuisine = recipe.cuisine ? `${recipe.cuisine} kuchyňa` : "Foodland recept";
      const note = recipe.note ? ` · ${recipe.note}` : "";
      const card = document.createElement("article");
      card.className = "fl-ai-recipe";
      card.innerHTML = `
        <h3 class="fl-ai-recipe-title">${escapeHtml(title)}</h3>
        <div class="fl-ai-recipe-meta">${escapeHtml(cuisine + note)}</div>
        <a class="fl-ai-recipe-link" href="${escapeAttr(recipe.link || "https://www.foodland.sk/recepty/")}" target="_blank" rel="noopener">Otvoriť recept</a>
      `;
      wrap.appendChild(card);
    });
    messages.appendChild(wrap);
    scrollToBottom();
  }

  async function addToCart(product) {
    const productLink = product.link || "";
    const isOnFoodland = window.location.hostname.includes("foodland.sk");

    if (!isOnFoodland || !productLink) {
      window.open(productLink || "https://www.foodland.sk/", "_blank", "noopener");
      return;
    }

    const pageResp = await fetch(productLink, { credentials: "include" });
    const html = await pageResp.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    const productId = doc.querySelector('input[name="product_id"]')?.value;
    const manufacturerId = doc.querySelector('input[name="manufacturer_id"]')?.value || "";
    const categoryId = doc.querySelector('input[name="category_id"]')?.value || "";

    if (!productId) {
      window.open(productLink, "_blank", "noopener");
      return;
    }

    const body = new URLSearchParams({
      product_id: productId,
      quantity: "1",
      flypage: "shop.flypage",
      manufacturer_id: manufacturerId,
      category_id: categoryId,
      func: "cartAdd",
    });

    await fetch("/modules/mod_shop_cart_ajax.php", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  }

  function addProducts(products) {
    if (!Array.isArray(products) || products.length === 0) return;

    const INITIAL = 3;
    const wrap = document.createElement("div");
    wrap.className = "fl-ai-products";

    function renderCard(product) {
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
          <div class="fl-ai-product-actions">
            <a class="fl-ai-product-link" href="${escapeAttr(product.link || "#")}" target="_blank" rel="noopener">Zobraziť</a>
          </div>
        </div>
      `;
      const actionsDiv = card.querySelector(".fl-ai-product-actions");
      const cartBtn = document.createElement("button");
      cartBtn.type = "button";
      cartBtn.className = "fl-ai-cart-btn";
      cartBtn.textContent = "Do košíka";
      cartBtn.addEventListener("click", async function () {
        cartBtn.disabled = true;
        cartBtn.textContent = "Pridávam...";
        try {
          await addToCart(product);
          cartBtn.textContent = "✓ Pridané";
          cartBtn.classList.add("is-added");
        } catch (e) {
          cartBtn.textContent = "Do košíka";
          cartBtn.disabled = false;
          window.open(product.link || "https://www.foodland.sk/", "_blank", "noopener");
        }
      });
      actionsDiv.appendChild(cartBtn);
      const image = card.querySelector("img");
      const fallback = card.querySelector(".fl-ai-product-image-fallback");
      image.addEventListener("error", function () {
        image.style.display = "none";
        fallback.style.display = "flex";
      });
      return card;
    }

    products.slice(0, INITIAL).forEach(function (product) {
      wrap.appendChild(renderCard(product));
    });

    if (products.length > INITIAL) {
      const remaining = products.slice(INITIAL);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "fl-ai-show-more";
      btn.textContent = `Zobraziť viac (${remaining.length})`;
      btn.addEventListener("click", function () {
        remaining.forEach(function (p) { wrap.insertBefore(renderCard(p), btn); });
        btn.remove();
        scrollToBottom();
      });
      wrap.appendChild(btn);
    }

    messages.appendChild(wrap);
    scrollToBottom();
  }

    function scrollToBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function updateNotice(data) {
    const products = Array.isArray(data.products) ? data.products : [];
    const shouldShow = data.intent === "allergen_safety" || products.length > 0;
    notice.hidden = !shouldShow;
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
    const backendText = withFollowUpContext(text);

    if (demoMode) {
      await new Promise(function (resolve) { window.setTimeout(resolve, 600); });
      const normalizedText = normalizedInput(backendText);
      let products = [];
      let recipes = [];
      let answer = "Nenašiel som presnú demo odpoveď. Skúste napísať názov produktu alebo kategóriu presnejšie.";
      const requestedRecipes = demoRecipesForText(normalizedText);
      const ingredientProducts = demoIngredientProductsForText(normalizedText);

      if (ingredientProducts.length > 0) {
        products = ingredientProducts;
        answer = "Na prípravu odporúčam tieto suroviny z Foodland.sk.";
      } else if (isRecipeRequest(normalizedText) && requestedRecipes.length > 0) {
        products = [];
        recipes = requestedRecipes;
        answer = recipes.length === 1
          ? "Našiel som recept z Foodland.sk. Otvorte si ho nižšie."
          : "Našiel som recepty z Foodland.sk. Vyberte si z odporúčaní nižšie.";
      } else if (isKimchiIngredientRequest(normalizedText)) {
        products = kimchiIngredientDemoProducts;
        answer = "Na výrobu kimchi odporúčam najmä gochujang, čili papriku, rybaciu omáčku, ryžovú múku a sezamový olej.";
      } else if (normalizedText.includes("kimchi") || normalizedText.includes("kimci")) {
        products = demoProducts;
        answer = "Našiel som niekoľko vhodných produktov. Pozrite si odporúčania nižšie.";
      } else if (isSoySauceRequest(normalizedText)) {
        products = soySauceDemoProducts;
        answer = "Našiel som sójové omáčky. Pozrite si odporúčania nižšie.";
      } else if (normalizedText.includes("srirach") || normalizedText.includes("srirac")) {
        products = srirachaDemoProducts;
        answer = "Našiel som niekoľko vhodných produktov. Pozrite si odporúčania nižšie.";
      }

      return {
        answer,
        recipes,
        products,
      };
    }

    const response = await fetch(`${apiBaseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: backendText, limit: 6, conversation_history: conversationHistory }),
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

  function renderText(text) {
    const escaped = escapeHtml(String(text || ""));
    return escaped.replace(
      /https?:\/\/[^\s\)\]"'<>]+/g,
      function (url) {
        return '<a href="' + url + '" target="_blank" rel="noopener" style="color:#299B5E;word-break:break-all;">' + url + '<\/a>';
      }
    );
  }

  function cleanAnswerText(text, hasProducts) {
    if (!hasProducts) return text;
    return text.split('\n').filter(function (line) {
      const t = line.trim();
      return !(t.startsWith('-') && /\d+[,.]\d+\s*(EUR|€)/.test(t));
    }).join('\n').trim();
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
    rememberProductSubject(text);
    const loading = addLoadingMessage();

    try {
      const data = await askBackend(text);
      updateNotice(data);
      const hasProducts = Array.isArray(data.products) && data.products.length > 0;
      loading.innerHTML = renderText(
        cleanAnswerText(
          data.answer || "Nenašiel som presnú odpoveď. Skúste napísať názov produktu alebo kategóriu inak.",
          hasProducts
        )
      );
      conversationHistory.push({role: "user", content: text});
      conversationHistory.push({role: "assistant", content: data.answer || ""});
      scrollToBottom();
      addRecipes(data.recipes);
      if (data.intent !== "recipe") addProducts(data.products);
    } catch (error) {
      notice.hidden = true;
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
