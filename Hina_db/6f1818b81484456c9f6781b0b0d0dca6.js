document.addEventListener("DOMContentLoaded", () => {
    // Affiliate ID Management State
    const defaultTag = "techgearhub-20";
    let amazonAffiliateTag = localStorage.getItem("amazon_affiliate_tag") || defaultTag;

    // Cart / Product Comparison State
    let compareList = JSON.parse(localStorage.getItem("compare_list")) || [];

    // Filter & Search State
    let activeCategory = "All";
    let searchQuery = "";
    let sortMethod = "featured";

    // Dynamic DOM elements
    const tagInput = document.getElementById("affiliate-tag-input");
    const saveTagBtn = document.getElementById("save-tag-btn");
    const productsGrid = document.getElementById("products-grid");
    const categoriesContainer = document.getElementById("categories-container");
    const searchInput = document.getElementById("search-input");
    const searchInputMobile = document.getElementById("search-input-mobile");
    const sortSelect = document.getElementById("sort-select");
    const currentCategoryTitle = document.getElementById("current-category-title");
    const productResultsCount = document.getElementById("product-results-count");
    const currentYearSpan = document.getElementById("current-year");

    // Modal DOM Elements
    const productModal = document.getElementById("product-modal");
    const closeModalOverlay = document.getElementById("close-modal-overlay");
    const closeModalBtn = document.getElementById("close-modal-btn");
    const modalProductImg = document.getElementById("modal-product-img");
    const modalProductCategory = document.getElementById("modal-product-category");
    const modalProductTitle = document.getElementById("modal-product-title");
    const modalProductStars = document.getElementById("modal-product-stars");
    const modalProductRating = document.getElementById("modal-product-rating");
    const modalProductReviews = document.getElementById("modal-product-reviews");
    const modalProductSpecs = document.getElementById("modal-product-specs");
    const modalProductPros = document.getElementById("modal-product-pros");
    const modalProductCons = document.getElementById("modal-product-cons");
    const modalProductPrice = document.getElementById("modal-product-price");
    const modalBuyBtn = document.getElementById("modal-buy-btn");

    // Compare Drawer DOM Elements
    const compareBtn = document.getElementById("compare-btn");
    const compareCount = document.getElementById("compare-count");
    const compareDrawer = document.getElementById("compare-drawer");
    const closeCompareBtn = document.getElementById("close-compare-btn");
    const compareContent = document.getElementById("compare-content");
    const clearCompareBtn = document.getElementById("clear-compare-btn");
    const compareShopAllBtn = document.getElementById("compare-shop-all-btn");

    // Initialize Page
    currentYearSpan.textContent = new Date().getFullYear();
    tagInput.value = amazonAffiliateTag;
    renderCategories();
    renderProducts();
    updateCompareCounter();

    // Event Listeners
    saveTagBtn.addEventListener("click", () => {
        const rawTag = tagInput.value.trim();
        if (rawTag) {
            amazonAffiliateTag = rawTag;
            localStorage.setItem("amazon_affiliate_tag", rawTag);
            alert(`Success! Affiliate Tag changed to "${rawTag}". All Amazon links now redirect using your key.`);
            renderProducts(); // Refresh buttons to reflect new tag
        }
    });

    searchInput.addEventListener("input", (e) => {
        searchQuery = e.target.value.toLowerCase();
        renderProducts();
    });

    searchInputMobile.addEventListener("input", (e) => {
        searchQuery = e.target.value.toLowerCase();
        renderProducts();
    });

    sortSelect.addEventListener("change", (e) => {
        sortMethod = e.target.value;
        renderProducts();
    });

    // Close Modal Events
    closeModalBtn.addEventListener("click", closeModal);
    closeModalOverlay.addEventListener("click", closeModal);
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeModal();
            closeCompareDrawer();
        }
    });

    // Compare Drawer Events
    compareBtn.addEventListener("click", toggleCompareDrawer);
    closeCompareBtn.addEventListener("click", closeCompareDrawer);
    clearCompareBtn.addEventListener("click", clearComparison);

    // Newsletter Submission Simulation
    document.getElementById("newsletter-form").addEventListener("submit", (e) => {
        e.preventDefault();
        alert("Awesome choice! You've been subscribed to the newsletter. We will deliver curated Amazon coupon alerts directly to your inbox.");
        e.target.reset();
    });

    // Functions

    // Dynamic Affiliate Link Creator
    function generateAffiliateLink(amazonUrl) {
        if (!amazonUrl) return "#";
        const urlObj = new URL(amazonUrl);
        // Replace or add the affiliate tag query parameter
        urlObj.searchParams.set("tag", amazonAffiliateTag);
        return urlObj.toString();
    }

    // Dynamic category pill list setup
    function renderCategories() {
        // Collect distinct categories
        const categories = ["All", ...new Set(products.map(p => p.category))];
        categoriesContainer.innerHTML = categories.map(cat => `
            <button class="px-5 py-2.5 rounded-full text-sm font-semibold transition-all duration-200 border cursor-pointer ${
                activeCategory === cat 
                ? "bg-indigo-600 text-white border-indigo-600 shadow-md shadow-indigo-200" 
                : "bg-white text-slate-700 border-slate-200 hover:border-indigo-400 hover:text-indigo-600"
            }" onclick="filterByCategory('${cat}')">
                ${cat}
            </button>
        `).join('');
    }

    // Global category selector window binding
    window.filterByCategory = function(category) {
        activeCategory = category;
        currentCategoryTitle.textContent = category === "All" ? "All Curated Gear" : `${category} Curated Selection`;
        renderCategories();
        renderProducts();
    };

    // Main grid rendering function
    function renderProducts() {
        // Apply filters
        let filtered = products.filter(p => {
            const matchesCat = activeCategory === "All" || p.category === activeCategory;
            const matchesSearch = p.title.toLowerCase().includes(searchQuery) || 
                                  p.category.toLowerCase().includes(searchQuery) ||
                                  Object.values(p.specs).some(val => val.toLowerCase().includes(searchQuery));
            return matchesCat && matchesSearch;
        });

        // Apply Sorting
        if (sortMethod === "price-low") {
            filtered.sort((a, b) => a.price - b.price);
        } else if (sortMethod === "price-high") {
            filtered.sort((a, b) => b.price - a.price);
        } else if (sortMethod === "rating") {
            filtered.sort((a, b) => b.rating - a.rating);
        } else {
            // "Featured" fallback
            filtered.sort((a, b) => (b.featured ? 1 : 0) - (a.featured ? 1 : 0));
        }

        productResultsCount.textContent = `Showing ${filtered.length} product${filtered.length === 1 ? '' : 's'}`;

        if (filtered.length === 0) {
            productsGrid.innerHTML = `
                <div class="col-span-full py-16 text-center">
                    <i class="fa-solid fa-face-frown text-4xl text-slate-300 mb-3"></i>
                    <h3 class="text-lg font-bold text-slate-800">No gear matches search criteria</h3>
                    <p class="text-sm text-slate-500 mt-1">Try resetting your filter, checking your spelling, or typing another tech tag.</p>
                </div>
            `;
            return;
        }

        productsGrid.innerHTML = filtered.map(p => {
            const inCompare = compareList.includes(p.id);
            const dynamicLink = generateAffiliateLink(p.amazonUrl);
            
            // Build rating stars
            let stars = '';
            for (let i = 1; i <= 5; i++) {
                if (i <= Math.floor(p.rating)) {
                    stars += '<i class="fa-solid fa-star text-amber-400"></i>';
                } else if (i - p.rating < 1) {
                    stars += '<i class="fa-solid fa-star-half-stroke text-amber-400"></i>';
                } else {
                    stars += '<i class="fa-regular fa-star text-slate-300"></i>';
                }
            }

            return `
                <div class="bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-xl transition-all duration-300 flex flex-col justify-between overflow-hidden relative group">
                    <!-- Top Badge -->
                    ${p.featured ? `
                    <span class="absolute top-3 left-3 bg-indigo-600 text-white text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full z-10">
                        Top Pick
                    </span>` : ''}

                    <!-- Compare Toggle Icon -->
                    <button onclick="toggleCompareItem('${p.id}')" class="absolute top-3 right-3 z-10 w-9 h-9 rounded-full flex items-center justify-center transition-colors shadow-sm ${
                        inCompare 
                        ? 'bg-rose-500 text-white hover:bg-rose-600' 
                        : 'bg-white text-slate-500 hover:text-slate-800 border border-slate-200'
                    }" title="Compare Product">
                        <i class="fa-solid fa-right-left text-sm"></i>
                    </button>

                    <!-- Product Image Container -->
                    <div class="pt-6 px-6 cursor-pointer overflow-hidden" onclick="openProductModal('${p.id}')">
                        <div class="bg-slate-50 rounded-xl h-48 flex items-center justify-center p-4 transform group-hover:scale-[1.03] transition-transform duration-300">
                            <img src="${p.imageUrl}" alt="${p.title}" class="max-h-full max-w-full object-contain rounded-md">
                        </div>
                    </div>

                    <!-- Details Area -->
                    <div class="p-6 flex-grow flex flex-col justify-between">
                        <div>
                            <span class="text-xs font-bold text-indigo-600 uppercase tracking-wide block mb-1">${p.category}</span>
                            <h3 class="font-bold text-slate-900 group-hover:text-indigo-600 cursor-pointer transition-colors text-sm line-clamp-2 leading-tight" onclick="openProductModal('${p.id}')">
                                ${p.title}
                            </h3>

                            <!-- Stars & Rating counts -->
                            <div class="flex items-center gap-1.5 mt-2 mb-4">
                                <div class="flex text-xs">${stars}</div>
                                <span class="text-xs font-semibold text-slate-800">${p.rating}</span>
                                <span class="text-[10px] text-slate-400">(${p.reviewsCount})</span>
                            </div>

                            <!-- Bullet Feature Callouts -->
                            <div class="space-y-1 mb-4 border-t border-slate-100 pt-3">
                                ${p.pros.slice(0, 2).map(pro => `
                                    <div class="flex items-start gap-1.5 text-xs text-slate-600">
                                        <i class="fa-solid fa-check text-emerald-500 mt-0.5"></i>
                                        <span class="line-clamp-1">${pro}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>

                        <!-- Footer Price Action Block -->
                        <div>
                            <div class="flex items-baseline gap-1 mb-4">
                                <span class="text-xs text-slate-400 font-medium">Amazon Price:</span>
                                <span class="text-2xl font-black text-slate-900">$${p.price.toFixed(2)}</span>
                            </div>

                            <div class="grid grid-cols-5 gap-2">
                                <button onclick="openProductModal('${p.id}')" class="col-span-1.5 flex items-center justify-center bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold py-3 px-1 rounded-xl text-xs transition-colors" title="Read Details & Pros/Cons">
                                    Specs
                                </button>
                                <a href="${dynamicLink}" target="_blank" rel="noopener sponsored" class="col-span-3.5 flex items-center justify-center gap-1.5 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 text-slate-950 font-bold py-3 px-3 rounded-xl text-xs transition-colors shadow-sm hover:shadow">
                                    <i class="fa-brands fa-amazon text-sm"></i> Buy Now
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Modal Control System
    window.openProductModal = function(productId) {
        const p = products.find(prod => prod.id === productId);
        if (!p) return;

        // Build Details
        modalProductImg.src = p.imageUrl;
        modalProductImg.alt = p.title;
        modalProductCategory.textContent = p.category;
        modalProductTitle.textContent = p.title;
        modalProductRating.textContent = p.rating;
        modalProductReviews.textContent = `${p.reviewsCount.toLocaleString()}+ Verified Reviews`;
        modalProductPrice.textContent = `$${p.price.toFixed(2)}`;
        
        // Link with active affiliate tag injected
        modalBuyBtn.href = generateAffiliateLink(p.amazonUrl);

        // Render ratings stars
        let starsHtml = '';
        for (let i = 1; i <= 5; i++) {
            if (i <= Math.floor(p.rating)) {
                starsHtml += '<i class="fa-solid fa-star text-amber-400"></i>';
            } else if (i - p.rating < 1) {
                starsHtml += '<i class="fa-solid fa-star-half-stroke text-amber-400 text-sm"></i>';
            } else {
                starsHtml += '<i class="fa-regular fa-star text-slate-300 text-sm"></i>';
            }
        }
        modalProductStars.innerHTML = starsHtml;

        // Key Specs
        modalProductSpecs.innerHTML = Object.entries(p.specs).map(([key, value]) => `
            <li class="flex flex-col border-b border-slate-100 pb-1">
                <span class="text-slate-400 font-medium text-[10px]">${key}</span>
                <span class="text-slate-800 font-semibold">${value}</span>
            </li>
        `).join('');

        // Pros
        modalProductPros.innerHTML = p.pros.map(pro => `
            <li class="mb-1">${pro}</li>
        `).join('');

        // Cons
        modalProductCons.innerHTML = p.cons.map(con => `
            <li class="mb-1">${con}</li>
        `).join('');

        // Show Modal
        productModal.classList.remove("hidden");
        document.body.style.overflow = "hidden"; // disable background scrolling
    };

    function closeModal() {
        productModal.classList.add("hidden");
        document.body.style.overflow = ""; // enable background scrolling
    }

    // Product Comparison Matrix Drawer logic
    window.toggleCompareItem = function(productId) {
        const index = compareList.indexOf(productId);
        if (index > -1) {
            compareList.splice(index, 1);
        } else {
            if (compareList.length >= 3) {
                alert("You can compare up to 3 devices simultaneously.");
                return;
            }
            compareList.push(productId);
        }

        localStorage.setItem("compare_list", JSON.stringify(compareList));
        updateCompareCounter();
        renderProducts();
        renderComparisonContent();
    };

    function updateCompareCounter() {
        const len = compareList.length;
        if (len > 0) {
            compareCount.textContent = len;
            compareCount.classList.remove("hidden");
        } else {
            compareCount.classList.add("hidden");
        }
    }

    function toggleCompareDrawer() {
        if (compareDrawer.classList.contains("translate-x-full")) {
            renderComparisonContent();
            compareDrawer.classList.remove("translate-x-full");
        } else {
            closeCompareDrawer();
        }
    }

    function closeCompareDrawer() {
        compareDrawer.classList.add("translate-x-full");
    }

    function clearComparison() {
        compareList = [];
        localStorage.removeItem("compare_list");
        updateCompareCounter();
        renderProducts();
        renderComparisonContent();
    }

    function renderComparisonContent() {
        if (compareList.length === 0) {
            compareContent.innerHTML = `
                <div class="h-64 flex flex-col items-center justify-center text-center">
                    <i class="fa-solid fa-shuffle text-3xl text-slate-300 mb-2"></i>
                    <p class="text-slate-700 font-bold">No Products Selected</p>
                    <p class="text-xs text-slate-400 mt-1">Tap the comparison icon on any product card to start comparing specs and prices immediately.</p>
                </div>
            `;
            compareShopAllBtn.classList.add("pointer-events-none", "opacity-50");
            compareShopAllBtn.href = "#";
            return;
        }

        compareShopAllBtn.classList.remove("pointer-events-none", "opacity-50");
        
        // Find matched comparison objects
        const selectedProducts = products.filter(p => compareList.includes(p.id));

        // Let's dynamically map products in comparison table/cards
        compareContent.innerHTML = `
            <div class="grid grid-cols-${selectedProducts.length} gap-4 h-full align-top">
                ${selectedProducts.map(p => `
                    <div class="flex flex-col justify-between border border-slate-200 bg-slate-50/50 rounded-xl p-3 relative h-full">
                        <button onclick="toggleCompareItem('${p.id}')" class="absolute top-1 right-1 text-slate-400 hover:text-red-500 text-xs p-1" title="Remove">
                            <i class="fa-solid fa-circle-minus"></i>
                        </button>
                        
                        <div>
                            <!-- Header / Image -->
                            <div class="h-24 bg-white rounded flex items-center justify-center p-2 mb-3 border border-slate-100">
                                <img src="${p.imageUrl}" alt="${p.title}" class="max-h-full max-w-full object-contain">
                            </div>
                            
                            <!-- Detail info -->
                            <h4 class="font-bold text-xs text-slate-900 line-clamp-2 h-8 leading-tight mb-2">${p.title}</h4>
                            <div class="text-sm font-black text-slate-900 mb-3">$${p.price.toFixed(2)}</div>
                            
                            <!-- Specs list comparison stack -->
                            <div class="space-y-3 mt-2 border-t border-slate-200 pt-3 text-[11px]">
                                <div>
                                    <span class="text-slate-400 block font-semibold uppercase text-[9px]">Rating</span>
                                    <span class="font-bold text-slate-800"><i class="fa-solid fa-star text-amber-400 mr-1"></i>${p.rating}</span>
                                </div>
                                ${Object.entries(p.specs).map(([key, val]) => `
                                    <div>
                                        <span class="text-slate-400 block font-semibold uppercase text-[9px]">${key}</span>
                                        <span class="font-medium text-slate-800 line-clamp-2 leading-none">${val}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>

                        <!-- CTA Bottom Direct Link -->
                        <div class="mt-6">
                            <a href="${generateAffiliateLink(p.amazonUrl)}" target="_blank" rel="noopener sponsored" class="w-full inline-flex items-center justify-center gap-1 bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold text-[11px] py-2 px-1 rounded-lg transition-colors">
                                <i class="fa-brands fa-amazon"></i> Prime Link
                            </a>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        // Direct users to shop comparison links (links open first selected product in separate window)
        if (selectedProducts.length > 0) {
            compareShopAllBtn.href = generateAffiliateLink(selectedProducts[0].amazonUrl);
        }
    }
});
