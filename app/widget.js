(function () {
  const config = window.FoodlandAI || {};
  const apiBaseUrl = config.apiBaseUrl || "https://foodland-ai-agent-production.up.railway.app";
  const meiAvatarDataUri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAACXBIWXMAAAsTAAALEwEAmpwYAAAFFmlUWHRYTUw6Y29tLmFkb2JlLnhtcAAAAAAAPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgNS42LWMxNDggNzkuMTY0MDM2LCAyMDE5LzA4LzEzLTAxOjA2OjU3ICAgICAgICAiPiA8cmRmOlJERiB4bWxuczpyZGY9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkvMDIvMjItcmRmLXN5bnRheC1ucyMiPiA8cmRmOkRlc2NyaXB0aW9uIHJkZjphYm91dD0iIiB4bWxuczp4bXA9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC8iIHhtbG5zOmRjPSJodHRwOi8vcHVybC5vcmcvZGMvZWxlbWVudHMvMS4xLyIgeG1sbnM6cGhvdG9zaG9wPSJodHRwOi8vbnMuYWRvYmUuY29tL3Bob3Rvc2hvcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RFdnQ9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZUV2ZW50IyIgeG1wOkNyZWF0b3JUb29sPSJBZG9iZSBQaG90b3Nob3AgMjEuMSAoV2luZG93cykiIHhtcDpDcmVhdGVEYXRlPSIyMDI2LTA3LTIwVDIzOjQyOjIxKzAyOjAwIiB4bXA6TW9kaWZ5RGF0ZT0iMjAyNi0wNy0yMVQwMToxNzo1OCswMjowMCIgeG1wOk1ldGFkYXRhRGF0ZT0iMjAyNi0wNy0yMVQwMToxNzo1OCswMjowMCIgZGM6Zm9ybWF0PSJpbWFnZS9wbmciIHBob3Rvc2hvcDpDb2xvck1vZGU9IjMiIHBob3Rvc2hvcDpJQ0NQcm9maWxlPSJzUkdCIElFQzYxOTY2LTIuMSIgeG1wTU06SW5zdGFuY2VJRD0ieG1wLmlpZDpkMzc3MGQxNC05NTc1LTA1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";
  const foodlandSymbolDataUri = "data:image/png;base64,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";
  const isDemoPage = window.location.protocol === "file:" || /\/static\/widget\.html$/.test(window.location.pathname);
  const demoMode = Boolean(config.demoMode && config.allowDemoMode && isDemoPage);
  const maxQuestionsPerMinute = config.maxQuestionsPerMinute || 8;
  const recentQuestions = [];
  let lastProductSubject = "";
  let lastRecipeSubject = "";
  const clientId = getOrCreateClientId();
  let popularQuestions = [];
  let popularQuestionsLoaded = false;
  let quickSuggestionsWrap = null;

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
    .fl-ai-root, .fl-ai-root *, .fl-ai-autocomplete, .fl-ai-autocomplete * { box-sizing: border-box; letter-spacing: 0; }
    .fl-ai-root {
      position: fixed;
      right: max(20px, env(safe-area-inset-right));
      bottom: max(20px, env(safe-area-inset-bottom));
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
      display: inline-block;
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
    }
    .fl-ai-label-sub {
      display: inline-block;
      background: rgba(20, 40, 28, 0.55);
      color: #fff;
      font-size: 9px;
      font-weight: 500;
      padding: 2px 8px;
      border-radius: 8px;
      white-space: nowrap;
      backdrop-filter: blur(4px);
      pointer-events: none;
    }
    .fl-ai-avatar {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: cover;
      object-position: center 34%;
      transform: scale(1.18);
      transform-origin: center center;
    }
    .fl-ai-panel {
      position: fixed;
      right: max(20px, env(safe-area-inset-right));
      bottom: calc(76px + env(safe-area-inset-bottom));
      z-index: 2147483001;
      width: min(410px, calc(100vw - 32px));
      height: min(640px, calc(var(--fl-ai-vh, 100vh) - 116px));
      max-height: calc(var(--fl-ai-vh, 100vh) - 116px);
      display: none;
      flex-direction: column;
      pointer-events: auto;
      overflow: hidden;
      overscroll-behavior: contain;
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
      width: 50px;
      height: 50px;
      display: block;
      flex: 0 0 auto;
      overflow: hidden;
      border: 2px solid rgba(255, 255, 255, 0.55);
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.14);
    }
    .fl-ai-mark img {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: cover;
      object-position: center 34%;
      transform: scale(1.18);
      transform-origin: center center;
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
      -webkit-overflow-scrolling: touch;
      overscroll-behavior: contain;
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
    .fl-ai-product-reason {
      margin: 0 0 7px;
      color: #52645a;
      font-size: 12px;
      line-height: 1.35;
    }
    .fl-ai-product-group {
      color: #299B5E;
      font-weight: 800;
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
    .fl-ai-recipes, .fl-ai-articles { display: grid; gap: 10px; margin: 0 0 12px; }
    .fl-ai-recipe, .fl-ai-article {
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid #dde7df;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 20px rgba(29, 48, 38, 0.06);
    }
    .fl-ai-recipe-title, .fl-ai-article-title {
      margin: 0;
      color: #221F20;
      font-size: 14px;
      line-height: 1.28;
      font-weight: 800;
    }
    .fl-ai-recipe-meta, .fl-ai-article-meta {
      color: #5d6d63;
      font-size: 12px;
      line-height: 1.35;
    }
    .fl-ai-notice[hidden] { display: none; }
    .fl-ai-recipe-link, .fl-ai-article-link {
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
      position: relative;
      z-index: 4;
    }
    .fl-ai-input-wrap {
      position: relative;
      min-width: 0;
      z-index: 5;
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
    .fl-ai-autocomplete {
      position: fixed;
      left: 0;
      top: 0;
      width: 320px;
      display: none;
      max-height: min(220px, calc(var(--fl-ai-vh, 100vh) - 24px));
      overflow: auto;
      border: 1px solid #d7e4dc;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 14px 36px rgba(20, 36, 28, 0.18);
      z-index: 2147483647;
    }
    .fl-ai-autocomplete.is-open { display: block; }
    .fl-ai-autocomplete button {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 9px 11px;
      border: 0;
      border-bottom: 1px solid #eef3f0;
      background: #fff;
      color: #221F20;
      font-size: 13px;
      text-align: left;
      cursor: pointer;
    }
    .fl-ai-autocomplete button:hover,
    .fl-ai-autocomplete button.is-active {
      background: #f2faf5;
    }
    .fl-ai-suggest-type {
      color: #299B5E;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }
    .fl-ai-suggest-label {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .fl-ai-suggest-label mark {
      background: #DFF4E9;
      color: #116B3B;
      border-radius: 3px;
      padding: 0 1px;
      font-weight: 800;
    }
    @keyframes fl-ai-pulse {
      0%, 100% { opacity: 0.35; transform: translateY(0); }
      50% { opacity: 1; transform: translateY(-2px); }
    }
    @media (max-width: 520px) {
      .fl-ai-root {
        right: max(10px, env(safe-area-inset-right));
        bottom: max(10px, env(safe-area-inset-bottom));
      }
      .fl-ai-panel {
        inset: auto max(8px, env(safe-area-inset-right)) calc(68px + env(safe-area-inset-bottom)) max(8px, env(safe-area-inset-left));
        width: auto;
        height: min(650px, calc(var(--fl-ai-vh, 100svh) - 96px - env(safe-area-inset-top)));
        max-height: calc(var(--fl-ai-vh, 100svh) - 96px - env(safe-area-inset-top));
      }
      .fl-ai-launcher { width: 58px; height: 58px; }
      .fl-ai-mark { width: 48px; height: 48px; }
      .fl-ai-form { grid-template-columns: 1fr; }
      .fl-ai-autocomplete { max-height: 180px; }
      .fl-ai-submit { min-height: 40px; }
      .fl-ai-product {
        grid-template-columns: 64px minmax(0, 1fr);
        gap: 9px;
        padding: 9px;
      }
      .fl-ai-product img,
      .fl-ai-product-image-fallback {
        width: 64px;
        height: 64px;
      }
      .fl-ai-product-title { font-size: 12px; line-height: 1.25; }
      .fl-ai-product-meta { font-size: 11px; gap: 5px; }
      .fl-ai-product-reason {
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      .fl-ai-product-actions {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
      }
      .fl-ai-product-link,
      .fl-ai-cart-btn {
        width: 100%;
        min-height: 36px;
        padding: 7px 8px;
      }
      .fl-ai-show-more { min-height: 40px; }
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
          <div class="fl-ai-mark">
            <img src="${meiAvatarDataUri}" alt="Foodland Mei" loading="lazy" />
          </div>
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
        <div class="fl-ai-input-wrap">
          <input class="fl-ai-input" type="text" placeholder="Napíšte, čo hľadáte..." autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="fl-ai-autocomplete" />
          <div class="fl-ai-autocomplete" id="fl-ai-autocomplete" role="listbox" aria-label="Návrhy vyhľadávania"></div>
        </div>
        <button class="fl-ai-submit" type="submit">Poslať</button>
      </form>
    </section>
    <div class="fl-ai-launcher-wrap">
      <div class="fl-ai-label-block">
        <span class="fl-ai-label-title">💬 Poraďte sa s Mei</span>
    </div>
    <button class="fl-ai-launcher" type="button" aria-label="Otvoriť Foodland poradcu">
      <img class="fl-ai-avatar" src="${meiAvatarDataUri}" alt="Foodland Mei" loading="lazy" />
    </button>
    </div>
  `;
  document.body.appendChild(root);

  const panel = root.querySelector(".fl-ai-panel");
  const launcher = root.querySelector(".fl-ai-launcher");
  const launcherWrap = root.querySelector(".fl-ai-launcher-wrap");
  const closeButton = root.querySelector(".fl-ai-close");
  const notice = root.querySelector(".fl-ai-notice");
  const messages = root.querySelector(".fl-ai-messages");
  let conversationHistory = [];
  const sessionId = Math.random().toString(36).slice(2, 12);

  function getOrCreateClientId() {
    const storageKey = "foodland_ai_client_id";
    try {
      const existing = window.localStorage && window.localStorage.getItem(storageKey);
      if (existing && /^[a-zA-Z0-9_-]{12,96}$/.test(existing)) return existing;
      const generated = "fl-" + randomId(24);
      window.localStorage && window.localStorage.setItem(storageKey, generated);
      return generated;
    } catch (error) {
      return "fl-session-" + randomId(18);
    }
  }

  function randomId(length) {
    const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    const bytes = new Uint8Array(length);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    }
    let result = "";
    for (let i = 0; i < bytes.length; i += 1) {
      result += chars[bytes[i] % chars.length];
    }
    return result;
  }
  const form = root.querySelector(".fl-ai-form");
  const input = root.querySelector(".fl-ai-input");
  const submit = root.querySelector(".fl-ai-submit");
  const autocomplete = root.querySelector(".fl-ai-autocomplete");
  document.body.appendChild(autocomplete);
  let suggestTimer = null;
  let suggestAbortController = null;
  const autocompleteCache = new Map();
  let activeSuggestionIndex = -1;
  let currentSuggestions = [];

  function updateViewportHeight() {
    const viewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    root.style.setProperty("--fl-ai-vh", `${Math.max(320, Math.round(viewportHeight))}px`);
    positionAutocomplete();
  }

  updateViewportHeight();
  window.addEventListener("resize", updateViewportHeight);
  window.addEventListener("orientationchange", updateViewportHeight);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", updateViewportHeight);
  }

  function shouldAutoFocusInput() {
    const isSmallScreen = window.matchMedia("(max-width: 520px)").matches;
    const isTouch = navigator.maxTouchPoints > 0 || "ontouchstart" in window;
    return !isSmallScreen && !isTouch;
  }

  function currentPageProductTitle() {
    const selectors = [
      "h1.product-title",
      ".product-title h1",
      ".vm-product-details-container h1",
      ".productdetails h1",
      "h1",
    ];
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      const text = element ? element.textContent.trim() : "";
      if (isUsableProductTitle(text, selector)) return text;
    }
    return "";
  }

  function isUsableProductTitle(text, selector) {
    const title = String(text || "").replace(/\s+/g, " ").trim();
    if (!title || title.length < 3 || title.length > 120) return false;
    const normalized = title
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
    const genericTitles = new Set([
      "uvod",
      "domov",
      "homepage",
      "akcia",
      "akcie",
      "novinky",
      "kontakt",
      "blog",
      "recepty",
      "kosik",
      "vyhladavanie",
      "prihlasenie",
      "registracia",
    ]);
    if (genericTitles.has(normalized)) return false;
    if (selector !== "h1") return true;
    return Boolean(document.querySelector(".productdetails, .vm-product-details-container, [itemtype*='Product'], [data-product-id]"));
  }

  function compactPromptProductName(title) {
    return String(title || "")
      .replace(/\s+/g, " ")
      .replace(/\b\d+[,.]?\d*\s*(g|kg|ml|l|ks|cm|mm)\b/gi, "")
      .trim()
      .slice(0, 70);
  }

  function initialSuggestionItems() {
    const productTitle = compactPromptProductName(currentPageProductTitle());
    if (productTitle) {
      return [
        `Doplnky k ${productTitle}`,
        `Recept s ${productTitle}`,
        `Čím nahradiť ${productTitle}?`,
        `Ako použiť ${productTitle}?`,
      ];
    }
    if (popularQuestions.length) return popularQuestions.slice(0, 5);
    return ["Čo variť na večeru?", "Recept na ramen", "Čím nahradiť mirin?", "Najlepšia sushi ryža", "Kokosové mlieko"];
  }

  function normalizeQuickQuestion(value) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, 90);
  }

  async function fetchPopularQuestions() {
    if (popularQuestionsLoaded || demoMode) return;
    popularQuestionsLoaded = true;
    try {
      const response = await fetch(`${apiBaseUrl}/suggested-questions?days=14&limit=5`, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const data = await response.json();
      const questions = (data.questions || [])
        .map(function (item) { return normalizeQuickQuestion(item.question || item.label || item); })
        .filter(function (label, index, all) { return label && all.indexOf(label) === index; })
        .slice(0, 5);
      if (!questions.length) return;
      popularQuestions = questions;
      refreshQuickSuggestions();
    } catch (error) {
      // Suggested questions are optional; keep static fallback chips if analytics is unavailable.
    }
  }

  function addSuggestions() {
    fetchPopularQuestions();
    const items = initialSuggestionItems();
    const wrap = document.createElement("div");
    wrap.className = "fl-ai-suggestions";
    quickSuggestionsWrap = wrap;
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
    setLauncherVisible(false);
    if (messages.children.length === 0) {
      addMessage("assistant", "Ahojte!\n\nSom Mei a rada vám pomôžem objaviť svet ázijskej kuchyne.\n\nMôžem odporučiť recept, nájsť vhodné produkty, poradiť s varením alebo pomôcť nahradiť ingredienciu.");
      addSuggestions();
    }
    if (shouldAutoFocusInput()) {
      window.setTimeout(function () { input.focus(); }, 50);
    }
  }

  function closeAutocomplete() {
    currentSuggestions = [];
    activeSuggestionIndex = -1;
    autocomplete.classList.remove("is-open");
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    autocomplete.style.left = "";
    autocomplete.style.top = "";
    autocomplete.style.width = "";
    autocomplete.style.maxHeight = "";
    autocomplete.innerHTML = "";
  }

  function suggestionTypeLabel(type) {
    return {
      product: "Produkt",
      brand: "Značka",
      category: "Kategória",
      recipe: "Recept",
      synonym: "Tip",
      buy_intent: "Produkt",
      cook_intent: "Recept",
      explain_intent: "Tip",
      replace_intent: "Náhrada",
    }[type] || "Tip";
  }

  function renderSuggestionLabel(item) {
    const label = String((item && (item.label || item.query)) || "");
    const ranges = Array.isArray(item && item.highlight) ? item.highlight : [];
    if (!label || !ranges.length) return escapeHtml(label);

    let html = "";
    let cursor = 0;
    ranges
      .map(function (range) {
        return {
          start: Math.max(0, Math.min(label.length, Number(range.start) || 0)),
          end: Math.max(0, Math.min(label.length, Number(range.end) || 0)),
        };
      })
      .filter(function (range) { return range.end > range.start; })
      .sort(function (a, b) { return a.start - b.start; })
      .forEach(function (range) {
        if (range.start < cursor) return;
        html += escapeHtml(label.slice(cursor, range.start));
        html += "<mark>" + escapeHtml(label.slice(range.start, range.end)) + "</mark>";
        cursor = range.end;
      });
    html += escapeHtml(label.slice(cursor));
    return html;
  }

  function renderAutocomplete(items) {
    currentSuggestions = Array.isArray(items) ? items : [];
    activeSuggestionIndex = -1;
    autocomplete.innerHTML = "";
    if (!currentSuggestions.length) {
      closeAutocomplete();
      return;
    }
    currentSuggestions.forEach(function (item, index) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = `fl-ai-suggest-${index}`;
      btn.setAttribute("role", "option");
      btn.innerHTML = `<span class="fl-ai-suggest-label">${renderSuggestionLabel(item)}</span><span class="fl-ai-suggest-type">${escapeHtml(suggestionTypeLabel(item.type))}</span>`;
      btn.addEventListener("mousedown", function (event) {
        event.preventDefault();
        applySuggestion(index);
      });
      autocomplete.appendChild(btn);
    });
    autocomplete.classList.add("is-open");
    input.setAttribute("aria-expanded", "true");
    positionAutocomplete();
  }

  function positionAutocomplete() {
    if (!autocomplete.classList.contains("is-open")) return;
    const rect = input.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const viewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    const viewportWidth = window.visualViewport ? window.visualViewport.width : window.innerWidth;
    const gap = 6;
    const sidePadding = 8;
    const panelPadding = 12;
    const panelWidth = panelRect.width || rect.width;
    const desiredWidth = Math.max(220, Math.min(panelWidth - (panelPadding * 2), viewportWidth - (sidePadding * 2)));
    const preferredLeft = panelRect.width ? panelRect.left + panelPadding : rect.left;
    const left = Math.max(sidePadding, Math.min(preferredLeft, viewportWidth - desiredWidth - sidePadding));
    const spaceAbove = rect.top - sidePadding;
    const spaceBelow = viewportHeight - rect.bottom - sidePadding;
    const availableSpace = Math.max(spaceAbove, spaceBelow);
    const maxHeight = Math.min(220, Math.max(120, availableSpace - gap));

    autocomplete.style.width = `${Math.round(desiredWidth)}px`;
    autocomplete.style.left = `${Math.round(left)}px`;
    autocomplete.style.maxHeight = `${Math.round(maxHeight)}px`;
    if (spaceAbove >= 150 || spaceAbove > spaceBelow) {
      autocomplete.style.top = `${Math.max(sidePadding, Math.round(rect.top - maxHeight - gap))}px`;
    } else {
      autocomplete.style.top = `${Math.min(viewportHeight - 80, Math.round(rect.bottom + gap))}px`;
    }
  }

  function applySuggestion(index) {
    const item = currentSuggestions[index];
    if (!item) return;
    input.value = item.query || item.label || "";
    closeAutocomplete();
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  }

  async function fetchAutocomplete(value) {
    const query = value.trim();
    if (query.length < 2 || demoMode) {
      closeAutocomplete();
      return;
    }
    const cacheKey = query.toLowerCase();
    if (autocompleteCache.has(cacheKey)) {
      renderAutocomplete(autocompleteCache.get(cacheKey));
      return;
    }
    if (suggestAbortController) {
      suggestAbortController.abort();
    }
    suggestAbortController = new AbortController();
    try {
      let response = await fetch(`${apiBaseUrl}/search/autocomplete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, limit: 7, client_id: clientId }),
        signal: suggestAbortController.signal,
      });
      if (!response.ok) {
        response = await fetch(`${apiBaseUrl}/products/suggest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, limit: 7 }),
          signal: suggestAbortController.signal,
        });
      }
      if (!response.ok) return closeAutocomplete();
      const data = await response.json();
      if (input.value.trim() !== query) return;
      const suggestions = data.suggestions || [];
      autocompleteCache.set(cacheKey, suggestions);
      if (autocompleteCache.size > 40) {
        autocompleteCache.delete(autocompleteCache.keys().next().value);
      }
      renderAutocomplete(suggestions);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      closeAutocomplete();
    }
  }

  function updateActiveSuggestion(nextIndex) {
    const buttons = autocomplete.querySelectorAll("button");
    buttons.forEach(function (button) { button.classList.remove("is-active"); });
    activeSuggestionIndex = nextIndex;
    if (buttons[activeSuggestionIndex]) {
      buttons[activeSuggestionIndex].classList.add("is-active");
      input.setAttribute("aria-activedescendant", buttons[activeSuggestionIndex].id);
      buttons[activeSuggestionIndex].scrollIntoView({ block: "nearest" });
    }
  }

  function closePanel() {
    closeAutocomplete();
    panel.classList.remove("is-open");
    setLauncherVisible(true);
  }

  function setLauncherVisible(visible) {
    if (launcherWrap) launcherWrap.style.display = visible ? "" : "none";
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
    message.innerHTML = `<span class="fl-ai-loading">Hľadám najvhodnejšiu odpoveď vo Foodland poradni <span class="fl-ai-dot"></span><span class="fl-ai-dot"></span><span class="fl-ai-dot"></span></span>`;
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

  function addArticles(articles) {
    if (!Array.isArray(articles) || articles.length === 0) return;

    const wrap = document.createElement("div");
    wrap.className = "fl-ai-articles";
    articles.slice(0, 3).forEach(function (article) {
      const title = article.title || "Foodland článok";
      const topic = article.topic || "Foodland magazín";
      const note = article.note ? ` · ${article.note}` : "";
      const card = document.createElement("article");
      card.className = "fl-ai-article";
      card.innerHTML = `
        <h3 class="fl-ai-article-title">${escapeHtml(title)}</h3>
        <div class="fl-ai-article-meta">${escapeHtml(topic + note)}</div>
        <a class="fl-ai-article-link" href="${escapeAttr(article.link || "https://www.foodland.sk/blog/")}" target="_blank" rel="noopener">Otvoriť článok</a>
      `;
      wrap.appendChild(card);
    });
    messages.appendChild(wrap);
    scrollToBottom();
  }

  function refreshQuickSuggestions() {
    if (!quickSuggestionsWrap || !quickSuggestionsWrap.isConnected) return;
    if (currentPageProductTitle()) return;
    const items = initialSuggestionItems();
    quickSuggestionsWrap.innerHTML = "";
    items.forEach(function (label) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "fl-ai-suggestion";
      btn.textContent = label;
      btn.addEventListener("click", function () {
        quickSuggestionsWrap.remove();
        input.value = label;
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      });
      quickSuggestionsWrap.appendChild(btn);
    });
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
          ${product.recommendation_reason ? `<p class="fl-ai-product-reason"><span class="fl-ai-product-group">${escapeHtml(product.recommendation_group || "Odporúčané")}</span>: ${escapeHtml(product.recommendation_reason)}</p>` : ""}
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

  function cartCandidatesToProducts(candidates) {
    if (!Array.isArray(candidates)) return [];
    return candidates
      .filter(function (candidate) {
        return candidate && (candidate.title || candidate.link);
      })
      .map(function (candidate) {
        return {
          id: candidate.product_id || "",
          title: candidate.title || "Odporúčaný produkt Foodland",
          effective_price: typeof candidate.price === "number" ? candidate.price : null,
          currency: candidate.currency || "EUR",
          availability: "in_stock",
          brand: "",
          image_link: "",
          link: candidate.link || "",
          recommendation_group: candidate.recommendation_group || "Do košíka",
          recommendation_reason: candidate.recommendation_reason || candidate.reason || "Kandidát pripravený podľa odporúčania Foodland Mei.",
        };
      });
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
      body: JSON.stringify({
        message: backendText,
        limit: 6,
        conversation_history: conversationHistory,
        session_id: sessionId,
        client_id: clientId,
      }),
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
    return escaped.replace(/\n/g, '<br>').replace(
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

  input.addEventListener("input", function () {
    window.clearTimeout(suggestTimer);
    suggestTimer = window.setTimeout(function () {
      fetchAutocomplete(input.value);
    }, 320);
  });

  input.addEventListener("focus", function () {
    if (input.value.trim().length >= 2) fetchAutocomplete(input.value);
  });

  input.addEventListener("keydown", function (event) {
    if (!autocomplete.classList.contains("is-open")) return;
    if (event.key === "Escape") {
      closeAutocomplete();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      updateActiveSuggestion(Math.min(currentSuggestions.length - 1, activeSuggestionIndex + 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      updateActiveSuggestion(Math.max(0, activeSuggestionIndex - 1));
      return;
    }
    if (event.key === "Enter" && activeSuggestionIndex >= 0) {
      event.preventDefault();
      applySuggestion(activeSuggestionIndex);
    }
  });

  input.addEventListener("blur", function () {
    window.setTimeout(closeAutocomplete, 120);
  });

  window.addEventListener("scroll", positionAutocomplete, true);

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    closeAutocomplete();

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
      addArticles(data.articles);
      if (data.intent !== "recipe") {
        addProducts(data.products);
        if (!Array.isArray(data.products) || data.products.length === 0) {
          addProducts(cartCandidatesToProducts(data.cart_candidates));
        }
      }
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

