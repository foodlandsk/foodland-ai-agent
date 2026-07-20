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
    
      overflow: hidden;
      padding: 0;}
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
    .fl-ai-label-block {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
    }
    .fl-ai-label-title {
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
          width: 100%;
          height: 100%;
          display: block;
          object-fit: cover;
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
    <section class="fl-ai-panel" aria-label="Foodland Mei">
      <header class="fl-ai-header">
        <div class="fl-ai-brand">
          <div class="fl-ai-mark">FL</div>
          <div>
            <p class="fl-ai-title">Foodland Mei</p>
            <div class="fl-ai-status">AI poradkyňa pre ázijskú kuchyňu</div>
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
      <div class="fl-ai-label-block">
        <span class="fl-ai-label-title">Spýtajte sa Mei</span>
        <span class="fl-ai-label-sub">Foodland poradca na ázijskú kuchyňu</span>
      </div>
    <button class="fl-ai-launcher" type="button" aria-label="Otvoriť Foodland poradcu">
      <img class="fl-ai-avatar" src="data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiIHN0YW5kYWxvbmU9Im5vIj8+CjxzdmcKICAgeG1sbnM6ZGM9Imh0dHA6Ly9wdXJsLm9yZy9kYy9lbGVtZW50cy8xLjEvIgogICB4bWxuczpjYz0iaHR0cDovL2NyZWF0aXZlY29tbW9ucy5vcmcvbnMjIgogICB4bWxuczpyZGY9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkvMDIvMjItcmRmLXN5bnRheC1ucyMiCiAgIHhtbG5zOnN2Zz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciCiAgIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIKICAgeG1sbnM6c29kaXBvZGk9Imh0dHA6Ly9zb2RpcG9kaS5zb3VyY2Vmb3JnZS5uZXQvRFREL3NvZGlwb2RpLTAuZHRkIgogICB4bWxuczppbmtzY2FwZT0iaHR0cDovL3d3dy5pbmtzY2FwZS5vcmcvbmFtZXNwYWNlcy9pbmtzY2FwZSIKICAgdmlld0JveD0iMCAwIDYyLjAwMDAwMyA2Mi4wMDAwMDMiCiAgIGhlaWdodD0iNjIuMDAwMDA0IgogICB3aWR0aD0iNjIuMDAwMDA0IgogICB4bWw6c3BhY2U9InByZXNlcnZlIgogICBpZD0ic3ZnMiIKICAgdmVyc2lvbj0iMS4xIgogICBpbmtzY2FwZTp2ZXJzaW9uPSIwLjQ4LjAgcjk2NTQiCiAgIHNvZGlwb2RpOmRvY25hbWU9IjIzNjkyMjI2M19zdmcuc3ZnIj48c29kaXBvZGk6bmFtZWR2aWV3CiAgICAgcGFnZWNvbG9yPSIjZmZmZmZmIgogICAgIGJvcmRlcmNvbG9yPSIjNjY2NjY2IgogICAgIGJvcmRlcm9wYWNpdHk9IjEiCiAgICAgb2JqZWN0dG9sZXJhbmNlPSIxMCIKICAgICBncmlkdG9sZXJhbmNlPSIxMCIKICAgICBndWlkZXRvbGVyYW5jZT0iMTAiCiAgICAgaW5rc2NhcGU6cGFnZW9wYWNpdHk9IjAiCiAgICAgaW5rc2NhcGU6cGFnZXNoYWRvdz0iMiIKICAgICBpbmtzY2FwZTp3aW5kb3ctd2lkdGg9IjIwNDgiCiAgICAgaW5rc2NhcGU6d2luZG93LWhlaWdodD0iMTA4MSIKICAgICBpZD0ibmFtZWR2aWV3MzI2NyIKICAgICBzaG93Z3JpZD0iZmFsc2UiCiAgICAgZml0LW1hcmdpbi10b3A9IjAiCiAgICAgZml0LW1hcmdpbi1sZWZ0PSIwIgogICAgIGZpdC1tYXJnaW4tcmlnaHQ9IjAiCiAgICAgZml0LW1hcmdpbi1ib3R0b209IjAiCiAgICAgaW5rc2NhcGU6em9vbT0iMSIKICAgICBpbmtzY2FwZTpjeD0iODI4IgogICAgIGlua3NjYXBlOmN5PSItMTAwLjM5Njg2IgogICAgIGlua3NjYXBlOndpbmRvdy14PSIwIgogICAgIGlua3NjYXBlOndpbmRvdy15PSIwIgogICAgIGlua3NjYXBlOndpbmRvdy1tYXhpbWl6ZWQ9IjEiCiAgICAgaW5rc2NhcGU6Y3VycmVudC1sYXllcj0ic3ZnMiIgLz48bWV0YWRhdGEKICAgICBpZD0ibWV0YWRhdGE4Ij48cmRmOlJERj48Y2M6V29yawogICAgICAgICByZGY6YWJvdXQ9IiI+PGRjOmZvcm1hdD5pbWFnZS9zdmcreG1sPC9kYzpmb3JtYXQ+PGRjOnR5cGUKICAgICAgICAgICByZGY6cmVzb3VyY2U9Imh0dHA6Ly9wdXJsLm9yZy9kYy9kY21pdHlwZS9TdGlsbEltYWdlIiAvPjxkYzp0aXRsZT48L2RjOnRpdGxlPjwvY2M6V29yaz48L3JkZjpSREY+PC9tZXRhZGF0YT48ZGVmcwogICAgIGlkPSJkZWZzNiI+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGg1NiIKICAgICAgIGNsaXBQYXRoVW5pdHM9InVzZXJTcGFjZU9uVXNlIj48cGF0aAogICAgICAgICBpZD0icGF0aDU0IgogICAgICAgICBkPSJtIDEzODA3LjEsMTY1MDUuOCBjIDIwLjUsLTI2LjQgNDUuNiwtNTMuNiA2MS40LC04MyAxMDA5LjksLTEyMTkuNyAxMjIzLjcsLTMwMDkuMSAxMDgwLjMsLTQ1MzUuMSBDIDE0NzU3LjEsOTg0Ni42IDEzODQwLDgxMTcuNiAxMjI1OC42LDY4MTEgYyAtMjcuOCwtMjMgLTU1LjgsLTQ1LjMgLTg1LjMsLTY2LjIgLTIuMSw0Ny43IC0xLDk4LjIgLTEwLjcsMTQ0LjkgbCAtMi4zLDQwLjEgYyA1LDY4LjcgLTEuMywxMzguNyAtNC44LDIwNy41IDM3LjgsNjguMyAxMjEuNCwxMzkuMiAxNzMuOCwxOTkuNiA4NCw5Ny43IDE2My40LDE5OSAyMzguMSwzMDQgMjM5LjMsMzM4IDQwNi45LDczMy42IDUyMi45LDExMjkuNiAzOC42LDEzMS40IDY0LjMsMjY2LjUgMTA0LjMsMzk3LjQgMzMuMywxODMuNyA4NSwzNzMuMiAxMzcsNTUyLjcgNDkuOCwyMDQuMyA5NS43LDQxNi43IDE3MS4yLDYxMy4yIDE3LjgsMTU4IDE1LDMxOS43IDE2LjQsNDc4LjUgMi44LDMwMi40IC0zLjEsNjA1LjUgMy40LDkwNy43IC0xMi43LDkxIC02LjUsMTkyLjUgLTYuOSwyODQuNSBsIC0yLjEsNTI1LjEgYyAtMi4xLDMuNyAtMy42LDcuOCAtNi40LDExIC04Myw5OC40IC0xNDQuMiwyMTUgLTIxOSwzMjAuNyAtMTMzLjgsMTg4LjQgLTI3Ni4zLDM3MCAtNDI3LjQsNTQ0LjggOTQuNCwtNDIuNyAyMTIuNiwtMjI2LjEgMjc2LjcsLTMxMiAyMS44LDI5IDUzLDYyLjQgNjkuMSw5NC40IDM3LjUsNzQuOCAtMjM1LjgsMjM5LjYgLTI1NiwzMjMuNSAtOTUuMywxMTguOSAtMjQ3LjMsMjIzLjYgLTM2NC45LDMyMS43IC0zOTguNCwzMzYuMiAtODEwLjEsNjU1LjQgLTEyMzQuOCw5NTcuNiA2NC43LDgxIDMyMi45LDIyOS4zIDQyNC40LDI5Ny43IGwgNjAyLjUsNDEyLjYgYyA0NzguMiwzMzEuNSA5NDUuNyw2ODEuMiAxNDI5LjMsMTAwNC4yIHoiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PC9jbGlwUGF0aD48bGluZWFyR3JhZGllbnQKICAgICAgIGlkPSJsaW5lYXJHcmFkaWVudDY0IgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KDIyNDQuNTYsLTY1MS41OCw2NTEuNTgsMjI0NC41NiwxMjU5NywxMTczOS41KSIKICAgICAgIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIgogICAgICAgeTI9IjAiCiAgICAgICB4Mj0iMSIKICAgICAgIHkxPSIwIgogICAgICAgeDE9IjAiPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wNjAiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6IzE0MTIxMiIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDYyIgogICAgICAgICBvZmZzZXQ9IjEiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiMyMTJhMmQiIC8+PC9saW5lYXJHcmFkaWVudD48Y2xpcFBhdGgKICAgICAgIGlkPSJjbGlwUGF0aDEwMiIKICAgICAgIGNsaXBQYXRoVW5pdHM9InVzZXJTcGFjZU9uVXNlIj48cGF0aAogICAgICAgICBpZD0icGF0aDEwMCIKICAgICAgICAgZD0ibSAxMDkxNy45LDYwOTkuMyBjIDQ4My42LDI1My42IDg2OCw2NDUgMTIzNy42LDEwMzggMy41LC02OC44IDkuOCwtMTM4LjggNC44LC0yMDcuNSBsIDIuMywtNDAuMSBjIC0zLC0xOTMuMiAyNS42LC0zOTIuMSA0Mi43LC01ODQuNiAzMS42LC0zNTQgNjAuMSwtNzEzLjQgMTIxLjksLTEwNjMuNyA0MS44LC0yNTkgODUuNSwtNTE3LjYgMTMxLjEsLTc3NiA0LjcsLTIxLjcgOS44LC00My4zIDEzLjIsLTY1LjIgLTU4LjUsLTgxLjEgLTIyMy4xLC0xODguMSAtMzAzLjcsLTI2OC45IC0xODguNSwtMTg4LjkgLTM1OS44LC00MDMuMiAtNTM0LjUsLTYwNS4zIC0zOTMuMiwtNDU0LjcgLTc2OSwtOTMxLjggLTExMzMuNywtMTQwOS43IC0xMzUuMSwtMTc3IC0yNjIuNiwtMzU5LjggLTM5OS40LC01MzUuNCAtMTMwLjM1LDE3My4yIC0yNDQuODMsMzU4LjUgLTM3NC45NSw1MzIuMSAtMzQyLjIyLDQ1Ni43IC03MDIuOTYsOTA0LjIgLTEwNjQuMzMsMTM0NS45IC0yMzQuMTQsMjg2LjcgLTYyNi43Myw3ODguNCAtOTM3Ljg1LDk3Ny43IDUzLjE5LDI2NS41IDEwMC40OSw1MzIgMTQxLjksNzk5LjYgMzAuODIsMTA1IDMyLjU3LDI2NS4zIDQ0Ljc5LDM3Ni43IDM5LjY1LDM2MS45IDgyLjk4LDcyOC4xIDk3Ljk0LDEwOTIuMSAxLjcyLDEwMC45IDAuOSwyMDIgMS4xMSwzMDIuOSA1NzYuMiwtNTcyLjUgMTE3Mi4wNCwtMTE1NCAyMDQyLjI5LC0xMTUwLjMgMjc3LjQsMS4xIDY0NC45LDYwLjkgODY2LjgsMjQxLjcgeiIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2NsaXBQYXRoPjxsaW5lYXJHcmFkaWVudAogICAgICAgaWQ9ImxpbmVhckdyYWRpZW50MTA4IgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KDM4MDMuNDcsNzcyLjczNiwtNzcyLjczNiwzODAzLjQ3LDg1MzQuNjIsNDE4OC44KSIKICAgICAgIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIgogICAgICAgeTI9IjAiCiAgICAgICB4Mj0iMSIKICAgICAgIHkxPSIwIgogICAgICAgeDE9IjAiPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMTA0IgogICAgICAgICBvZmZzZXQ9IjAiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiNmOGEwNjUiIC8+PHN0b3AKICAgICAgICAgaWQ9InN0b3AxMDYiCiAgICAgICAgIG9mZnNldD0iMSIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2ZkZTRiNyIgLz48L2xpbmVhckdyYWRpZW50PjxjbGlwUGF0aAogICAgICAgaWQ9ImNsaXBQYXRoMTIwIgogICAgICAgY2xpcFBhdGhVbml0cz0idXNlclNwYWNlT25Vc2UiPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTE4IgogICAgICAgICBkPSJtIDEwOTE3LjksNjA5OS4zIGMgNDgzLjYsMjUzLjYgODY4LDY0NSAxMjM3LjYsMTAzOCAzLjUsLTY4LjggOS44LC0xMzguOCA0LjgsLTIwNy41IGwgLTMxNCwtMzg5LjIgYyAtMTUxLC0xNjguMyAtMzAwLjMsLTMzOS42IC00NTcsLTUwMi41IC01ODAuMiwtNjAzLjQgLTEyMDQuOSwtMTE3Mi40IC0xODIwLjY2LC0xNzM5LjQgLTE3Ny44NiwtMTYyLjIgLTM1NC40NywtMzI1LjcgLTUyOS44MywtNDkwLjYgLTEyMy43NSwtMTE2LjcgLTI0Ni4zNCwtMjQxLjcgLTM3Ny44OSwtMzQ5LjIgLTIzNC4xNCwyODYuNyAtNjI2LjczLDc4OC40IC05MzcuODUsOTc3LjcgNTMuMTksMjY1LjUgMTAwLjQ5LDUzMiAxNDEuOSw3OTkuNiAzMC44MiwxMDUgMzIuNTcsMjY1LjMgNDQuNzksMzc2LjcgMzkuNjUsMzYxLjkgODIuOTgsNzI4LjEgOTcuOTQsMTA5Mi4xIDEuNzIsMTAwLjkgMC45LDIwMiAxLjExLDMwMi45IDU3Ni4yLC01NzIuNSAxMTcyLjA0LC0xMTU0IDIwNDIuMjksLTExNTAuMyAyNzcuNCwxLjEgNjQ0LjksNjAuOSA4NjYuOCwyNDEuNyB6IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvY2xpcFBhdGg+PGxpbmVhckdyYWRpZW50CiAgICAgICBpZD0ibGluZWFyR3JhZGllbnQxMjYiCiAgICAgICBzcHJlYWRNZXRob2Q9InBhZCIKICAgICAgIGdyYWRpZW50VHJhbnNmb3JtPSJtYXRyaXgoLTE1NzUuNDgsLTQyOTQuODcsNDI5NC44NywtMTU3NS40OCwxMDM2OC4zLDc3NDIuMykiCiAgICAgICBncmFkaWVudFVuaXRzPSJ1c2VyU3BhY2VPblVzZSIKICAgICAgIHkyPSIwIgogICAgICAgeDI9IjEiCiAgICAgICB5MT0iMCIKICAgICAgIHgxPSIwIj48c3RvcAogICAgICAgICBpZD0ic3RvcDEyMiIKICAgICAgICAgb2Zmc2V0PSIwIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojYWExZTI0IiAvPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMTI0IgogICAgICAgICBvZmZzZXQ9IjEiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiNlYTgxNGMiIC8+PC9saW5lYXJHcmFkaWVudD48Y2xpcFBhdGgKICAgICAgIGlkPSJjbGlwUGF0aDE0MCIKICAgICAgIGNsaXBQYXRoVW5pdHM9InVzZXJTcGFjZU9uVXNlIj48cGF0aAogICAgICAgICBpZD0icGF0aDEzOCIKICAgICAgICAgZD0ibSAxMjg0OS42LDQ1OTMuNCBjIDI2LjksLTEuOCA2Mi44LDAuMSA4Ni40LC0xMi4zIC0zOC44LC04NS40IC0xNTIuMiwtMjAyLjIgLTIxMi43LC0yODEuMiAtMjE3LjYsLTI4OCAtNDM3LjcsLTU3NCAtNjYwLjIsLTg1OC4xIEwgMTA0MzMuOSwxMjk4LjEgQyAxMDEwNy4zLDg2Ny41IDk3NjUuMzEsNDQyLjgwMSA5NDU1Ljk0LDAgaCAtNjAzLjU4IGwgOTE0Ljk5LDExNTQuOSBjIDgzLjA3LDEyMC44IDE4OCwyMzQuOCAyNzkuODUsMzQ5LjkgMTkuNywyNC42IDM2LjYsNDkuMSA1Myw3Ni4xIDEzNi44LDE3NS42IDI2NC4zLDM1OC40IDM5OS40LDUzNS40IDM2NC43LDQ3Ny45IDc0MC41LDk1NSAxMTMzLjcsMTQwOS43IDE3NC43LDIwMi4xIDM0Niw0MTYuNCA1MzQuNSw2MDUuMyA4MC42LDgwLjggMjQ1LjIsMTg3LjggMzAzLjcsMjY4LjkgMTMxLjgsNDMuMyAxNTMuMywxNjEuOSAzNzguMSwxOTMuMiB6IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvY2xpcFBhdGg+PGxpbmVhckdyYWRpZW50CiAgICAgICBpZD0ibGluZWFyR3JhZGllbnQxNDYiCiAgICAgICBzcHJlYWRNZXRob2Q9InBhZCIKICAgICAgIGdyYWRpZW50VHJhbnNmb3JtPSJtYXRyaXgoMTE0My4yOCwtMTk1OC41NiwxOTU4LjU2LDExNDMuMjgsMTAzNzMuNiwzMTgyLjIpIgogICAgICAgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiCiAgICAgICB5Mj0iMCIKICAgICAgIHgyPSIxIgogICAgICAgeTE9IjAiCiAgICAgICB4MT0iMCI+PHN0b3AKICAgICAgICAgaWQ9InN0b3AxNDIiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2YzZGRkNCIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDE0NCIKICAgICAgICAgb2Zmc2V0PSIxIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojZjBmNWUyIiAvPjwvbGluZWFyR3JhZGllbnQ+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGgyMDAiCiAgICAgICBjbGlwUGF0aFVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxOTgiCiAgICAgICAgIGQ9Im0gMTA4MDkuOCwxMjI2Mi40IGMgMTcuOCw3Mi44IDM4LjksMTU1LjcgODAsMjE4LjggMTA1LjQsMTYxLjggNTYzLjksMjcyLjIgNzU2LjMsMzE4IDQ0Ni42LDEwNi4zIDc0NS41LDE1MC42IDExNDkuMSwtOTguNSAtMTIuOCwtMjAuOCAtMjIuNywtMzcuOCAtNDAuOCwtNTQuOCAtOTEuNSwzMC4yIC0xNzAuMSwzNy4yIC0yNjYsMzcuNSAtMjUzLjUsLTI2LjEgLTUwNS4yLC0xMTYuNyAtNzUwLjIsLTE4NS4yIC0zMDguMSwtODMuOSAtNjE3LjYsLTE2Mi41IC05MjguNCwtMjM1LjggeiIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2NsaXBQYXRoPjxsaW5lYXJHcmFkaWVudAogICAgICAgaWQ9ImxpbmVhckdyYWRpZW50MjA2IgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KC0xNzM1LjI2LDQzMS45NDIsLTQzMS45NDIsLTE3MzUuMjYsMTI2NzMuOSwxMjI5Ny43KSIKICAgICAgIGdyYWRpZW50VW5pdHM9InVzZXJTcGFjZU9uVXNlIgogICAgICAgeTI9IjAiCiAgICAgICB4Mj0iMSIKICAgICAgIHkxPSIwIgogICAgICAgeDE9IjAiPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMjAyIgogICAgICAgICBvZmZzZXQ9IjAiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiMxYTFhMWMiIC8+PHN0b3AKICAgICAgICAgaWQ9InN0b3AyMDQiCiAgICAgICAgIG9mZnNldD0iMSIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6IzFhNDY0ZiIgLz48L2xpbmVhckdyYWRpZW50PjxjbGlwUGF0aAogICAgICAgaWQ9ImNsaXBQYXRoMjIyIgogICAgICAgY2xpcFBhdGhVbml0cz0idXNlclNwYWNlT25Vc2UiPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjIwIgogICAgICAgICBkPSJtIDc3OTIuOTEsMTE0NTkuMSBjIDQ5Ljk4LDQyIDExOC4wNiw5OS4zIDE4MC45OCwxMTkuMiAxOS44Miw2LjIgMTEuMzcsNi4zIDMwLjE0LC00IGwgLTEuODQsLTI0LjIgYyAwLjczLC0xMzMuOSAwLjYxLC0yNTguMyAxMDEuMzMsLTM2MC44IDUxLC01MS45IDEyMC4xMywtODMuOCAxOTMuNSwtODIuMiA3Ni42OSwxLjcgMTQ2LjA3LDM5LjkgMTk2Ljk3LDk1LjkgNzAuMDgsNzcuMiA5Mi40LDE2OC4zIDEwOCwyNjcuNyA3NC44OSwtNTYgMTkzLjIsLTEzMi40IDIzOS4zNywtMjE2LjQgLTY2Ljk5LC0zOS44IC0xMzIuODQsLTc2LjggLTIwNC4yMSwtMTA4LjIgLTQ1LjgxLC0yMC4yIC05OS44OCwtMzUuMiAtMTQyLjc4LC02MCAtOSwtMi4zIC0xNy45OCwtNC43IC0yNy4wMywtNi43IC0zMjAuMywtNzEuOCAtNTYwLjYzLDYwLjcgLTgyMy40LDIzMC4xIDQ0LjM4LDU3LjEgOTAuODksMTA2LjMgMTQ4Ljk3LDE0OS42IHoiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PC9jbGlwUGF0aD48bGluZWFyR3JhZGllbnQKICAgICAgIGlkPSJsaW5lYXJHcmFkaWVudDIyOCIKICAgICAgIHNwcmVhZE1ldGhvZD0icGFkIgogICAgICAgZ3JhZGllbnRUcmFuc2Zvcm09Im1hdHJpeCg4OTAuMzc2LC00OTAuMzA0LDQ5MC4zMDQsODkwLjM3Niw3ODA1LjA4LDExNTU5LjkpIgogICAgICAgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiCiAgICAgICB5Mj0iMCIKICAgICAgIHgyPSIxIgogICAgICAgeTE9IjAiCiAgICAgICB4MT0iMCI+PHN0b3AKICAgICAgICAgaWQ9InN0b3AyMjQiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2M1YzFiYiIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDIyNiIKICAgICAgICAgb2Zmc2V0PSIxIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojZmZmZmZmIiAvPjwvbGluZWFyR3JhZGllbnQ+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGgyNDAiCiAgICAgICBjbGlwUGF0aFVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyMzgiCiAgICAgICAgIGQ9Im0gMTAwNjksMTU3MTUuNyBjIDE1Ny44LC0xMTQuNyAzMjcuNiwtMjExLjQgNDg0LC0zMjguOCAxOTMuMywtMTQ1IDM4Mi4zLC0yOTUuNSA1NzcuMiwtNDM4LjUgNzAuNSwtNTEuNyAxNDQuNSwtMTE0LjMgMjIwLjcsLTE1Ny4xIDQyNC43LC0zMDIuMiA4MzYuNCwtNjIxLjQgMTIzNC44LC05NTcuNiAxMTcuNiwtOTguMSAyNjkuNiwtMjAyLjggMzY0LjksLTMyMS43IDIwLjIsLTgzLjkgMjkzLjUsLTI0OC43IDI1NiwtMzIzLjUgLTE2LjEsLTMyIC00Ny4zLC02NS40IC02OS4xLC05NC40IC02NC4xLDg1LjkgLTE4Mi4zLDI2OS4zIC0yNzYuNywzMTIgLTIyMi40LDIyOC44IC00NjEuOCw0NTMuMSAtNzEwLjcsNjUzLjEgLTM2My42LDI5Mi4yIC03NTQuNiw1NTQuMiAtMTEzMC43LDgzMC41IC0zMjAuMiwyMzUuMiAtNjMyLjUsNTAwLjEgLTk3Ni41LDY5OS44IC0zNTkuMzIsLTE4MC41IC02OTkuODQsLTQwNi45IC0xMDM4LjI5LC02MjMuMiAtMzk5Ljg2LC0yNTUuNSAtODAxLjk5LC01MTEuNCAtMTE4OC45MywtNzg2LjIgLTE1My4xNSwtOTYuMSAtMjk5LjM4LC0yMDEuOCAtNDM4LjcxLC0zMTcuMSAtMTE1LjU0LC05Ni4zIC0yMjYuNTksLTIwMSAtMzQ1Ljg0LC0yOTIuNSAtMjAuMzYsLTE1LjYgLTMzLjYsLTIzLjEgLTU4Ljg0LC0yNi45IDMzMC4yNSw0NTQuOSA4NTguNzEsNzg1LjcgMTMyMC4yMywxMDkyLjEgMTU2LjIyLDc1LjQgNDI3LjgsMjc3LjcgNTgzLjA2LDM4MS41IDQxMC45LDI0Ny40IDc1Ni43OCw0ODIuNyAxMTkzLjQyLDY5OC41IHoiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PC9jbGlwUGF0aD48bGluZWFyR3JhZGllbnQKICAgICAgIGlkPSJsaW5lYXJHcmFkaWVudDI0NiIKICAgICAgIHNwcmVhZE1ldGhvZD0icGFkIgogICAgICAgZ3JhZGllbnRUcmFuc2Zvcm09Im1hdHJpeCgxMzg4LjUzLC0zMzAxLjUzLDMzMDEuNTMsMTM4OC41Myw5MjU4LjQsMTUzNTkpIgogICAgICAgZ3JhZGllbnRVbml0cz0idXNlclNwYWNlT25Vc2UiCiAgICAgICB5Mj0iMCIKICAgICAgIHgyPSIxIgogICAgICAgeTE9IjAiCiAgICAgICB4MT0iMCI+PHN0b3AKICAgICAgICAgaWQ9InN0b3AyNDIiCiAgICAgICAgIG9mZnNldD0iMCIKICAgICAgICAgc3R5bGU9InN0b3Atb3BhY2l0eToxO3N0b3AtY29sb3I6I2RhM2QyNiIgLz48c3RvcAogICAgICAgICBpZD0ic3RvcDI0NCIKICAgICAgICAgb2Zmc2V0PSIxIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojZWE4MTUxIiAvPjwvbGluZWFyR3JhZGllbnQ+PGNsaXBQYXRoCiAgICAgICBpZD0iY2xpcFBhdGgyNzQiCiAgICAgICBjbGlwUGF0aFVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNzIiCiAgICAgICAgIGQ9Im0gNzY5NC43LDEyODc3LjUgYyAzNjYuMjEsNC41IDcyOS4wMSwtNzUgMTA3Ni4yLC0xODYuOCA2OS40NSwtMjIuNCAxNTcuMDksLTQ1LjUgMjE5LjY2LC04MS4zIDI5LjU5LC05My44IC00Ni45OCwtMTc0LjQgLTQyLjIzLC0yNjUuNSAtMTc2LjIyLDM2LjkgLTM1Mi4yNCw5NS4yIC01MjYuNjUsMTQxLjUgLTIwNS45Myw1OC41IC03MTguODYsMjA4LjUgLTkxMS4yNCwyMDYuNSAtMjYwLjMyLC0yLjYgLTQ2Ny43MywtMTc4LjMgLTYzOC43MiwtMzU1IDE1LjExLDIzIDMxLjQsNDQuOSA0OC40Nyw2Ni41IDE5Ni40LDI0OC4yIDQ1NS44NCw0MzguMSA3NzQuNTEsNDc0LjEgeiIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2NsaXBQYXRoPjxsaW5lYXJHcmFkaWVudAogICAgICAgaWQ9ImxpbmVhckdyYWRpZW50MjgwIgogICAgICAgc3ByZWFkTWV0aG9kPSJwYWQiCiAgICAgICBncmFkaWVudFRyYW5zZm9ybT0ibWF0cml4KDE2NzQuMjEsLTYwMS43NDYsNjAxLjc0NiwxNjc0LjIxLDcxODUuNDQsMTI3NDQuOCkiCiAgICAgICBncmFkaWVudFVuaXRzPSJ1c2VyU3BhY2VPblVzZSIKICAgICAgIHkyPSIwIgogICAgICAgeDI9IjEiCiAgICAgICB5MT0iMCIKICAgICAgIHgxPSIwIj48c3RvcAogICAgICAgICBpZD0ic3RvcDI3NiIKICAgICAgICAgb2Zmc2V0PSIwIgogICAgICAgICBzdHlsZT0ic3RvcC1vcGFjaXR5OjE7c3RvcC1jb2xvcjojMTQxMjEyIiAvPjxzdG9wCiAgICAgICAgIGlkPSJzdG9wMjc4IgogICAgICAgICBvZmZzZXQ9IjEiCiAgICAgICAgIHN0eWxlPSJzdG9wLW9wYWNpdHk6MTtzdG9wLWNvbG9yOiMxZTNjNGEiIC8+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PGcKICAgICB0cmFuc2Zvcm09Im1hdHJpeCgwLjAzMDg5MTI3LDAsMCwtMC4wMzA4OTEyNywwLDYyLjAwMDAwMykiCiAgICAgaWQ9ImcxMCI+PGcKICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMC4xLDAuMSkiCiAgICAgICBpZD0iZzEyIj48ZwogICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMjMxMjksMS4yMzEyOSkiCiAgICAgICAgIGlkPSJnMTQiPjxwYXRoCiAgICAgICAgICAgaWQ9InBhdGgxNiIKICAgICAgICAgICBzdHlsZT0iZmlsbDojZGQxZTI2O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgIGQ9Ik0gMCwxNjMwMC4zIEggMTYzMDAuMyBWIDAgSCAxNjAzMC43IDE0OTI4LjggMTA1MzAuNiA5OTAyLjE1IDc2NzkuNzEgNzE4OS41MSA2NDA4LjgyIDU3MTUuMDIgMzUyNyAxMzQ5LjI3IDI5MC4yMTMgMCB2IDE2MzAwLjMiCiAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxOCIKICAgICAgICAgc3R5bGU9ImZpbGw6IzQ3MjAyODtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMjMyNy4yLDUyNDEuNCBjIDEyOSwtMS41IDEwNDguMiwtMTguNiAxMDg0LjQsLTQxLjQgLTEyNy42LC0yMTUuMSAtMzIxLjMsLTM5MS41IC00NTUuOSwtNjAzLjUgLTMzLjIsMC42IC03NC40LDYuMyAtMTA2LjEsLTMuMSAtMjI0LjgsLTMxLjMgLTI0Ni4zLC0xNDkuOSAtMzc4LjEsLTE5My4yIC0zLjQsMjEuOSAtOC41LDQzLjUgLTEzLjIsNjUuMiAtNDUuNiwyNTguNCAtODkuMyw1MTcgLTEzMS4xLDc3NiIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48ZwogICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMTQ4ODMsMS4xNDg4MykiCiAgICAgICAgIGlkPSJnMjAiPjxwYXRoCiAgICAgICAgICAgaWQ9InBhdGgyMiIKICAgICAgICAgICBzdHlsZT0iZmlsbDojMWIxYjFkO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgIGQ9Im0gMTAyMjcuMywxNjI5MC42IGMgNjMuMyw5LjQgMTI1LjYsLTIxLjMgMTc1LjgsLTU4LjEgMTgwLjMsLTEzMi4xIDMyMC4xLC0zODMgMzQ5LjIsLTYwMy40IDguNSwtNjQuMSA2LC0xMjYuNyAtOC43LC0xODkuNyAtNzAuNSwyMi42IC0xNDAuNSw4Mi4zIC0yMDkuNSwxMTQuOCAtMjIwLjUsMTA0IC00NDEuNywxOTEuNSAtNjc3LjI4LDI1NS4xIC03MS45OCwxNTQuMyAtMTc1LjY2LDI3NyAtMzA1LjcsMzg0LjkgMjIwLjMxLDU5LjYgNDU2LjM4LDQzLjkgNjc2LjE4LDk2LjQiCiAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNCIKICAgICAgICAgc3R5bGU9ImZpbGw6IzQ3MjAyODtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMjQyLjEsMTQ0OC4zIGMgNTMuMTksLTkyIDcxLjY4LC0yMzUuNyAxMDEuNDcsLTM0MC41IEwgMTUyOC44NCw0NjguODAxIEMgMTU3Mi4zMiwzMTMuMjAzIDE2MDkuMTksMTUyLjkwMiAxNjYxLjM0LDAgSCAzNTcuMzM2IGMgMjAyLjM3MSwzODIuMjAzIDQyMC42MDIsNzU1LjEwMiA2NTQuNjk0LDExMTguOCA3MC44NSwxMDkuMSAxNDAuMzksMjM1LjQgMjMwLjA3LDMyOS41IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4yMTA5NCwxLjIxMDk0KSIKICAgICAgICAgaWQ9ImcyNiI+PHBhdGgKICAgICAgICAgICBpZD0icGF0aDI4IgogICAgICAgICAgIHN0eWxlPSJmaWxsOiM5NDE5MzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0iTSAxNTU3My40LDEyMTguNzIgQyAxNTc2Mi42LDEwNDIuMjUgMTU5NzgsNTkxLjE5MyAxNjEwNS45LDM1NC40MzcgMTYxNjkuNiwyMzYuNjc2IDE2MjQwLjcsMTE5LjkwOSAxNjMwMCwwIGggLTExMjAuNCBjIDQ0LjEsMTAyLjgxMiA3Ni45LDIxNS43ODMgMTEzLjEsMzIxLjgxNyA5OS43LDI5Ni45NTcgMTkzLjMsNTk1Ljk4MSAyODAuNyw4OTYuOTAzIgogICAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PC9nPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4xOTY4OCwxLjE5Njg4KSIKICAgICAgICAgaWQ9ImczMCI+PHBhdGgKICAgICAgICAgICBpZD0icGF0aDMyIgogICAgICAgICAgIHN0eWxlPSJmaWxsOiMxYTNkNDc7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSA2OTc2LjgyLDE1NjI3LjQgYyA2MC43NSw0My43IDE0OC4yNiwxNjcuNSAyMTEuNzIsMjI3LjEgMzM3LDMxNi4zIDgyNS4xNyw0NDUuNSAxMjc4Ljk5LDQyOC43IDM5Ni45NCwtMTQuOCA4MDIuNzUsLTE0NS41IDExMDkuMTMsLTQwMy45IDg3Ljg5LC03NC4xIDE2MiwtMTU4LjkgMjQwLjA0LC0yNDIuNyAtMjEwLjk3LC01MC40IC00MzcuNTYsLTM1LjMgLTY0OS4wMiwtOTIuNiAtMzUuMDksMjIuMSAtNzAuNDMsNDMuNiAtMTA2LjE5LDY0LjQgLTM0OS44MywyMDMuNyAtNzA0LjUsMjQ5LjggLTEwOTUuMTgsMTQ3IC0xNDAuMzIsLTUzLjQgLTI2NS4yNywtMTIzLjMgLTM5MS4wNCwtMjA0LjUgLTEzNC44NSwzOC4xIC0yODcuMTUsNTYuOSAtNDI2Ljc0LDY3LjcgLTUxLjk5LDQgLTEwNC45OSwxIC0xNTYuNjQsNyBsIC0xNS4wNywxLjgiCiAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PGcKICAgICAgICAgdHJhbnNmb3JtPSJzY2FsZSgxLjE1Njk2LDEuMTU2OTYpIgogICAgICAgICBpZD0iZzM0Ij48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMzYiCiAgICAgICAgICAgc3R5bGU9ImZpbGw6I2IxMWUyYTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICBkPSJtIDEyODA3LjMsMjcxMS4wNiBjIDY5LjksLTU3LjU2IDQ0NiwtMTYyLjkyIDU1Ny45LC0yMDEuNDcgMTAwMi4yLC0zNDQuODcgMjAxMC41LC03MDkuMDEgMjkzNC44LC0xMjM0LjAxIC05MS40LC0zMTQuOTYgLTE4OS40LC02MjcuOTM2IC0yOTMuOCwtOTM4Ljc0NyBDIDE1OTY4LjQsMjI1Ljg1MSAxNTkzNCwxMDcuNjA5IDE1ODg3LjgsMCBoIC00NjgwLjcgYyAxODkuOCwyMzguMzgzIDM2MC4yLDQ4OS4zODQgNTI5LjQsNzQyLjU0OSA0MzMuMyw2NDguMDgxIDc3Ny42LDEyNDIuOTExIDEwNzAuOCwxOTY4LjUxMSIKICAgICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDM4IgogICAgICAgICBzdHlsZT0iZmlsbDojMWIxYjFkO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDYwNjkuODMsMTYyODMuNCBjIDg3LjQ3LC0xMDkuOSAyNDguODgsLTIwMy44IDM2MC41OSwtMjkxLjEgMzg0LjMyLC0zMDIuMSA3NzYuMDQsLTU5NC4yIDExNzUuMTQsLTg3Ni40IGwgNDkzLjU4LC0zNDEuNSBjIDYyLjUsLTQ0LjEgMTM2LjY1LC04Ny43IDE5My4zOCwtMTM4LjcgLTQ2MS41MiwtMzA2LjQgLTk4OS45OCwtNjM3LjIgLTEzMjAuMjMsLTEwOTIuMSAtMTMyLjExLC0xNTcuOCAtMjU3LjY3LC0zMjQuNyAtMzI4LjczLC01MTkuOSAtMTY3LjUsLTQ2MCAtMTE4LjcsLTE1NDYuMyAtNzQuMDEsLTIwNDYgNy42LC04NC45IDE4LjgzLC0xNjkuMyAyOC4zMiwtMjUzLjkgMzMuODksLTgxLjMgNDIuMiwtMTk5LjIgNTguMzMsLTI4Ni43IDM3LjY1LC0yMDQuMSA3My44OSwtNDA4LjMgMTE5LjczLC02MTAuOCA0Mi45NywtMTI4LjkgNTUuOCwtMjc3LjggODYuNDQsLTQxMS4yIDI3LjQ4LC0xMTkuNiA3My43NCwtMjQxLjMgOTIuNDQsLTM2MS44IDEzOS43NSwtNjM0LjQgMzYyLjQ4LC0xMjEzLjUgNzcwLjM3LC0xNzI1LjggODkuNCwtMTEyLjIgMTg4LjMsLTIxMi45IDI4My42MywtMzE5LjYgLTAuMjEsLTEwMC45IDAuNjEsLTIwMiAtMS4xMSwtMzAyLjkgLTI1MS4wNSwxODAuMSAtNDg5LjU3LDQwNi41IC03MDUuMDEsNjI3LjcgLTMzLjczLDM1LjEgLTY3LjEzLDcwLjYgLTEwMC4xOSwxMDYuMyAtMzMuMDgsMzUuNyAtNjUuODMsNzEuOCAtOTguMjUsMTA4LjEgLTMyLjQxLDM2LjMgLTY0LjUsNzMgLTk2LjI1LDEwOS45IC0zMS43NSwzNi45IC02My4xNyw3NC4xIC05NC4yNSwxMTEuNiAtMzEuMDgsMzcuNSAtNjEuOCw3NS4yIC05Mi4xOCwxMTMuMyAtMzAuMzgsMzggLTYwLjQyLDc2LjQgLTkwLjExLDExNSAtMjkuNjksMzguNiAtNTkuMDIsNzcuNCAtODgsMTE2LjYgLTI4Ljk4LDM5LjEgLTU3LjYxLDc4LjUgLTg1Ljg3LDExOC4xIC0yOC4yNiwzOS43IC01Ni4xNiw3OS42IC04My42OSwxMTkuNyAtMjcuNTMsNDAuMiAtNTQuNyw4MC42IC04MS40OSwxMjEuMyAtMjYuNzksNDAuNiAtNTMuMjIsODEuNSAtNzkuMjcsMTIyLjcgLTI2LjA2LDQxLjEgLTUxLjczLDgyLjUgLTc3LjAzLDEyNC4xIC0yNS4yOSw0MS42IC01MC4yMiw4My40IC03NC43NSwxMjUuNSAtMjQuNTQsNDIgLTQ4LjY5LDg0LjMgLTcyLjQ0LDEyNi44IC0yMy43Nyw0Mi41IC00Ny4xNSw4NS4yIC03MC4xNCwxMjguMSAtMjIuOTcsNDMgLTQ1LjU3LDg2LjEgLTY3Ljc5LDEyOS41IC0yMi4yLDQzLjMgLTQ0LDg2LjggLTY1LjQsMTMwLjYgLTIxLjQxLDQzLjcgLTQyLjQxLDg3LjYgLTYzLjAyLDEzMS43IC0yMC42LDQ0LjEgLTQwLjgxLDg4LjUgLTYwLjYyLDEzMi45IC0xOS44LDQ0LjUgLTM5LjE5LDg5LjIgLTU4LjE4LDEzNCAtMTguOTgsNDQuOSAtMzcuNTUsODkuOSAtNTUuNzIsMTM1IC0xOC4xNiw0NS4yIC0zNS45MSw5MC42IC01My4yNSwxMzYuMSAtMTcuMzMsNDUuNSAtMzQuMjYsOTEuMSAtNTAuNzYsMTM2LjkgLTE2LjUyLDQ1LjggLTMyLjYxLDkxLjggLTQ4LjI3LDEzNy45IC0xNS42OCw0Ni4xIC0zMC45Miw5Mi40IC00NS43NiwxMzguNyAtMTQuODMsNDYuNCAtMjkuMjIsOTIuOSAtNDMuMTksMTM5LjYgLTEzLjk4LDQ2LjYgLTI3LjU0LDkzLjQgLTQwLjY3LDE0MC4zIC0xMy4xMiw0Ni45IC0yNS44MSw5My45IC0zOC4wOSwxNDEgLTEyLjI2LDQ3LjEgLTI0LjExLDk0LjMgLTM1LjUzLDE0MS43IC0xMS40MSw0Ny4zIC0yMi4zOSw5NC43IC0zMi45MywxNDIuMyAtMTAuNTQsNDcuNSAtMjAuNjUsOTUuMiAtMzAuMzIsMTQyLjkgLTkuNjksNDcuNyAtMTguOTIsOTUuNSAtMjcuNzMsMTQzLjQgLTI5My42OSwxNjI5LjQgLTk0LjE2LDM0NjAuOSA4NjguMjgsNDg0OS4xIgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoNDAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNjYzU5MmY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNjk1NC44MSw5MDUzLjMgYyAtNTguMzUsNC41IC0xMTUuMjIsOS45IC0xNzAuMTgsMzEuNSAtMzM0LjcsMTMxLjMgLTUyNS45Myw1MzMuMyAtNjU5LjU3LDg0Mi44IC0xNzAuNzgsMzk1LjYgLTUxOS4zMiwxMzgwLjEgLTM0Ny4wMiwxNzg4LjQgMjQuMjcsNTcuNSA2MS43NCwxMDQuNiAxMjEuMzgsMTI3LjMgMTAzLjEsMzkuNCAyMTAuNDUsOS44IDMwNS4xNywtMzUuNCAxMDkuNjcsLTIyMC40IDIwNy42OSwtNTA5IDI3OS45OCwtNzQ1LjkgNDYuOTgsLTExMCA2My40NSwtMjMxLjYgMTA2Ljc3LC0zNDMgbCA2LjUzLDQuOCBjIDMzLjg5LC04MS4zIDQyLjIsLTE5OS4yIDU4LjMzLC0yODYuNyAzNy42NSwtMjA0LjEgNzMuODksLTQwOC4zIDExOS43MywtNjEwLjggNDIuOTcsLTEyOC45IDU1LjgsLTI3Ny44IDg2LjQ0LC00MTEuMiAyNy40OCwtMTE5LjYgNzMuNzQsLTI0MS4zIDkyLjQ0LC0zNjEuOCIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDQyIgogICAgICAgICBzdHlsZT0iZmlsbDojYjMzNDIyO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDY0MDUuNzksOTk1Mi45IGMgLTUzLjUzLDczIC04Ny44MywxNTUuOCAtMTE2LjUyLDI0MS4yIC01Ni45NiwxNjkuNSAtMzc0LjMsMTIzMi4zIC0zMjUuMjYsMTMzMC4xIDQuMjksMC41IDguNTgsMS4xIDEyLjkxLDEuNCA0Mi4xLDIuOSA5MS40NywtMjAuOSAxMjkuMjEsLTM4LjUgMTU3LjI2LC03My4zIDIyNS45OCwtMjAyLjEgMzA1LjQ0LC0zNDYuOSAxNy4yOSwtMzEuNCAzMC4xMiwtNjUuNSA1OC4xNywtODkuMSBsIDE0LjgzLDEwLjkgYyA0Ni45OCwtMTEwIDYzLjQ1LC0yMzEuNiAxMDYuNzcsLTM0MyBsIDYuNTMsNC44IGMgMzMuODksLTgxLjMgNDIuMiwtMTk5LjIgNTguMzMsLTI4Ni43IDM3LjY1LC0yMDQuMSA3My44OSwtNDA4LjMgMTE5LjczLC02MTAuOCAtMTQ5Ljg1LDY2LjggLTI0OC42NCwyMjAgLTQwMi45NywyOTMgNi41NSwtNTYuMyAyMC4yOSwtMTExLjIgMzIuODMsLTE2Ni40IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoNDQiCiAgICAgICAgIHN0eWxlPSJmaWxsOiM1ZjFkMmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNTE4Ni4yLDMwOTUuMyBjIDExNy4xMSwyMS40IDQ1My41NCwxNTIuNyA1NzIuNTcsMjA2LjggMjAwLjM5LC0zNDguNSA0MDQuMjcsLTY5NSA2MTEuNjgsLTEwMzkuMyA4My44MywtMTM5LjMgMTcyLjA5LC0zMTcuOCAyNzAuMDMsLTQ0MS44IGwgMC44LC01LjQgQyA2NTY4LjE0LDE3ODkuNSA2MTY3LjUxLDE0NjguNSA2MTA0LjA1LDE0MDMuMSA2Mzg0LjM1LDkxNC4zMDEgNjcwOS4yOSw0NTcuNzAzIDcwMzYuODMsMCBIIDQzNDIuNzUgMTY2MS4zNCBjIC01Mi4xNSwxNTIuOTAyIC04OS4wMiwzMTMuMjAzIC0xMzIuNSw0NjguODAxIEwgMTM0My41NywxMTA3LjggYyAtMjkuNzksMTA0LjggLTQ4LjI4LDI0OC41IC0xMDEuNDcsMzQwLjUgNzUwLjA4LDUzNS41IDE2MTguMyw4NDYuNCAyNDgxLjk4LDExNDUuOCA0ODYuMTIsMTcwLjcgOTczLjQ5LDMzNy44IDE0NjIuMTIsNTAxLjIiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg0NiIKICAgICAgICAgc3R5bGU9ImZpbGw6IzZmMmYyMjtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA1MTg2LjIsMzA5NS4zIGMgMTE3LjExLDIxLjQgNDUzLjU0LDE1Mi43IDU3Mi41NywyMDYuOCAyMDAuMzksLTM0OC41IDQwNC4yNywtNjk1IDYxMS42OCwtMTAzOS4zIDgzLjgzLC0xMzkuMyAxNzIuMDksLTMxNy44IDI3MC4wMywtNDQxLjggbCAwLjgsLTUuNCBjIC03My4xNCwtMjYuMSAtNDczLjc3LC0zNDcuMSAtNTM3LjIzLC00MTIuNSBsIC01LjgsLTAuNSBjIC00MC42LDExNS40IC0yMDIuMDYsMzQ1IC0yNzMuNjIsNDczIC0yMjIuNjEsMzk4LjMgLTQ0Ny4yMyw4MDUuNCAtNjM4LjQzLDEyMTkuNyIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDQ4IgogICAgICAgICBzdHlsZT0iZmlsbDojYjExZTJhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDYwOTguMjUsMTQwMi42IDUuOCwwLjUgQyA2Mzg0LjM1LDkxNC4zMDEgNjcwOS4yOSw0NTcuNzAzIDcwMzYuODMsMCBIIDQzNDIuNzUgYyAxNjcuMDMsMTQ2LjQwMiAzNTAuNTMsMjc2LjAwNCA1MjMuOTUsNDE0LjcwMyBMIDYwOTguMjUsMTQwMi42IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxnCiAgICAgICAgIGlkPSJnNTAiPjxnCiAgICAgICAgICAgY2xpcC1wYXRoPSJ1cmwoI2NsaXBQYXRoNTYpIgogICAgICAgICAgIGlkPSJnNTIiPjxnCiAgICAgICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMDEyNjIsMS4wMTI2MikiCiAgICAgICAgICAgICBpZD0iZzU4Ij48cGF0aAogICAgICAgICAgICAgICBpZD0icGF0aDY2IgogICAgICAgICAgICAgICBzdHlsZT0iZmlsbDp1cmwoI2xpbmVhckdyYWRpZW50NjQpO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgICAgICBkPSJtIDEzNjM1LDE2MzAwIGMgMjAuMiwtMjYuMSA0NSwtNTIuOSA2MC42LC04MS45IDk5Ny4zLC0xMjA0LjUgMTIwOC41LC0yOTcxLjYgMTA2Ni44LC00NDc4LjYgLTE4OS4zLC0yMDE1LjY1IC0xMDk0LjksLTM3MjMuMSAtMjY1Ni42LC01MDEzLjQxIC0yNy41LC0yMi43MSAtNTUuMSwtNDQuNzMgLTg0LjMsLTY1LjM3IC0yLDQ3LjEgLTAuOSw5Ni45NyAtMTAuNSwxNDMuMDkgbCAtMi4zLDM5LjYgYyA0LjksNjcuODQgLTEuMywxMzYuOTcgLTQuNywyMDQuOTEgMzcuMyw2Ny40NSAxMTkuOCwxMzcuNDcgMTcxLjYsMTk3LjEyIDgyLjksOTYuNDggMTYxLjQsMTk2LjUyIDIzNS4xLDMwMC4yMSAyMzYuMywzMzMuNzggNDAxLjksNzI0LjQ1IDUxNi40LDExMTUuNTEgMzguMSwxMjkuNzcgNjMuNSwyNjMuMTggMTAzLDM5Mi40NSAzMi45LDE4MS40MSA4NCwzNjguNTUgMTM1LjMsNTQ1LjgxIDQ5LjIsMjAxLjc1IDk0LjUsNDExLjQ4IDE2OS4xLDYwNS41OCAxNy41LDE1NiAxNC44LDMxNS42IDE2LjIsNDcyLjUgMi43LDI5OC42IC0zLjEsNTk4IDMuMyw4OTYuNCAtMTIuNSw4OS45IC02LjQsMTkwLjEgLTYuOCwyODEgbCAtMi4xLDUxOC41IGMgLTIsMy42IC0zLjUsNy43IC02LjMsMTAuOSAtODIsOTcuMiAtMTQyLjQsMjEyLjIgLTIxNi4zLDMxNi43IC0xMzIuMSwxODYgLTI3Mi44LDM2NS4zIC00MjIsNTM4IDkzLjIsLTQyLjIgMjA5LjksLTIyMy4zIDI3My4yLC0zMDguMiAyMS41LDI4LjcgNTIuNCw2MS43IDY4LjMsOTMuMyAzNyw3My45IC0yMzIuOSwyMzYuNiAtMjUyLjgsMzE5LjQgLTk0LjIsMTE3LjQgLTI0NC4zLDIyMC45IC0zNjAuNCwzMTcuNyAtMzkzLjQsMzMyIC04MDAsNjQ3LjMgLTEyMTkuNCw5NDUuNyA2My45LDgwIDMxOC45LDIyNi40IDQxOS4xLDI5NCBsIDU5NSw0MDcuNSBjIDQ3Mi4yLDMyNy4zIDkzMy45LDY3Mi43IDE0MTEuNSw5OTEuNiIKICAgICAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PC9nPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDY4IgogICAgICAgICBzdHlsZT0iZmlsbDojZjBhOTZjO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDE0MTc2LjEsMTMwMzQuNCBjIDU2LjgsLTk0LjYgLTE4MywtMTA3NS44IC0xNDAuMSwtMTI2MC40IDUyLjIsMTkuNyAxMTMsMjUuOCAxNjUuNCwyLjQgMzMsLTE0LjggNTIuNywtMzkuMiA2NSwtNzIuOCA4Mi44LC0yMjcuNyAtMTM1LjIsLTEyODkuMyAtMjE2LjUsLTE1NjAuNCAtMjUsLTgxLjIgLTUzLjUsLTE2MS4zIC04NS40LC0yNDAuMSAtMzEuOCwtNzguOCAtNjcsLTE1Ni4yIC0xMDUuNCwtMjMyLjEgLTg5LjMsLTE3Ni41IC0yNDcuMiwtNDQ2LjMgLTQ0Ni4yLC01MTMuNiAtNzUuMSwtMjUuNCAtMTQ1LjQsLTE4LjIgLTIxOC4zLDEwLjUgMzMuMywxODMuNyA4NSwzNzMuMiAxMzcsNTUyLjcgNDkuOCwyMDQuMyA5NS43LDQxNi43IDE3MS4yLDYxMy4yIDE3LjgsMTU4IDE1LDMxOS43IDE2LjQsNDc4LjUgMi44LDMwMi40IC0zLjEsNjA1LjUgMy40LDkwNy43IDExLjEsODYuNiA1LjIsMTc4IDQuOCwyNjUuMyAyODkuOSwyMjkgNTI5LjgsNzA5LjYgNjQ4LjcsMTA0OS4xIgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoNzAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNjYzU5MmY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTQwNzguNCwxMTUzOC44IGMgMTUuNiwtMTIuNyAzMC45LC0zMC4yIDQyLjEsLTQ3LjEgMTE1LjgsLTE3NC41IC0yLjEsLTU4Ni4yIC00Ni4zLC03NzguMyBsIC00LjYsLTIwLjMgLTEwLjEsLTQuOSBjIC0yLjQsNy45IC01LjgsMTguMyAtNy42LDI2LjcgLTExLjQsNTQuNCAtOS42LDExNS4zIC0xNS4zLDE3MC45IC0xOS45LDE5NSAtNzIuMiw0NzkuMSA0MS44LDY1MyIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDcyIgogICAgICAgICBzdHlsZT0iZmlsbDojY2M1OTJmO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDEzNTAyLjgsMTAzMzMuOCBjIDQwLjUsMzguMSAxNDkuNiw2OTcuOCAxNzEuNyw4MDcuOCAyNS4yLC04MCA1NC42LC0xNTQuNyA5Mi4zLC0yMjkuNiA5Ni45LC0xOTIuNyAyNDYuNCwtMzk5LjcgMTM0LjIsLTYyMC4xIC03MywtMTQzLjYgLTIyMi43LC0yMDEuMSAtMzI4LjMsLTMxMyAtNzkuNiwtODQuNSAtMTIxLjcsLTE5MS43IC0yMTguMSwtMjYwLjcgbCAtMjMsMi40IGMgNDkuOCwyMDQuMyA5NS43LDQxNi43IDE3MS4yLDYxMy4yIgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoNzQiCiAgICAgICAgIHN0eWxlPSJmaWxsOiMxYjFiMWQ7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTQxNzYuMSwxMzAzNC40IGMgNTYuOCwtOTQuNiAtMTgzLC0xMDc1LjggLTE0MC4xLC0xMjYwLjQgLTIyMC4zLC0xNDguNyAtMjk3LjIsLTM4NiAtMzYxLjUsLTYzMi40IC0yMi4xLC0xMTAgLTEzMS4yLC03NjkuNyAtMTcxLjcsLTgwNy44IDE3LjgsMTU4IDE1LDMxOS43IDE2LjQsNDc4LjUgMi44LDMwMi40IC0zLjEsNjA1LjUgMy40LDkwNy43IDExLjEsODYuNiA1LjIsMTc4IDQuOCwyNjUuMyAyODkuOSwyMjkgNTI5LjgsNzA5LjYgNjQ4LjcsMTA0OS4xIgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4wMTI2MiwxLjAxMjYyKSIKICAgICAgICAgaWQ9Imc3NiI+PHBhdGgKICAgICAgICAgICBpZD0icGF0aDc4IgogICAgICAgICAgIHN0eWxlPSJmaWxsOiMyMTJiMzE7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSAxMzYzNSwxNjMwMCBjIDIwLjIsLTI2LjEgNDUsLTUyLjkgNjAuNiwtODEuOSAwLjYsLTEzIDAuOCwtMjIuOCA1LjQsLTM1LjEgMjQuMSwtNjQuOSA3MS44LC0xMzIuNCAxMDUuNywtMTk0LjEgNjQsLTExNi41IDEyMS40LC0yMzUuOCAxNjcuMSwtMzYwLjggMjk3LjcsLTgxMyAyNDMuNSwtMTkyOC44IDI1LjYsLTI3NTYuMiAtMTE3LjQsLTMzNS4zIC0zNTQuNCwtODA5LjkgLTY0MC42LC0xMDM2IDAuNCwtODYuMiA2LjIsLTE3Ni41IC00LjgsLTI2MiAtMTIuNSw4OS45IC02LjQsMTkwLjEgLTYuOCwyODEgbCAtMi4xLDUxOC41IGMgLTIsMy42IC0zLjUsNy43IC02LjMsMTAuOSAtODIsOTcuMiAtMTQyLjQsMjEyLjIgLTIxNi4zLDMxNi43IC0xMzIuMSwxODYgLTI3Mi44LDM2NS4zIC00MjIsNTM4IDkzLjIsLTQyLjIgMjA5LjksLTIyMy4zIDI3My4yLC0zMDguMiAyMS41LDI4LjcgNTIuNCw2MS43IDY4LjMsOTMuMyAzNyw3My45IC0yMzIuOSwyMzYuNiAtMjUyLjgsMzE5LjQgLTk0LjIsMTE3LjQgLTI0NC4zLDIyMC45IC0zNjAuNCwzMTcuNyAtMzkzLjQsMzMyIC04MDAsNjQ3LjMgLTEyMTkuNCw5NDUuNyA2My45LDgwIDMxOC45LDIyNi40IDQxOS4xLDI5NCBsIDU5NSw0MDcuNSBjIDQ3Mi4yLDMyNy4zIDkzMy45LDY3Mi43IDE0MTEuNSw5OTEuNiIKICAgICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDgwIgogICAgICAgICBzdHlsZT0iZmlsbDojZjBhOTZjO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDEyOTUwLjYsMTM1MTIgYyAyMDcuNSwtMTczLjUgMzY1LjcsLTM4Ny42IDU1NC4xLC01NzguNiBsIDguOSwtNDAzLjggYyAtMi4xLDMuNyAtMy42LDcuOCAtNi40LDExIC04Myw5OC40IC0xNDQuMiwyMTUgLTIxOSwzMjAuNyAtMTMzLjgsMTg4LjQgLTI3Ni4zLDM3MCAtNDI3LjQsNTQ0LjggOTQuNCwtNDIuNyAyMTIuNiwtMjI2LjEgMjc2LjcsLTMxMiAyMS44LDI5IDUzLDYyLjQgNjkuMSw5NC40IDM3LjUsNzQuOCAtMjM1LjgsMjM5LjYgLTI1NiwzMjMuNSIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDgyIgogICAgICAgICBzdHlsZT0iZmlsbDojOTQxOTMwO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDY2NjguMzIsNTI0OC40IDc3My43MywxLjMgYyAxMzQuNTksLTAuMiAyNzMuOCw3LjUgNDA3LjQ0LC01LjcgbCAxNS40OCwtNy44IGMgLTQxLjQxLC0yNjcuNiAtODguNzEsLTUzNC4xIC0xNDEuOSwtNzk5LjYgMzExLjEyLC0xODkuMyA3MDMuNzEsLTY5MSA5MzcuODUsLTk3Ny43IDM2MS4zNywtNDQxLjcgNzIyLjExLC04ODkuMiAxMDY0LjMzLC0xMzQ1LjkgMTMwLjEyLC0xNzMuNiAyNDQuNiwtMzU4LjkgMzc0Ljk1LC01MzIuMSAtMTYuNCwtMjcgLTMzLjMsLTUxLjUgLTUzLC03Ni4xIC05MS44NSwtMTE1LjEgLTE5Ni43OCwtMjI5LjEgLTI3OS44NSwtMzQ5LjkgTCA4ODUyLjM2LDAgSCA3ODkxLjEgNzAzNi44MyBjIC0zMjcuNTQsNDU3LjcwMyAtNjUyLjQ4LDkxNC4zMDEgLTkzMi43OCwxNDAzLjEgNjMuNDYsNjUuNCA0NjQuMDksMzg2LjQgNTM3LjIzLDQxMi41IGwgLTAuOCw1LjQgYyAtOTcuOTQsMTI0IC0xODYuMiwzMDIuNSAtMjcwLjAzLDQ0MS44IC0yMDcuNDIsMzQ0LjMgLTQxMS4zMSw2OTAuOCAtNjExLjY4LDEwMzkuMyA0MC41LDE0OS40IDE3NC4yNSwzNzMuMSAyNDMuMjIsNTIzLjUgbCAzNzguMTgsODE0IGMgOTMuMjIsMjAzLjEgMTgwLjE1LDQxMy4xIDI4OC4xNSw2MDguOCIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDg0IgogICAgICAgICBzdHlsZT0iZmlsbDojZGY3ZTNhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDYxMDQuMDUsMTQwMy4xIGMgNjMuNDYsNjUuNCA0NjQuMDksMzg2LjQgNTM3LjIzLDQxMi41IEMgNzA0MS4xNSwxMTk3LjYgNzQzMS45OSw1NzYuODAxIDc4OTEuMSwwIGggLTg1NC4yNyBjIC0zMjcuNTQsNDU3LjcwMyAtNjUyLjQ4LDkxNC4zMDEgLTkzMi43OCwxNDAzLjEiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg4NiIKICAgICAgICAgc3R5bGU9ImZpbGw6I2IxYWI5ZDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA3MjEyLjYyLDQ1NjMuMyBjIDE0MS44NywyOC45IDM0Ni43MSwtNy41IDQ2My43LC0xMDAuOSAyLjkyLC0yLjMgNS4yMiwtNS40IDcuODMsLTguMSBsIDM4LjkyLC0xNy43IGMgMzExLjEyLC0xODkuMyA3MDMuNzEsLTY5MSA5MzcuODUsLTk3Ny43IDM2MS4zNywtNDQxLjcgNzIyLjExLC04ODkuMiAxMDY0LjMzLC0xMzQ1LjkgMTMwLjEyLC0xNzMuNiAyNDQuNiwtMzU4LjkgMzc0Ljk1LC01MzIuMSAtMTYuNCwtMjcgLTMzLjMsLTUxLjUgLTUzLC03Ni4xIC05MS44NSwtMTE1LjEgLTE5Ni43OCwtMjI5LjEgLTI3OS44NSwtMzQ5LjkgLTMxNS44OCw0MTUuNCAtNjE5LjYsODQxLjcgLTkzMS42MywxMjYwLjMgLTE4Ni40NCwyNTAuMSAtMzkyLjQzLDQ5My42IC01NjYuMzgsNzUxLjkgbCAtNiwxLjMgYyAtNzkuNTQsMTM3LjUgLTE5OC43MSwyNzAuNSAtMjk2LjA4LDM5Ni44IC0xNzguMDcsMjI5LjEgLTM1NC4yNiw0NTkuNSAtNTI4LjU3LDY5MS41IC03MS41LDk0IC0xNzQuNjEsMjAxLjggLTIyNi4wNywzMDYuNiIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDg4IgogICAgICAgICBzdHlsZT0iZmlsbDojZWZlY2U3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDc2ODQuMTUsNDQ1NC4zIDM4LjkyLC0xNy43IGMgMzExLjEyLC0xODkuMyA3MDMuNzEsLTY5MSA5MzcuODUsLTk3Ny43IDM2MS4zNywtNDQxLjcgNzIyLjExLC04ODkuMiAxMDY0LjMzLC0xMzQ1LjkgMTMwLjEyLC0xNzMuNiAyNDQuNiwtMzU4LjkgMzc0Ljk1LC01MzIuMSAtMTYuNCwtMjcgLTMzLjMsLTUxLjUgLTUzLC03Ni4xIC0yODMuMDEsNDQyLjggLTYxMC44NCw4NTYuMyAtOTM0LjcyLDEyNjkuNSAtMTY3Ljk2LDIxNC4zIC0zMjkuODgsNDQyLjggLTUxNyw2NDAuNiAtMTgxLjY1LDIxOS4zIC0zNjEuNjYsNDQxLjggLTU1My4zMyw2NTIuNSAtNTkuNjQsNjUuNiAtMzUxLjI1LDMzNC4zIC0zNTgsMzg2LjkiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg5MCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2EzOTQ4YjtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA3MjEyLjYyLDQ1NjMuMyBjIDE0MS44NywyOC45IDM0Ni43MSwtNy41IDQ2My43LC0xMDAuOSAyLjkyLC0yLjMgNS4yMiwtNS40IDcuODMsLTguMSA2Ljc1LC01Mi42IDI5OC4zNiwtMzIxLjMgMzU4LC0zODYuOSAxOTEuNjcsLTIxMC43IDM3MS42OCwtNDMzLjIgNTUzLjMzLC02NTIuNSAtOTkuMjIsLTkyIC0yMzIuNjEsLTE1My40IC0zMjYuMTQsLTI0Ny44IGwgLTYsMS4zIGMgLTc5LjU0LDEzNy41IC0xOTguNzEsMjcwLjUgLTI5Ni4wOCwzOTYuOCAtMTc4LjA3LDIyOS4xIC0zNTQuMjYsNDU5LjUgLTUyOC41Nyw2OTEuNSAtNzEuNSw5NCAtMTc0LjYxLDIwMS44IC0yMjYuMDcsMzA2LjYiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGg5MiIKICAgICAgICAgc3R5bGU9ImZpbGw6IzVmMWQyYztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA2NjY4LjMyLDUyNDguNCA3NzMuNzMsMS4zIGMgMTM0LjU5LC0wLjIgMjczLjgsNy41IDQwNy40NCwtNS43IGwgMTUuNDgsLTcuOCBjIC00MS40MSwtMjY3LjYgLTg4LjcxLC01MzQuMSAtMTQxLjksLTc5OS42IGwgLTM4LjkyLDE3LjcgYyAtMi42MSwyLjcgLTQuOTEsNS44IC03LjgzLDguMSAtMTE2Ljk5LDkzLjQgLTMyMS44MywxMjkuOCAtNDYzLjcsMTAwLjkgNTEuNDYsLTEwNC44IDE1NC41NywtMjEyLjYgMjI2LjA3LC0zMDYuNiAxNzQuMzEsLTIzMiAzNTAuNSwtNDYyLjQgNTI4LjU3LC02OTEuNSA5Ny4zNywtMTI2LjMgMjE2LjU0LC0yNTkuMyAyOTYuMDgsLTM5Ni44IC0yNTcuMTUsLTIxOS45IC01MjAuODgsLTQzMi42IC03ODAuMiwtNjUwIC0yNzguNjcsLTIzMy43IC01NTUuNjksLTQ3NCAtODQyLjY2LC02OTcuNCAtOTcuOTQsMTI0IC0xODYuMiwzMDIuNSAtMjcwLjAzLDQ0MS44IC0yMDcuNDIsMzQ0LjMgLTQxMS4zMSw2OTAuOCAtNjExLjY4LDEwMzkuMyA0MC41LDE0OS40IDE3NC4yNSwzNzMuMSAyNDMuMjIsNTIzLjUgbCAzNzguMTgsODE0IGMgOTMuMjIsMjAzLjEgMTgwLjE1LDQxMy4xIDI4OC4xNSw2MDguOCIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDk0IgogICAgICAgICBzdHlsZT0iZmlsbDojNDcyMDI4O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDc4NDkuNDksNTI0NCAxNS40OCwtNy44IGMgLTQxLjQxLC0yNjcuNiAtODguNzEsLTUzNC4xIC0xNDEuOSwtNzk5LjYgbCAtMzguOTIsMTcuNyBjIC0yLjYxLDIuNyAtNC45MSw1LjggLTcuODMsOC4xIC0xMTYuOTksOTMuNCAtMzIxLjgzLDEyOS44IC00NjMuNywxMDAuOSAtMjguNTEsMTcuOCAtNDYxLjk5LDU5MC4yIC01MzIuOTIsNjc2LjcgbCA3MzcuOTQsLTEgYyAxNDMuMjksLTAuMSAyODguOTksLTUuMSA0MzEuODUsNSIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48ZwogICAgICAgICBpZD0iZzk2Ij48ZwogICAgICAgICAgIGNsaXAtcGF0aD0idXJsKCNjbGlwUGF0aDEwMikiCiAgICAgICAgICAgaWQ9Imc5OCI+PHBhdGgKICAgICAgICAgICAgIGlkPSJwYXRoMTEwIgogICAgICAgICAgICAgc3R5bGU9ImZpbGw6dXJsKCNsaW5lYXJHcmFkaWVudDEwOCk7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICBkPSJtIDEwOTE3LjksNjA5OS4zIGMgNDgzLjYsMjUzLjYgODY4LDY0NSAxMjM3LjYsMTAzOCAzLjUsLTY4LjggOS44LC0xMzguOCA0LjgsLTIwNy41IGwgMi4zLC00MC4xIGMgLTMsLTE5My4yIDI1LjYsLTM5Mi4xIDQyLjcsLTU4NC42IDMxLjYsLTM1NCA2MC4xLC03MTMuNCAxMjEuOSwtMTA2My43IDQxLjgsLTI1OSA4NS41LC01MTcuNiAxMzEuMSwtNzc2IDQuNywtMjEuNyA5LjgsLTQzLjMgMTMuMiwtNjUuMiAtNTguNSwtODEuMSAtMjIzLjEsLTE4OC4xIC0zMDMuNywtMjY4LjkgLTE4OC41LC0xODguOSAtMzU5LjgsLTQwMy4yIC01MzQuNSwtNjA1LjMgLTM5My4yLC00NTQuNyAtNzY5LC05MzEuOCAtMTEzMy43LC0xNDA5LjcgLTEzNS4xLC0xNzcgLTI2Mi42LC0zNTkuOCAtMzk5LjQsLTUzNS40IC0xMzAuMzUsMTczLjIgLTI0NC44MywzNTguNSAtMzc0Ljk1LDUzMi4xIC0zNDIuMjIsNDU2LjcgLTcwMi45Niw5MDQuMiAtMTA2NC4zMywxMzQ1LjkgLTIzNC4xNCwyODYuNyAtNjI2LjczLDc4OC40IC05MzcuODUsOTc3LjcgNTMuMTksMjY1LjUgMTAwLjQ5LDUzMiAxNDEuOSw3OTkuNiAzMC44MiwxMDUgMzIuNTcsMjY1LjMgNDQuNzksMzc2LjcgMzkuNjUsMzYxLjkgODIuOTgsNzI4LjEgOTcuOTQsMTA5Mi4xIDEuNzIsMTAwLjkgMC45LDIwMiAxLjExLDMwMi45IDU3Ni4yLC01NzIuNSAxMTcyLjA0LC0xMTU0IDIwNDIuMjksLTExNTAuMyAyNzcuNCwxLjEgNjQ0LjksNjAuOSA4NjYuOCwyNDEuNyIKICAgICAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PC9nPjwvZz48cGF0aAogICAgICAgICBpZD0icGF0aDExMiIKICAgICAgICAgc3R5bGU9ImZpbGw6I2ZjZDRhODtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMjE2MC4zLDY5MjkuOCAyLjMsLTQwLjEgYyAtMywtMTkzLjIgMjUuNiwtMzkyLjEgNDIuNywtNTg0LjYgMzEuNiwtMzU0IDYwLjEsLTcxMy40IDEyMS45LC0xMDYzLjcgNDEuOCwtMjU5IDg1LjUsLTUxNy42IDEzMS4xLC03NzYgLTk4LjksNDguOCAtMTIwLjEsMzM0IC0xNDEuMSw0MzIuOCAtMjYuOCwxMjYgLTc4LjIsMjQzLjkgLTEwMS43LDM3MS42IC0zNS43LDE5My4yIC00My40LDM4Ny42IC03MS42LDU4MS4yIC0xNSwxMDIuOCAtNDUuMywyMDYuMiAtNzEsMzA2LjkgLTE4LjMsNzEuNyAtMzQuMiwxNTQgLTY1LjksMjIwLjcgLTM0LDcxLjQgLTEwNC44LDkyLjYgLTE1Mi4yLDE1MSAtMi45LDMuNiAtNS43LDcuMyAtOC41LDExIGwgMzE0LDM4OS4yIgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxnCiAgICAgICAgIGlkPSJnMTE0Ij48ZwogICAgICAgICAgIGNsaXAtcGF0aD0idXJsKCNjbGlwUGF0aDEyMCkiCiAgICAgICAgICAgaWQ9ImcxMTYiPjxwYXRoCiAgICAgICAgICAgICBpZD0icGF0aDEyOCIKICAgICAgICAgICAgIHN0eWxlPSJmaWxsOnVybCgjbGluZWFyR3JhZGllbnQxMjYpO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgICAgZD0ibSAxMDkxNy45LDYwOTkuMyBjIDQ4My42LDI1My42IDg2OCw2NDUgMTIzNy42LDEwMzggMy41LC02OC44IDkuOCwtMTM4LjggNC44LC0yMDcuNSBsIC0zMTQsLTM4OS4yIGMgLTE1MSwtMTY4LjMgLTMwMC4zLC0zMzkuNiAtNDU3LC01MDIuNSAtNTgwLjIsLTYwMy40IC0xMjA0LjksLTExNzIuNCAtMTgyMC42NiwtMTczOS40IC0xNzcuODYsLTE2Mi4yIC0zNTQuNDcsLTMyNS43IC01MjkuODMsLTQ5MC42IC0xMjMuNzUsLTExNi43IC0yNDYuMzQsLTI0MS43IC0zNzcuODksLTM0OS4yIC0yMzQuMTQsMjg2LjcgLTYyNi43Myw3ODguNCAtOTM3Ljg1LDk3Ny43IDUzLjE5LDI2NS41IDEwMC40OSw1MzIgMTQxLjksNzk5LjYgMzAuODIsMTA1IDMyLjU3LDI2NS4zIDQ0Ljc5LDM3Ni43IDM5LjY1LDM2MS45IDgyLjk4LDcyOC4xIDk3Ljk0LDEwOTIuMSAxLjcyLDEwMC45IDAuOSwyMDIgMS4xMSwzMDIuOSA1NzYuMiwtNTcyLjUgMTE3Mi4wNCwtMTE1NCAyMDQyLjI5LC0xMTUwLjMgMjc3LjQsMS4xIDY0NC45LDYwLjkgODY2LjgsMjQxLjciCiAgICAgICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvZz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxMzAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiM5NDE5MzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTM0MTEuNiw1MjAwIGMgMjAxLjIsLTQ2MC44IDQzNC4yLC05MTEuNSA2NTYuNCwtMTM2Mi42IDU4LjMsLTExOC42IDE4Ni4xLC00MzIuMiAyNjQuMywtNTE0LjQgNzUuMywtMTcuMSA0NDMuNSwtMTQ0LjcgNDg1LjMsLTE4Ni40IEMgMTQ0NzguMywyMjk3LjEgMTQwODAsMTYwOC45IDEzNTc4LjcsODU5LjEwMiAxMzM4Mi45LDU2Ni4xOTkgMTMxODUuOCwyNzUuODAxIDEyOTY2LjIsMCBoIC03NzMuOCAtMjczNi40NiAtNjAzLjU4IGwgOTE0Ljk5LDExNTQuOSBjIDgzLjA3LDEyMC44IDE4OCwyMzQuOCAyNzkuODUsMzQ5LjkgMTkuNywyNC42IDM2LjYsNDkuMSA1Myw3Ni4xIDEzNi44LDE3NS42IDI2NC4zLDM1OC40IDM5OS40LDUzNS40IDM2NC43LDQ3Ny45IDc0MC41LDk1NSAxMTMzLjcsMTQwOS43IDE3NC43LDIwMi4xIDM0Niw0MTYuNCA1MzQuNSw2MDUuMyA4MC42LDgwLjggMjQ1LjIsMTg3LjggMzAzLjcsMjY4LjkgMTMxLjgsNDMuMyAxNTMuMywxNjEuOSAzNzguMSwxOTMuMiAzMS43LDkuNCA3Mi45LDMuNyAxMDYuMSwzLjEgMTM0LjYsMjEyIDMyOC4zLDM4OC40IDQ1NS45LDYwMy41IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTMyIgogICAgICAgICBzdHlsZT0iZmlsbDojZGY3ZTNhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDE0MzMyLjMsMzMyMyBjIDc1LjMsLTE3LjEgNDQzLjUsLTE0NC43IDQ4NS4zLC0xODYuNCBDIDE0NDc4LjMsMjI5Ny4xIDE0MDgwLDE2MDguOSAxMzU3OC43LDg1OS4xMDIgMTMzODIuOSw1NjYuMTk5IDEzMTg1LjgsMjc1LjgwMSAxMjk2Ni4yLDAgaCAtNzczLjggYyAzODcuMiw0ODkuMzAxIDc0Ni41LDEwMDYuNCAxMDk0LjksMTUyMy43IDI0Ny4xLDM2MCA0NzksNzI5LjQgNjk1LjYsMTEwOC41IDEyNi41LDIyMS44IDI1NS4zLDQ1MyAzNDkuNCw2OTAuOCIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48ZwogICAgICAgICBpZD0iZzEzNCI+PGcKICAgICAgICAgICBjbGlwLXBhdGg9InVybCgjY2xpcFBhdGgxNDApIgogICAgICAgICAgIGlkPSJnMTM2Ij48cGF0aAogICAgICAgICAgICAgaWQ9InBhdGgxNDgiCiAgICAgICAgICAgICBzdHlsZT0iZmlsbDp1cmwoI2xpbmVhckdyYWRpZW50MTQ2KTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICAgIGQ9Im0gMTI4NDkuNiw0NTkzLjQgYyAyNi45LC0xLjggNjIuOCwwLjEgODYuNCwtMTIuMyAtMzguOCwtODUuNCAtMTUyLjIsLTIwMi4yIC0yMTIuNywtMjgxLjIgLTIxNy42LC0yODggLTQzNy43LC01NzQgLTY2MC4yLC04NTguMSBMIDEwNDMzLjksMTI5OC4xIEMgMTAxMDcuMyw4NjcuNSA5NzY1LjMxLDQ0Mi44MDEgOTQ1NS45NCwwIGggLTYwMy41OCBsIDkxNC45OSwxMTU0LjkgYyA4My4wNywxMjAuOCAxODgsMjM0LjggMjc5Ljg1LDM0OS45IDE5LjcsMjQuNiAzNi42LDQ5LjEgNTMsNzYuMSAxMzYuOCwxNzUuNiAyNjQuMywzNTguNCAzOTkuNCw1MzUuNCAzNjQuNyw0NzcuOSA3NDAuNSw5NTUgMTEzMy43LDE0MDkuNyAxNzQuNywyMDIuMSAzNDYsNDE2LjQgNTM0LjUsNjA1LjMgODAuNiw4MC44IDI0NS4yLDE4Ny44IDMwMy43LDI2OC45IDEzMS44LDQzLjMgMTUzLjMsMTYxLjkgMzc4LjEsMTkzLjIiCiAgICAgICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvZz48L2c+PGcKICAgICAgICAgdHJhbnNmb3JtPSJzY2FsZSgxLjE2NDQ0LDEuMTY0NDQpIgogICAgICAgICBpZD0iZzE1MCI+PHBhdGgKICAgICAgICAgICBpZD0icGF0aDE1MiIKICAgICAgICAgICBzdHlsZT0iZmlsbDojMWEzZDQ3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICAgIGQ9Im0gODE4OC4yNywxNjE5NC40IGMgNDAxLjU2LDEwNS42IDc2Ni4xMiw1OC4zIDExMjUuNjksLTE1MS4xIDM2Ljc1LC0yMS40IDczLjA4LC00My41IDEwOS4xNSwtNjYuMiAxMjguMywtMTA2LjQgMjMwLjU4LC0yMjcuNCAzMDEuNjEsLTM3OS43IDIzMi4zOCwtNjIuNyA0NTAuNjgsLTE0OS4xIDY2OC4xOCwtMjUxLjcgNjguMSwtMzIgMTM3LjIsLTkwLjkgMjA2LjcsLTExMy4yIDg3LjQsLTc0LjEgMjExLjMsLTEyMi44IDMwNy4xLC0xODguMyAzMzcuNCwtMjMwLjYgNzA4LjQsLTUzOC4yIDk1MC42LC04NjkuMyAtNDE1LjMsLTI3Ny4zIC04MTYuOCwtNTc3LjcgLTEyMjcuNCwtODYyLjMgbCAtNTE3LjQsLTM1NC40IGMgLTg3LjIsLTU4LjcgLTMwOC45NSwtMTg2LjEgLTM2NC41MSwtMjU1LjcgLTY1LjQ0LDM2LjggLTEyOC45OSw5MC42IC0xODkuNTQsMTM1IC0xNjcuMzcsMTIyLjggLTMyOS42OCwyNTIgLTQ5NS42OSwzNzYuNiAtMTM0LjMxLDEwMC44IC0yODAuMTMsMTgzLjggLTQxNS42NSwyODIuMyAtMzc0Ljk4LC0xODUuMyAtNjcyLjAyLC0zODcuNCAtMTAyNC44OSwtNTk5LjggLTEzMy4zNCwtODkuMiAtMzY2LjU2LC0yNjMgLTUwMC43MiwtMzI3LjcgLTQ4LjcyLDQzLjggLTExMi40LDgxLjMgLTE2Ni4wOCwxMTkuMSBsIC00MjMuODcsMjkzLjMgYyAtMzQyLjc1LDI0Mi40IC02NzkuMTUsNDkzLjMgLTEwMDkuMiw3NTIuNiAtOTUuOTMsNzUgLTIzNC41NSwxNTUuNiAtMzA5LjY3LDI1MCAxMjQuMzcsMTc4LjYgMjcyLjM4LDMzNi43IDQyMC4wMyw0OTUuOCAyOTcuNzgsMzE3LjQgNjc5LjE5LDU4MC45IDEwNjYuNjYsNzc2LjIgLTMxLjM1LDIxNCA0Mi44Niw0MjQuOCAxNjUuNjYsNTk5IDgwLjU1LDExNC4zIDE2NS43MywxODMuOSAzMDYuMTgsMjA3LjkgbCAxNS40OSwtMS45IGMgNTMuMDksLTYuMSAxMDcuNTcsLTMuMSAxNjEuMDEsLTcuMiAxNDMuNDgsLTExLjEgMzAwLjAyLC0zMC4zIDQzOC42MiwtNjkuNSAxMjkuMjgsODMuNSAyNTcuNzEsMTU1LjIgNDAxLjk0LDIxMC4yIgogICAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PC9nPjxnCiAgICAgICAgIHRyYW5zZm9ybT0ic2NhbGUoMS4xNTY4OSwxLjE1Njg5KSIKICAgICAgICAgaWQ9ImcxNTQiPjxwYXRoCiAgICAgICAgICAgaWQ9InBhdGgxNTYiCiAgICAgICAgICAgc3R5bGU9ImZpbGw6IzVmMWQyYztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICBkPSJtIDc4MzcuMSwxNjA4OC40IGMgMTMwLjEyLDg0IDI1OS4zOSwxNTYuMyA0MDQuNTYsMjExLjYgMTQwLjk5LC0xMjQuMiAyNTMuNDMsLTI5NSAzNzAuMjIsLTQ0Mi40IC0xMjAuMzcsLTEuOSAtMjQwLjMxLC0xMCAtMzU5LjgzLC0yNC40IC0xMTkuNTEsLTE0LjUgLTIzNy45NSwtMzUgLTM1NS4zMiwtNjEuOCAtMTIzLjg3LC0yOC4xIC0yNDcuNjEsLTY1LjcgLTM3Mi4wOCwtODkuNyA2OS4xNiwxNjYuMyAxNjkuMTEsMjk3IDMxMi40NSw0MDYuNyIKICAgICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvZz48ZwogICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMTQ3NDksMS4xNDc0OSkiCiAgICAgICAgIGlkPSJnMTU4Ij48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMTYwIgogICAgICAgICAgIHN0eWxlPSJmaWxsOiMxYjFiMWQ7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSA3Mjc3LjEsMTYzMDAgMTUuNzIsLTEuOSBjIDUzLjg3LC02LjIgMTA5LjE1LC0zLjEgMTYzLjM4LC03LjMgMTQ1LjYsLTExLjMgMzA0LjQ1LC0zMC44IDQ0NS4xMSwtNzAuNiAtMTQ0LjUyLC0xMTAuNiAtMjQ1LjI5LC0yNDIuMyAtMzE1LjAyLC00MTAgLTkzLjQzLC0zOS4zIC0xOTMuNTUsLTY0LjIgLTI4OS40NywtOTcgLTE2Ni44NywtNTcuMiAtMzQ4Ljk5LC0xMzcuOCAtNDk4LjUzLC0yMzIgLTMxLjgxLDIxNy4xIDQzLjUsNDMxIDE2OC4xMSw2MDcuOCA4MS43NCwxMTYgMTY4LjE3LDE4Ni42IDMxMC43LDIxMSIKICAgICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjwvZz48ZwogICAgICAgICB0cmFuc2Zvcm09InNjYWxlKDEuMTY0NDQsMS4xNjQ0NCkiCiAgICAgICAgIGlkPSJnMTYyIj48cGF0aAogICAgICAgICAgIGlkPSJwYXRoMTY0IgogICAgICAgICAgIHN0eWxlPSJmaWxsOiNhMjFjMzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgZD0ibSA4MTg4LjI3LDE2MTk0LjQgYyA0MDEuNTYsMTA1LjYgNzY2LjEyLDU4LjMgMTEyNS42OSwtMTUxLjEgMzYuNzUsLTIxLjQgNzMuMDgsLTQzLjUgMTA5LjE1LC02Ni4yIDEyOC4zLC0xMDYuNCAyMzAuNTgsLTIyNy40IDMwMS42MSwtMzc5LjcgLTE0NiwxOS45IC0yODkuMzMsNjcuNCAtNDM0LjcyLDk0IC0yNDQuMTUsNDQuNSAtNDg2LjUsNTQuOCAtNzMzLjkxLDYzLjUgLTExNi4wMywxNDYuNCAtMjI3Ljc1LDMxNi4xIC0zNjcuODIsNDM5LjUiCiAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PGcKICAgICAgICAgdHJhbnNmb3JtPSJzY2FsZSgxLjAzNDQsMS4wMzQ0KSIKICAgICAgICAgaWQ9ImcxNjYiPjxwYXRoCiAgICAgICAgICAgaWQ9InBhdGgxNjgiCiAgICAgICAgICAgc3R5bGU9ImZpbGw6IzIxMmIzMTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICBkPSJtIDYzNDAuODIsMTYzMDAgYyAyMDcuNTIsLTI2MyA0ODQuODMsLTQ3MS4xIDc0NS41NywtNjc4LjkgNDg3LjY1LC0zODEuOCA5ODUuNjYsLTc0OS42IDE0OTQuMDYsLTExMDMuMiAtMTUwLjEsLTEwMC40IC00MTIuNjUsLTI5NiAtNTYzLjY4LC0zNjguOSAtNTQuODQsNDkuMyAtMTI2LjUyLDkxLjUgLTE4Ni45NSwxMzQuMSBsIC00NzcuMTYsMzMwLjIgYyAtMzg1LjgzLDI3Mi44IC03NjQuNTMsNTU1LjIgLTExMzYuMDcsODQ3LjIgLTEwNy45OSw4NC40IC0yNjQuMDQsMTc1LjIgLTM0OC42LDI4MS40IDE0MC4wMSwyMDEgMzA2LjYzLDM3OSA0NzIuODMsNTU4LjEiCiAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxNzAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNmY2Q0YTg7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTAwNjksMTU3MTUuNyBjIDE1Ny44LC0xMTQuNyAzMjcuNiwtMjExLjQgNDg0LC0zMjguOCAxOTMuMywtMTQ1IDM4Mi4zLC0yOTUuNSA1NzcuMiwtNDM4LjUgNzAuNSwtNTEuNyAxNDQuNSwtMTE0LjMgMjIwLjcsLTE1Ny4xIDQyNC43LC0zMDIuMiA4MzYuNCwtNjIxLjQgMTIzNC44LC05NTcuNiAxMTcuNiwtOTguMSAyNjkuNiwtMjAyLjggMzY0LjksLTMyMS43IDIwLjIsLTgzLjkgMjkzLjUsLTI0OC43IDI1NiwtMzIzLjUgLTE2LjEsLTMyIC00Ny4zLC02NS40IC02OS4xLC05NC40IC02NC4xLDg1LjkgLTE4Mi4zLDI2OS4zIC0yNzYuNywzMTIgMTUxLjEsLTE3NC44IDI5My42LC0zNTYuNCA0MjcuNCwtNTQ0LjggNzQuOCwtMTA1LjcgMTM2LC0yMjIuMyAyMTksLTMyMC43IDIuOCwtMy4yIDQuMywtNy4zIDYuNCwtMTEgbCAyLjEsLTUyNS4xIGMgMC40LC05MiAtNS44LC0xOTMuNSA2LjksLTI4NC41IC02LjUsLTMwMi4yIC0wLjYsLTYwNS4zIC0zLjQsLTkwNy43IC0xLjQsLTE1OC44IDEuNCwtMzIwLjUgLTE2LjQsLTQ3OC41IC03NS41LC0xOTYuNSAtMTIxLjQsLTQwOC45IC0xNzEuMiwtNjEzLjIgLTUyLC0xNzkuNSAtMTAzLjcsLTM2OSAtMTM3LC01NTIuNyAtNDAsLTEzMC45IC02NS43LC0yNjYgLTEwNC4zLC0zOTcuNCAtMTE2LC0zOTYgLTI4My42LC03OTEuNiAtNTIyLjksLTExMjkuNiAtNzQuNywtMTA1IC0xNTQuMSwtMjA2LjMgLTIzOC4xLC0zMDQgLTUyLjQsLTYwLjQgLTEzNiwtMTMxLjMgLTE3My44LC0xOTkuNiAtMzY5LjYsLTM5MyAtNzU0LC03ODQuNCAtMTIzNy42LC0xMDM4IC0yMjEuOSwtMTgwLjggLTU4OS40LC0yNDAuNiAtODY2LjgsLTI0MS43IC04NzAuMjUsLTMuNyAtMTQ2Ni4wOSw1NzcuOCAtMjA0Mi4yOSwxMTUwLjMgLTk1LjMzLDEwNi43IC0xOTQuMjMsMjA3LjQgLTI4My42MywzMTkuNiAtNDA3Ljg5LDUxMi4zIC02MzAuNjIsMTA5MS40IC03NzAuMzcsMTcyNS44IC0xOC43LDEyMC41IC02NC45NiwyNDIuMiAtOTIuNDQsMzYxLjggLTMwLjY0LDEzMy40IC00My40NywyODIuMyAtODYuNDQsNDExLjIgLTQ1Ljg0LDIwMi41IC04Mi4wOCw0MDYuNyAtMTE5LjczLDYxMC44IC0xNi4xMyw4Ny41IC0yNC40NCwyMDUuNCAtNTguMzMsMjg2LjcgLTkuNDksODQuNiAtMjAuNzIsMTY5IC0yOC4zMiwyNTMuOSAtNDQuNjksNDk5LjcgLTkzLjQ5LDE1ODYgNzQuMDEsMjA0NiA3MS4wNiwxOTUuMiAxOTYuNjIsMzYyLjEgMzI4LjczLDUxOS45IDMzMC4yNSw0NTQuOSA4NTguNzEsNzg1LjcgMTMyMC4yMywxMDkyLjEgMTU2LjIyLDc1LjQgNDI3LjgsMjc3LjcgNTgzLjA2LDM4MS41IDQxMC45LDI0Ny40IDc1Ni43OCw0ODIuNyAxMTkzLjQyLDY5OC41IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTcyIgogICAgICAgICBzdHlsZT0iZmlsbDojZGY3ZTNhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDExMDgxLjQsMTExODguMiBjIDI0LjEsMTEuOSA0NC4xLDI4LjYgNjUuNSw0NC44IDczLjEsLTc1IDE2My41LC0xNjcuNiAyNTguOCwtMjEzLjIgLTk2LjEsNC4zIC0yNDQuNywxMTYuNiAtMzI0LjMsMTY4LjQiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxNzQiCiAgICAgICAgIHN0eWxlPSJmaWxsOiMxYjFiMWQ7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTI3OTUuMiwxMjcwMC43IGMgMTA5LjYsLTgzLjEgMjA4LC0xNzEuMiAyODQuNCwtMjg2LjggbCAtMC42LC0xMy45IGMgLTEwNC43LDEwMi4yIC0xOTAuMiwxODIuNSAtMzI0LjYsMjQ1LjkgMTguMSwxNyAyOCwzNCA0MC44LDU0LjgiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxNzYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNiMTFlMmE7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTI0MzQuMiwxMTQzNi44IGMgMjEuOSwtNi45IDQzLjIsLTE0LjMgNjYuMiwtMTYuNyAtMTI3LjMsLTIwOS40IC0zNDEuMywtMzkwLjIgLTU4Mi41LC00NTMuOSAtMTcuMywtNC42IC0zNC41LC03IC01Mi40LC01LjcgMjQzLjgsODEuOSA0MzcuMiwyNTguOCA1NjguNyw0NzYuMyIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDE3OCIKICAgICAgICAgc3R5bGU9ImZpbGw6IzFhM2Q0NztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA4OTkwLjU2LDEyNjA5LjQgYyAxMDEuNTQsLTM4IDE2NS4zNiwtNzIuNyAyMTQsLTE3NS42IDI1LjA4LC01My4xIDQ0LjExLC0xMTAuMSA2NC4xNywtMTY1LjMgLTQ4LjAxLC0xNC4zIC0yNjQuNDUsNTYuOSAtMzIwLjQsNzUuNCAtNC43NSw5MS4xIDcxLjgyLDE3MS43IDQyLjIzLDI2NS41IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTgwIgogICAgICAgICBzdHlsZT0iZmlsbDojZWZlY2U3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDEwMTU1LjMsMTAzNDEuMyBjIDMuOCwtNS4yIDguNiwtOS44IDExLjYsLTE1LjUgMjUuNiwtNDguNiAxNTksLTY4Ni4zIDE1OC44LC03NDkuOCAtMC4xLC00MS4yIC0xOS4xLC03Ni43IC0zNi44LC0xMTIuOSAtNS40LC0zLjMgLTExLjgsLTcuNiAtMTgsLTkuMiAtMjEuNiwtNS40IC00MC40LDAgLTU3LjcsMTQuMiAtMTI3LDEwNC43IC02Ni4zLDcwNi41IC01Ny45LDg3My4yIgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTgyIgogICAgICAgICBzdHlsZT0iZmlsbDojYjExZTJhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDg5NjUuNCw3Nzg3LjggYyAxNzAuNjksMTA1LjIgNTc3LjkyLDMzMS4zIDc2Mi41MywzNjQuNCAxNy4xMSwtOTQuNSAzMC41LC0xNjEuOCA5Ny42NSwtMjM1LjEgLTQ5LjYsMi43IC05OS4yMywzLjEgLTE0OC44NywxLjEgLTQ5LjYzLC0yIC05OS4wNywtNi4zIC0xNDguMzEsLTEyLjkgLTQ5LjIzLC02LjYgLTk4LjA1LC0xNS41IC0xNDYuNDcsLTI2LjYgLTQ4LjQsLTExLjIgLTk2LjE3LC0yNC42IC0xNDMuMzMsLTQwLjIgLTM3LjUsLTEyLjYgLTY4Ljk4LC0zNS4xIC0xMDcuMjgsLTQ3LjEgLTU1LjI5LDIuMiAtMTEwLjM0LC01LjcgLTE2NS45MiwtMy42IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMTg0IgogICAgICAgICBzdHlsZT0iZmlsbDojZjAzYjRhO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDk3MjcuOTMsODE1Mi4yIGMgMTE3LjcyLC00Mi4yIDIwOC40OSwtODMuOSAzMzYuMDcsLTUzLjEgNzguOCwyNC4zIDE1MCw1Mi4zIDIzMy42LDQxLjggLTMwLjQsLTMzLjYgLTI1LjYsLTk0LjYgLTUwLjUsLTEzNy41IC0yNiwtMzggLTUyLjYsLTc1LjggLTc5LjYsLTExMy4xIC0xMjEuMSwtMzIuNCAtMjI3LjMsLTE3LjEgLTM0MS45MiwyNi44IC02Ny4xNSw3My4zIC04MC41NCwxNDAuNiAtOTcuNjUsMjM1LjEiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxODYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNkZDFlMjY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTAyOTcuNiw4MTQwLjkgYyAxMzcuMiwtMzguMSAyNjkuMSwtMTIyLjYgMzk0LjksLTE4OC4yIDExMi43LC01OCAyMjYuOSwtMTEzLjEgMzQyLjUsLTE2NS4yIC02My4yLC0xMS41IC0xNjMuOSwxNS45IC0yMjkuNiwyMy4yIC0xOTcuMiw0OC45IC00MzQuNCw5Ny42IC02MzcuOSw3OS42IDI3LDM3LjMgNTMuNiw3NS4xIDc5LjYsMTEzLjEgMjQuOSw0Mi45IDIwLjEsMTAzLjkgNTAuNSwxMzcuNSIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDE4OCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2EyMWMzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA5MTMxLjMyLDc3OTEuNCBjIDM4LjMsMTIgNjkuNzgsMzQuNSAxMDcuMjgsNDcuMSA0Ny4xNiwxNS42IDk0LjkzLDI5IDE0My4zMyw0MC4yIDQ4LjQyLDExLjEgOTcuMjQsMjAgMTQ2LjQ3LDI2LjYgNDkuMjQsNi42IDk4LjY4LDEwLjkgMTQ4LjMxLDEyLjkgNDkuNjQsMS45IDk5LjI3LDEuNiAxNDguODcsLTEuMSAxMTQuNjIsLTQzLjkgMjIwLjgyLC01OS4yIDM0MS45MiwtMjYuOCAyMDMuNSwxOCA0NDAuNywtMzAuNyA2MzcuOSwtNzkuNiAtMTUyLjIsLTk1LjYgLTE0MzMuMTEsLTI2LjEgLTE2NzQuMDgsLTE5LjMiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxOTAiCiAgICAgICAgIHN0eWxlPSJmaWxsOiM5NDE5MzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTA4MDUuNCw3ODEwLjcgYyA2NS43LC03LjMgMTY2LjQsLTM0LjcgMjI5LjYsLTIzLjIgMjUuNSwtOC4zIDYzLjYsLTE0LjIgNzguNywtMzUuOCAtMTguMSwtMTAuNSAtMzUuNiwtMTguMSAtNTUuMSwtMjUuNSAtNTMwLjcsLTEwNS43IC0xMjI1LjU0LC0xNTEuNSAtMTc1OS4xLC01Ni44IC0xMTEuMDYsMjIuNSAtMjI3LjQ4LDU4LjUgLTMzOS4xLDcxLjEgbCAtMzYuNDIsMzguMyA0MS40Miw5IGMgNTUuNTgsLTIuMSAxMTAuNjMsNS44IDE2NS45MiwzLjYgMjQwLjk3LC02LjggMTUyMS44OCwtNzYuMyAxNjc0LjA4LDE5LjMiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgxOTIiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNmMGE5NmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTA4MDkuOCwxMjI2Mi40IGMgMzEwLjgsNzMuMyA2MjAuMywxNTEuOSA5MjguNCwyMzUuOCAyNDUsNjguNSA0OTYuNywxNTkuMSA3NTAuMiwxODUuMiAtNDguNywtNTQuNCAtMjY4LjYsLTk3LjIgLTM0Ny43LC0xMjYuNCAtMzU1LjksLTEzMS41IC03NjEuOSwtMzcyLjggLTEwMjkuNywtNjQxLjggLTE2NC45LC0xNjUuNiAtMzIxLjgsLTM5MS41IC00MzAuMiwtNTk4LjcgLTIxLjcsMzM0LjkgLTUuNyw2MzIuNyAxMjksOTQ1LjkiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PGcKICAgICAgICAgaWQ9ImcxOTQiPjxnCiAgICAgICAgICAgY2xpcC1wYXRoPSJ1cmwoI2NsaXBQYXRoMjAwKSIKICAgICAgICAgICBpZD0iZzE5NiI+PHBhdGgKICAgICAgICAgICAgIGlkPSJwYXRoMjA4IgogICAgICAgICAgICAgc3R5bGU9ImZpbGw6dXJsKCNsaW5lYXJHcmFkaWVudDIwNik7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICBkPSJtIDEwODA5LjgsMTIyNjIuNCBjIDE3LjgsNzIuOCAzOC45LDE1NS43IDgwLDIxOC44IDEwNS40LDE2MS44IDU2My45LDI3Mi4yIDc1Ni4zLDMxOCA0NDYuNiwxMDYuMyA3NDUuNSwxNTAuNiAxMTQ5LjEsLTk4LjUgLTEyLjgsLTIwLjggLTIyLjcsLTM3LjggLTQwLjgsLTU0LjggLTkxLjUsMzAuMiAtMTcwLjEsMzcuMiAtMjY2LDM3LjUgLTI1My41LC0yNi4xIC01MDUuMiwtMTE2LjcgLTc1MC4yLC0xODUuMiAtMzA4LjEsLTgzLjkgLTYxNy42LC0xNjIuNSAtOTI4LjQsLTIzNS44IgogICAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PC9nPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjEwIgogICAgICAgICBzdHlsZT0iZmlsbDojZGQxZTI2O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDkyOTkuNSw3NjY5LjQgYyA1MzMuNTYsLTk0LjcgMTIyOC40LC00OC45IDE3NTkuMSw1Ni44IC0yMDQuNywtMTgzLjEgLTU5MC41LC01NDAuNSAtODc0LjIsLTU2MC41IC02MS44LDMwLjkgLTE1MiwxMS44IC0yMjAuNTUsMTkuNiAtNTkuMTEsNi44IC0xMTkuMzYsMjAuNyAtMTc1Ljk4LDM4LjkgLTI1Ni40NSw4Mi40IC0zNjkuNzgsMjEwLjUgLTQ4OC4zNyw0NDUuMiIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDIxMiIKICAgICAgICAgc3R5bGU9ImZpbGw6IzFiMWIxZDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA3NDU0LjkyLDExNzI0LjcgYyAzNzMuNzksODguNyA3NTEuMTcsMTM2LjEgMTA5NC40NiwtNzcgMjE2LjYsLTEzNC40IDM2Ny4yOSwtMzQyLjYgNDg4LjI0LC01NjIuNSAtNjMuNDUsNDAuNCAtMTU0LjM5LDEwNiAtMTk2LjI2LDE2OS4xIC02Ni45OSwtMzkuOCAtMTMyLjg0LC03Ni44IC0yMDQuMjEsLTEwOC4yIC00NS44MSwtMjAuMiAtOTkuODgsLTM1LjIgLTE0Mi43OCwtNjAgLTksLTIuMyAtMTcuOTgsLTQuNyAtMjcuMDMsLTYuNyAtMzIwLjMsLTcxLjggLTU2MC42Myw2MC43IC04MjMuNCwyMzAuMSAtOTguMzEsMTIgLTM5OC45NywyNzUuNCAtNDY4LjU5LDM1OC45IDkzLjc0LDguNSAxODguODgsMzEuNiAyNzkuNTcsNTYuMyIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDIxNCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2VmZWNlNztmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA4MzI0LjEsMTE1NTguMSBjIDE2LjcyLC0zLjYgMzQuMjMsLTcuMSA1MC4yMSwtMTMuMyAyNC4xOSwtOS4zIDM3LjMxLC0yNCA0OC4wMSwtNDcuMiAyLjM0LC0zMy4yIC01LjEyLC00Ny43IC0yMS4xMSwtNzUuMiAtMjAuODcsMC4yIC00MC41NSwxLjYgLTU5LjU2LDExLjQgLTIxLjU5LDExIC0zNi41OCwzMi44IC00MC43Miw1Ni40IC00LjgyLDI3LjUgOSw0Ni42IDIzLjE3LDY3LjkiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PGcKICAgICAgICAgaWQ9ImcyMTYiPjxnCiAgICAgICAgICAgY2xpcC1wYXRoPSJ1cmwoI2NsaXBQYXRoMjIyKSIKICAgICAgICAgICBpZD0iZzIxOCI+PHBhdGgKICAgICAgICAgICAgIGlkPSJwYXRoMjMwIgogICAgICAgICAgICAgc3R5bGU9ImZpbGw6dXJsKCNsaW5lYXJHcmFkaWVudDIyOCk7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICBkPSJtIDc3OTIuOTEsMTE0NTkuMSBjIDQ5Ljk4LDQyIDExOC4wNiw5OS4zIDE4MC45OCwxMTkuMiAxOS44Miw2LjIgMTEuMzcsNi4zIDMwLjE0LC00IGwgLTEuODQsLTI0LjIgYyAwLjczLC0xMzMuOSAwLjYxLC0yNTguMyAxMDEuMzMsLTM2MC44IDUxLC01MS45IDEyMC4xMywtODMuOCAxOTMuNSwtODIuMiA3Ni42OSwxLjcgMTQ2LjA3LDM5LjkgMTk2Ljk3LDk1LjkgNzAuMDgsNzcuMiA5Mi40LDE2OC4zIDEwOCwyNjcuNyA3NC44OSwtNTYgMTkzLjIsLTEzMi40IDIzOS4zNywtMjE2LjQgLTY2Ljk5LC0zOS44IC0xMzIuODQsLTc2LjggLTIwNC4yMSwtMTA4LjIgLTQ1LjgxLC0yMC4yIC05OS44OCwtMzUuMiAtMTQyLjc4LC02MCAtOSwtMi4zIC0xNy45OCwtNC43IC0yNy4wMywtNi43IC0zMjAuMywtNzEuOCAtNTYwLjYzLDYwLjcgLTgyMy40LDIzMC4xIDQ0LjM4LDU3LjEgOTAuODksMTA2LjMgMTQ4Ljk3LDE0OS42IgogICAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PC9nPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjMyIgogICAgICAgICBzdHlsZT0iZmlsbDojZWZlY2U3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDc3OTIuOTEsMTE0NTkuMSBjIDQ5Ljk4LDQyIDExOC4wNiw5OS4zIDE4MC45OCwxMTkuMiAxOS44Miw2LjIgMTEuMzcsNi4zIDMwLjE0LC00IGwgLTEuODQsLTI0LjIgYyAtMTAuMDYsLTQ5IC05LjAzLC05NS44IC04LjI1LC0xNDUuNCAtNzIuMTEsNC45IC0xNDAuNTgsOS4xIC0yMDEuMDMsNTQuNCIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48ZwogICAgICAgICBpZD0iZzIzNCI+PGcKICAgICAgICAgICBjbGlwLXBhdGg9InVybCgjY2xpcFBhdGgyNDApIgogICAgICAgICAgIGlkPSJnMjM2Ij48cGF0aAogICAgICAgICAgICAgaWQ9InBhdGgyNDgiCiAgICAgICAgICAgICBzdHlsZT0iZmlsbDp1cmwoI2xpbmVhckdyYWRpZW50MjQ2KTtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgICAgIGQ9Im0gMTAwNjksMTU3MTUuNyBjIDE1Ny44LC0xMTQuNyAzMjcuNiwtMjExLjQgNDg0LC0zMjguOCAxOTMuMywtMTQ1IDM4Mi4zLC0yOTUuNSA1NzcuMiwtNDM4LjUgNzAuNSwtNTEuNyAxNDQuNSwtMTE0LjMgMjIwLjcsLTE1Ny4xIDQyNC43LC0zMDIuMiA4MzYuNCwtNjIxLjQgMTIzNC44LC05NTcuNiAxMTcuNiwtOTguMSAyNjkuNiwtMjAyLjggMzY0LjksLTMyMS43IDIwLjIsLTgzLjkgMjkzLjUsLTI0OC43IDI1NiwtMzIzLjUgLTE2LjEsLTMyIC00Ny4zLC02NS40IC02OS4xLC05NC40IC02NC4xLDg1LjkgLTE4Mi4zLDI2OS4zIC0yNzYuNywzMTIgLTIyMi40LDIyOC44IC00NjEuOCw0NTMuMSAtNzEwLjcsNjUzLjEgLTM2My42LDI5Mi4yIC03NTQuNiw1NTQuMiAtMTEzMC43LDgzMC41IC0zMjAuMiwyMzUuMiAtNjMyLjUsNTAwLjEgLTk3Ni41LDY5OS44IC0zNTkuMzIsLTE4MC41IC02OTkuODQsLTQwNi45IC0xMDM4LjI5LC02MjMuMiAtMzk5Ljg2LC0yNTUuNSAtODAxLjk5LC01MTEuNCAtMTE4OC45MywtNzg2LjIgLTE1My4xNSwtOTYuMSAtMjk5LjM4LC0yMDEuOCAtNDM4LjcxLC0zMTcuMSAtMTE1LjU0LC05Ni4zIC0yMjYuNTksLTIwMSAtMzQ1Ljg0LC0yOTIuNSAtMjAuMzYsLTE1LjYgLTMzLjYsLTIzLjEgLTU4Ljg0LC0yNi45IDMzMC4yNSw0NTQuOSA4NTguNzEsNzg1LjcgMTMyMC4yMywxMDkyLjEgMTU2LjIyLDc1LjQgNDI3LjgsMjc3LjcgNTgzLjA2LDM4MS41IDQxMC45LDI0Ny40IDc1Ni43OCw0ODIuNyAxMTkzLjQyLDY5OC41IgogICAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PC9nPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjUwIgogICAgICAgICBzdHlsZT0iZmlsbDojMWIxYjFkO2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDExMDgxLjQsMTExODguMiBjIDEuOCwxOS40IDUuNCwzNi4zIDEyLjksNTQuMiA1NiwxMzMuNyAxNjUuNCwyNjIuMyAyNzUuNCwzNTUgNjAxLjcsNTA3LjcgMTE0NC42LC0xMjAgMTY2NC4yLDEwMC4xIC05OS42LC03OS4yIC0zNjMuNiwtMjgwLjcgLTQ5My4yLC0yNzQuNCAtMjAuNCwxIC0xMC43LDIuNCAtMzAuMywtMC45IC0zLjQsLTAuNiAtNi43LC0xLjQgLTEwLC0yLjEgLTIzLDIuNCAtNDQuMyw5LjggLTY2LjIsMTYuNyAtMTMxLjUsLTIxNy41IC0zMjQuOSwtMzk0LjQgLTU2OC43LC00NzYuMyAtNy40LC0xLjEgLTE0LjksLTIuMSAtMjIuMywtMy41IC0xNjkuMywtMzMgLTI4MCwxMC40IC00MzcuNSw2Mi44IC05NS4zLDQ1LjYgLTE4NS43LDEzOC4yIC0yNTguOCwyMTMuMiAtMjEuNCwtMTYuMiAtNDEuNCwtMzIuOSAtNjUuNSwtNDQuOCIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDI1MiIKICAgICAgICAgc3R5bGU9ImZpbGw6I2ZjZDRhODtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSAxMTcwMi43LDExNTQxLjUgYyA3LjksLTEuNCAxNi43LC0yLjQgMjQuMSwtNS45IDI1LjgsLTEyLjEgMzAuMSwtMjAuMiA0MC4xLC00NC45IC0zLjgsLTMzLjEgLTE2LC01MS41IC0zNC40LC03OC44IC0xMSwzIC0zMC45LDYuNyAtNDEuMywxMi44IC0yMi41LDEzLjMgLTIzLjgsMjEuOSAtMzAuMyw0NS4yIDUuOCwzMi4zIDIxLDQ3LjkgNDEuOCw3MS42IgogICAgICAgICBpbmtzY2FwZTpjb25uZWN0b3ItY3VydmF0dXJlPSIwIiAvPjxwYXRoCiAgICAgICAgIGlkPSJwYXRoMjU0IgogICAgICAgICBzdHlsZT0iZmlsbDojZWZlY2U3O2ZpbGwtb3BhY2l0eToxO2ZpbGwtcnVsZTpub256ZXJvO3N0cm9rZTpub25lIgogICAgICAgICBkPSJtIDExMzQ0LjgsMTE0MTQuNCBjIDYuOCwtMzYuMyAxMy4zLC03My4xIDI1LjEsLTEwOC4xIDMyLjEsLTk1IDEwMy4xLC0xNzguMyAxOTQuOCwtMjIwLjIgNS40LC0yLjQgMTAuOCwtNC44IDE2LjIsLTYuOSA1LjUsLTIuMiAxMSwtNC4zIDE2LjYsLTYuMiA1LjYsLTEuOCAxMS4yLC0zLjYgMTYuOCwtNS4yIDUuNywtMS42IDExLjQsLTMuMSAxNy4xLC00LjQgNS44LC0xLjMgMTEuNSwtMi40IDE3LjMsLTMuNCA1LjgsLTEgMTEuNiwtMS45IDE3LjUsLTIuNiA1LjgsLTAuNyAxMS43LC0xLjMgMTcuNiwtMS43IDUuOCwtMC4zIDExLjcsLTAuNiAxNy42LC0wLjcgNS45LC0wLjEgMTEuNywtMC4xIDE3LjYsMC4yIDUuOSwwLjIgMTEuOCwwLjUgMTcuNiwxIDUuOSwwLjYgMTEuNywxLjIgMTcuNiwyLjEgNS44LDAuOCAxMS42LDEuNyAxNy40LDIuOSA1LjcsMS4xIDExLjUsMi4zIDE3LjIsMy44IDUuNywxLjQgMTEuNCwyLjkgMTcsNC43IDUuNiwxLjcgMTEuMiwzLjUgMTYuNyw1LjUgNS42LDIgMTEsNC4yIDE2LjUsNi40IDc3LjksMzIuMyAxNDIuNiw5Mi44IDE3Mi4xLDE3Mi43IDQwLjgsMTEwLjkgOC4zLDIyNS45IC0zNi44LDMyOS40IDE1Ny45LC0yNy43IDMwNy41LC05OC4xIDQ1OS45LC0xNDYuOSAtMTMxLjUsLTIxNy41IC0zMjQuOSwtMzk0LjQgLTU2OC43LC00NzYuMyAtNy40LC0xLjEgLTE0LjksLTIuMSAtMjIuMywtMy41IC0xNjkuMywtMzMgLTI4MCwxMC40IC00MzcuNSw2Mi44IC05NS4zLDQ1LjYgLTE4NS43LDEzOC4yIC0yNTguOCwyMTMuMiA2NC4yLDYyLjggMTMwLjIsMTIyLjQgMTk3LjksMTgxLjQiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNTYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNmMGE5NmM7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gODAyNC43MSwxMjUyMS4xIDEuNTMsMTEuOCBjIC02Mi40MywzMS43IC0xMzIuMDMsNDEuNiAtMTkzLjU3LDc0LjYgMTkzLjcyLC0yLjIgMzk5Ljc2LC0xMzMuNyA1ODkuMDEsLTEyMi4xIDE3NC40MSwtNDYuMyAzNTAuNDMsLTEwNC42IDUyNi42NSwtMTQxLjUgNTUuOTUsLTE4LjUgMjcyLjM5LC04OS43IDMyMC40LC03NS40IDM1Ni45NSwtNzc3LjMgMzk5LjU4LC0xMzMyLjggMzMwLjA1LC0yMTc0LjQgLTE3LjIyLC0yMDguNSAtNjQuODcsLTUwMS40IC0yNS4zMiwtNzAyLjQgMjUuOTEsLTEzMS42IDExMi43OSwtMjQ2LjEgMjQwLjk1LC0yOTIgMjUyLjg5LC05MC41IDQzOS43OSw3OCA2NjQuOTksNjAuOSA4NC44LC02LjQgMTg3LjcsLTkwLjMgMjY3LC01OS45IDM2LDQzLjUgMzgsOTAuMyAzMy42LDE0NS4xIC01LjgsNzEuNyAtMjcuMSwxNDMuMyAtNDUuMywyMTIuNSA2NC4yLC05NC4yIDEyMi44LC0yMDUuOCA5OC41LC0zMjMuOCAtMTcuMiwtODMuMyAtNzQuNiwtMTUzIC0xNDYuNCwtMTk2LjUgLTExOC45LC03MiAtMjY3LjUsLTg4LjQgLTM5Ni42LC0xMzcuOSAtMTQzLjksLTU1LjIgLTI3OS43LC0xMjkuOCAtNDI0LjU4LC0xODMuMyAtNTEuMTksMjIgLTEwMi43Miw0NCAtMTU2LjAyLDYwLjYgLTU1LjkxLDE3LjUgLTE3Ny45NiwzNC40IC0yMjIuNCw2MS43IC01OC41LDEwLjEgLTExOC43NSwyNS44IC0xNzMuODEsNDguMSAtOTUuNDksMzguOCAtMTgzLjg2LDEwMS42IC0yMjIuMTYsMjAwLjkgLTY0LjE3LDE2Ni4xIDQ2LjUzLDM3OS42IDExNy4wOSw1MjkgMTEuNjksNjYuMiAxMDAuMzEsMjI5LjYgMTI5LjUsMzA3LjEgMTYwLjIyLDQyNS42IDIyNi45NCw4OTguNCA4NC44NCwxMzM4LjYgLTE1Ny43NCw0ODguNiAtNTIxLjk0LDkxNC41IC05NzAuNDQsMTE2MS4zIC0xMzMuNzUsNzMuNiAtMjc5LjMsMTE4LjQgLTQxMi41NCwxODguOSBsIC0xNC45Nyw4LjEiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNTgiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNhMjFjMzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gMTA0NjEuMSw5MTEwLjIgYyAyOC45LC0xLjEgNTguNSwtNy41IDg3LjEsLTEyLjEgbCAxMi4zLC0yOS42IGMgLTEuOSwtMi4zIC0zLjcsLTQuNyAtNS43LC02LjkgLTczLjIsLTc1LjQgLTE5Ni41LC05MS45IC0yOTUuNCwtOTcuOSBsIC0xMDEuNSwtOSBjIDk2LjIsOTAuMyAxNjguNiwxNDEuNCAzMDMuMiwxNTUuNSIKICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48cGF0aAogICAgICAgICBpZD0icGF0aDI2MCIKICAgICAgICAgc3R5bGU9ImZpbGw6I2EyMWMzMDtmaWxsLW9wYWNpdHk6MTtmaWxsLXJ1bGU6bm9uemVybztzdHJva2U6bm9uZSIKICAgICAgICAgZD0ibSA5MzcwLjIxLDg5NTIuMiBjIDMyLjU2LDM4LjcgNjQuODksODAuOCAxMDIuOTQsMTE0LjEgMzQuNTYsMzAuMyA3OS4zMyw1Ni42IDEyNi44Nyw1MS44IDg5LjYzLC05LjEgMTY0LjIxLC0xMTYuNyAyMTguMjEsLTE3OC44IC01MC40MywxMi4xIC05OC45LDIyLjYgLTE1MC42MSwyOCAtMTAwLjM3LDIwLjYgLTE5Ny40NywtNC4xIC0yOTcuNDEsLTE1LjEiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNjIiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNjYzU5MmY7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gOTIwOC4zMiw5NTE3LjEgYyAwLjE3LC01LjcgMC40MywtMTEuNCAwLjUyLC0xNy4xIDAuNzEsLTQyLjUgLTkuNDQsLTg1IC0xMy4wMiwtMTI3LjMgLTEyLjY1LC0xNDguMyAxMy4wNiwtMjg3LjIgMTIyLjIzLC0zOTYuNyAxMy4zOSwtMTMuNCAyNC4zOSwtMjEuMyA0Mi44NSwtMjYuOCBsIDkuMzEsMyBjIDk5Ljk0LDExIDE5Ny4wNCwzNS43IDI5Ny40MSwxNS4xIC04OS4zMSwtNi43IC0yNzcuMjYsLTYxLjMgLTM1Mi43NiwtOS43IC0xOS4xMSwxMyAtMzEuODUsMzUuOSAtNDMuOTEsNTUuMiBsIC03MS44MiwtMTExLjUgYyA2LjU2LC0zMC40IDIwLjY5LC00My44IDQ2LjQ4LC02MC45IDk0LC02Mi4yIDE2MS45NCwtNTIuMyAyNDQuMDIsLTkxLjEgbCAtMi40MywtMTAuMiBjIC01OC41LDEwLjEgLTExOC43NSwyNS44IC0xNzMuODEsNDguMSAtOTUuNDksMzguOCAtMTgzLjg2LDEwMS42IC0yMjIuMTYsMjAwLjkgLTY0LjE3LDE2Ni4xIDQ2LjUzLDM3OS42IDExNy4wOSw1MjkiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNjQiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNkZjdlM2E7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gNjk3Mi4yOSwxMzU0My42IGMgMjUuMjQsMy44IDM4LjQ4LDExLjMgNTguODQsMjYuOSAxMTkuMjUsOTEuNSAyMzAuMywxOTYuMiAzNDUuODQsMjkyLjUgMTM5LjMzLDExNS4zIDI4NS41NiwyMjEgNDM4LjcxLDMxNy4xIC0yOC4xMSwtMjQ1LjcgLTQ0Ljg2LC00OTMuMSAtNjkuNzIsLTczOS4yIC0xOC42OCwtMTg0LjkgLTUxLjQzLC0zNzguMiAtNTEuMjYsLTU2My40IDM2Ni4yMSw0LjUgNzI5LjAxLC03NSAxMDc2LjIsLTE4Ni44IDY5LjQ1LC0yMi40IDE1Ny4wOSwtNDUuNSAyMTkuNjYsLTgxLjMgMjkuNTksLTkzLjggLTQ2Ljk4LC0xNzQuNCAtNDIuMjMsLTI2NS41IC0xNzYuMjIsMzYuOSAtMzUyLjI0LDk1LjIgLTUyNi42NSwxNDEuNSAtMTg5LjI1LC0xMS42IC0zOTUuMjksMTE5LjkgLTU4OS4wMSwxMjIuMSA2MS41NCwtMzMgMTMxLjE0LC00Mi45IDE5My41NywtNzQuNiBsIC0xLjUzLC0xMS44IGMgLTEyNy4zNCw0NC41IC0yNTMuNDUsODguMSAtMzgzLjYxLDEyMy43IC04Ny4wNiwtMjkxLjIgLTE2NC4wNSwtNjA5IC0yMDcuNTksLTkwOS41IGwgMjEuNDEsLTEwLjYgYyAtOTAuNjksLTI0LjcgLTE4NS44MywtNDcuOCAtMjc5LjU3LC01Ni4zIDY5LjYyLC04My41IDM3MC4yOCwtMzQ2LjkgNDY4LjU5LC0zNTguOSAyNjIuNzcsLTE2OS40IDUwMy4xLC0zMDEuOSA4MjMuNCwtMjMwLjEgOS4wNSwyIDE4LjAzLDQuNCAyNy4wMyw2LjcgbCAyLjk0LC04LjQgQyA4MTIwLjQyLDEwODc2IDczOTAuMjIsMTEyNjEgNzA2Mi4yNywxMDk5NyBjIC0xMS4wOSwtMjMyLjIgNTQuMjYsLTQ3My43IDE1NC44MiwtNjgxLjQgMjMyLjM0LC00NzkuOSA2NTcuMTcsLTg0MS45IDkxOS4yNiwtMTMwNy42IDE3MS4wMSwtMzA0IDM2MC41NiwtOTM3LjkgNTY1LjE5LC0xMTU3LjMgMTAuNzIsLTExLjUgMzEuMDgsLTI3LjkgNDcuMjksLTI3LjUgMjEuODQsMC41IDQwLjAyLDE0LjEgNTguMTgsMjUgMzEuMzksLTExIDM5LjM5LC0yNy40IDU0LjY0LC01Ni42IDIxLjkzLC05LjkgMzguMzksLTExLjYgNjIuMzMsLTEyLjggbCAzNi40MiwtMzguMyBjIDExMS42MiwtMTIuNiAyMjguMDQsLTQ4LjYgMzM5LjEsLTcxLjEgMTE4LjU5LC0yMzQuNyAyMzEuOTIsLTM2Mi44IDQ4OC4zNywtNDQ1LjIgNTYuNjIsLTE4LjIgMTE2Ljg3LC0zMi4xIDE3NS45OCwtMzguOSA2OC41NSwtNy44IDE1OC43NSwxMS4zIDIyMC41NSwtMTkuNiAtNTkuNiwtMTIuOSAtMTE5LjgsLTIwLjIgLTE4MC43LC0yMi4xIDE1LC02Ni4zIDM2LjcsLTEyOC43IDU5LjgsLTE5Mi41IC0yMjEuNDksNS4zIC01ODUuNTEsLTQuMiAtNzU4LjczLC0xNjUgLTUxLjI0LC00Ny42IC04MS42LC0xMDkuNCAtODMuMTYsLTE3OS42IC0yLjQsLTEwNi4zIDU5LjA3LC0yMDMuOSAxMzIuMDgsLTI3Ni4zIDIzOC4zLC0yMzYuNSA2MTkuMTMsLTMxOS45IDk0My44MSwtMzE1LjkgMjEzLjgsMi42IDQxMS4zLDUyLjkgNjIwLjQsODUgLTIyMS45LC0xODAuOCAtNTg5LjQsLTI0MC42IC04NjYuOCwtMjQxLjcgLTg3MC4yNSwtMy43IC0xNDY2LjA5LDU3Ny44IC0yMDQyLjI5LDExNTAuMyAtOTUuMzMsMTA2LjcgLTE5NC4yMywyMDcuNCAtMjgzLjYzLDMxOS42IC00MDcuODksNTEyLjMgLTYzMC42MiwxMDkxLjQgLTc3MC4zNywxNzI1LjggLTE4LjcsMTIwLjUgLTY0Ljk2LDI0Mi4yIC05Mi40NCwzNjEuOCAtMzAuNjQsMTMzLjQgLTQzLjQ3LDI4Mi4zIC04Ni40NCw0MTEuMiAtNDUuODQsMjAyLjUgLTgyLjA4LDQwNi43IC0xMTkuNzMsNjEwLjggLTE2LjEzLDg3LjUgLTI0LjQ0LDIwNS40IC01OC4zMywyODYuNyAtOS40OSw4NC42IC0yMC43MiwxNjkgLTI4LjMyLDI1My45IC00NC42OSw0OTkuNyAtOTMuNDksMTU4NiA3NC4wMSwyMDQ2IDcxLjA2LDE5NS4yIDE5Ni42MiwzNjIuMSAzMjguNzMsNTE5LjkiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PHBhdGgKICAgICAgICAgaWQ9InBhdGgyNjYiCiAgICAgICAgIHN0eWxlPSJmaWxsOiNhMjFjMzA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgIGQ9Im0gODk2MC40LDc3NDAuNSBjIDExMS42MiwtMTIuNiAyMjguMDQsLTQ4LjYgMzM5LjEsLTcxLjEgMTE4LjU5LC0yMzQuNyAyMzEuOTIsLTM2Mi44IDQ4OC4zNywtNDQ1LjIgNTYuNjIsLTE4LjIgMTE2Ljg3LC0zMi4xIDE3NS45OCwtMzguOSA2OC41NSwtNy44IDE1OC43NSwxMS4zIDIyMC41NSwtMTkuNiAtNTkuNiwtMTIuOSAtMTE5LjgsLTIwLjIgLTE4MC43LC0yMi4xIC00MiwzLjIgLTg0LjE2LDIuNiAtMTI2LjE1LDYuMyAtNDIyLjcsMzYuNyAtNjU1Ljc3LDI4Ni4yIC05MTcuMTUsNTkwLjYiCiAgICAgICAgIGlua3NjYXBlOmNvbm5lY3Rvci1jdXJ2YXR1cmU9IjAiIC8+PGcKICAgICAgICAgaWQ9ImcyNjgiPjxnCiAgICAgICAgICAgY2xpcC1wYXRoPSJ1cmwoI2NsaXBQYXRoMjc0KSIKICAgICAgICAgICBpZD0iZzI3MCI+PHBhdGgKICAgICAgICAgICAgIGlkPSJwYXRoMjgyIgogICAgICAgICAgICAgc3R5bGU9ImZpbGw6dXJsKCNsaW5lYXJHcmFkaWVudDI4MCk7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiCiAgICAgICAgICAgICBkPSJtIDc2OTQuNywxMjg3Ny41IGMgMzY2LjIxLDQuNSA3MjkuMDEsLTc1IDEwNzYuMiwtMTg2LjggNjkuNDUsLTIyLjQgMTU3LjA5LC00NS41IDIxOS42NiwtODEuMyAyOS41OSwtOTMuOCAtNDYuOTgsLTE3NC40IC00Mi4yMywtMjY1LjUgLTE3Ni4yMiwzNi45IC0zNTIuMjQsOTUuMiAtNTI2LjY1LDE0MS41IC0yMDUuOTMsNTguNSAtNzE4Ljg2LDIwOC41IC05MTEuMjQsMjA2LjUgLTI2MC4zMiwtMi42IC00NjcuNzMsLTE3OC4zIC02MzguNzIsLTM1NSAxNS4xMSwyMyAzMS40LDQ0LjkgNDguNDcsNjYuNSAxOTYuNCwyNDguMiA0NTUuODQsNDM4LjEgNzc0LjUxLDQ3NC4xIgogICAgICAgICAgICAgaW5rc2NhcGU6Y29ubmVjdG9yLWN1cnZhdHVyZT0iMCIgLz48L2c+PC9nPjwvZz48L2c+PC9zdmc+" alt="Mei">
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
    const items = ["Čo dnes variť?", "Recept na ramen", "Čím nahradiť mirin?", "Najlepšia sushi ryža", "Kokosové mlieko"];
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
      addMessage("assistant", "<strong>Ahojte!</strong><br><br>Som Mei a rada vám pomôžem objaviť svet ázijskej kuchyne.<br><br>Môžem odporučiť recept, nájsť vhodné produkty, poradiť s varením alebo pomôcť nahradiť ingredienciu.");
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
    const lb = document.querySelector('.fl-ai-label-block');
    if (lb) lb.style.display = panel.classList.contains("is-open") ? 'none' : '';
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
