const products = [
    {
        id: "keychron-q1",
        title: "Keychron Q1 Pro QMK/VIA Custom Wireless Mechanical Keyboard",
        category: "Keyboards",
        price: 198.00,
        rating: 4.8,
        reviewsCount: 312,
        imageUrl: "https://images.unsplash.com/photo-1595225476474-87563907a212?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B0B8S9N8R8", // Mock ASIN for building links
        amazonUrl: "https://www.amazon.com/dp/B0C39CD4WD", 
        specs: {
            "Layout": "75% Mechanical",
            "Switches": "Hot-swappable K Pro Brown",
            "Keycaps": "Double-shot PBT",
            "Connectivity": "Bluetooth 5.1 / Type-C"
        },
        pros: [
            "Heavy-duty aluminum CNC body",
            "Gasket-mounted sound profile",
            "Hot-swappable for fast switches"
        ],
        cons: [
            "Very heavy design, not portable",
            "Stock keycaps don't shine through"
        ],
        featured: true
    },
    {
        id: "mx-master-3s",
        title: "Logitech MX Master 3S Wireless Performance Mouse",
        category: "Smart Office",
        price: 99.99,
        rating: 4.9,
        reviewsCount: 4210,
        imageUrl: "https://images.unsplash.com/photo-1615663245857-ac93bb7c39e7?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B09HM94VDS",
        amazonUrl: "https://www.amazon.com/dp/B09HM94VDS",
        specs: {
            "Sensor": "8K DPI Optical tracking",
            "Battery Life": "Up to 70 days rechargeable",
            "Buttons": "7 Programmable buttons",
            "Connectivity": "Logi Bolt / Bluetooth"
        },
        pros: [
            "Ergonomic fit mitigates wrist strain",
            "Silent tactile clicks",
            "Magspeed scrolling is incredibly fast"
        ],
        cons: [
            "Bulky for smaller hand sizes",
            "Logi Options+ software is heavy"
        ],
        featured: true
    },
    {
        id: "sony-wh1000xm5",
        title: "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        category: "Audio",
        price: 398.00,
        rating: 4.7,
        reviewsCount: 1540,
        imageUrl: "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B09XS7JWHH",
        amazonUrl: "https://www.amazon.com/dp/B09XS7JWHH",
        specs: {
            "Battery": "30 Hours ANC active",
            "Drivers": "30mm custom dome drivers",
            "ANC": "Industry-leading Dual Processor",
            "Weight": "250 Grams lightweight"
        },
        pros: [
            "Incredible active noise cancellation",
            "Extremely comfortable long wear",
            "Superior microphone voice pickup"
        ],
        cons: [
            "Cannot fold completely flat",
            "Touch sensor inputs can be touchy in cold"
        ],
        featured: true
    },
    {
        id: "lg-ultrawide-38",
        title: "LG UltraWide Curved Monitor 38-Inch WQHD+",
        category: "Monitors",
        price: 896.99,
        rating: 4.6,
        reviewsCount: 650,
        imageUrl: "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B0892MHGZ8",
        amazonUrl: "https://www.amazon.com/dp/B0892MHGZ8",
        specs: {
            "Resolution": "3840 x 1600 Curvature",
            "Panel Type": "Nano IPS Panel",
            "Refresh Rate": "144Hz high refresh",
            "Ports": "USB Type-C (90W Delivery)"
        },
        pros: [
            "Seamless multi-window window layout",
            "Vibrant color coverage & wide gamut",
            "Single USB-C runs monitor and power"
        ],
        cons: [
            "Requires substantial desk space",
            "Expensive compared to standard dual-setups"
        ],
        featured: false
    },
    {
        id: "glorious-gmmk-2",
        title: "Glorious GMMK 2 Compact Mechanical Keyboard",
        category: "Keyboards",
        price: 119.99,
        rating: 4.5,
        reviewsCount: 480,
        imageUrl: "https://images.unsplash.com/photo-1618384887929-16ec33fab9ef?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B09V7N8WSD",
        amazonUrl: "https://www.amazon.com/dp/B09V7N8WSD",
        specs: {
            "Layout": "65% Space-saving design",
            "Switches": "Glorious Fox Linear",
            "RGB": "Vibrant custom backlight per key",
            "Frame": "Anodized aluminum top plate"
        },
        pros: [
            "Smooth linear switches out of the box",
            "Robust customization software",
            "Great affordable modular mechanical"
        ],
        cons: [
            "ABS keycaps feel cheaper over time",
            "Stabilizers require manual lube to shine"
        ],
        featured: false
    },
    {
        id: "caldigit-ts4",
        title: "CalDigit TS4 Thunderbolt 4 Station 18-Port Dock",
        category: "Smart Office",
        price: 399.99,
        rating: 4.8,
        reviewsCount: 890,
        imageUrl: "https://images.unsplash.com/photo-1547082299-de196ea013d6?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B09GK6S55V",
        amazonUrl: "https://www.amazon.com/dp/B09GK6S55V",
        specs: {
            "Power Delivery": "Up to 98W host charging",
            "Ports": "18 versatile connection interfaces",
            "Max Display": "Dual 6K @ 60Hz supported",
            "Speed": "40Gbps maximum transfer bandwidth"
        },
        pros: [
            "Extremely high number of fast USB/TB ports",
            "Excellent build quality and heatsink layout",
            "Flawless macOS/Windows integration"
        ],
        cons: [
            "Very expensive compared to basic docks",
            "Heats up noticeably during maximum load"
        ],
        featured: true
    },
    {
        id: "shure-sm7b",
        title: "Shure SM7B Vocal Dynamic Studio Microphone",
        category: "Audio",
        price: 399.00,
        rating: 4.9,
        reviewsCount: 3105,
        imageUrl: "https://images.unsplash.com/photo-1590608897129-79da98d15969?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B0002E4Z8M",
        amazonUrl: "https://www.amazon.com/dp/B0002E4Z8M",
        specs: {
            "Mic Type": "Cardioid Dynamic",
            "Frequency Range": "50 to 20,000 Hz",
            "Interface": "XLR connection required",
            "Best For": "Podcasting, streaming, vocals"
        },
        pros: [
            "Unrivaled crisp studio broadcast sound",
            "Excellent electromagnetic hum shielding",
            "Durable metal frame lasts a lifetime"
        ],
        cons: [
            "Needs high-gain pre-amp or Cloudlifter",
            "Does not come with XLR cables or arm"
        ],
        featured: false
    },
    {
        id: "benq-screenbar-plus",
        title: "BenQ ScreenBar Plus Monitor Light Bar & Controller",
        category: "Monitors",
        price: 139.00,
        rating: 4.7,
        reviewsCount: 1980,
        imageUrl: "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?auto=format&fit=crop&q=80&w=600",
        amazonAsin: "B07DP7RY56",
        amazonUrl: "https://www.amazon.com/dp/B07DP7RY56",
        specs: {
            "Controller": "Desktop dial adjustments",
            "Power Supply": "USB Powered 5V",
            "Optics": "Asymmetric optical setup",
            "Material": "Premium Aluminum alloy"
        },
        pros: [
            "Reduces screen glare & direct eye fatigue",
            "Asymmetric light path avoids reflection",
            "Saves valuable desktop real estate"
        ],
        cons: [
            "Desktop controller adds an extra wire",
            "Hard to clip onto ultra-curved panels"
        ],
        featured: false
    }
];
